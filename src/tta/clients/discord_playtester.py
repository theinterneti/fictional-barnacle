"""Discord playtester bot for TTA.

Shares the FastAPI event loop — started in the lifespan handler.
Each Discord user gets their own game session with a guided genesis
flow followed by free-text turn input.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import discord
import sqlalchemy as sa
import structlog
from discord.ext import commands

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession

    from tta.config import Settings

log = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────

COLOUR_DARK = 0x5B2C8E
COLOUR_HOPEFUL = 0x2ECC71
COLOUR_MYSTERIOUS = 0x3498DB
COLOUR_COMEDIC = 0xF1C40F
COLOUR_SYSTEM = 0x95A5A6
COLOUR_ERROR = 0xE74C3C

GEORGIAN_FANTASY_ID = 1500633449881538722  # Spamento's server
DEFAULT_CHANNEL_ID = 1500635920334852228  # hermes-home

GENESIS_QUESTIONS: list[dict[str, Any]] = [
    {
        "key": "tone",
        "prompt": "What mood should the story have?",
        "options": ["dark", "hopeful", "mysterious", "comedic"],
    },
    {
        "key": "tech_level",
        "prompt": "What's the technology level?",
        "options": ["medieval", "renaissance", "modern", "far_future"],
    },
    {
        "key": "magic_presence",
        "prompt": "How present is magic in this world?",
        "options": ["none", "rare", "common", "pervasive"],
    },
    {
        "key": "world_scale",
        "prompt": "What's the scale of the world?",
        "options": ["village", "city", "kingdom", "continent"],
    },
    {
        "key": "player_position",
        "prompt": "What is your character's role?",
        "options": ["outsider", "local", "authority", "fugitive"],
    },
    {
        "key": "power_source",
        "prompt": "What drives power in this world?",
        "options": ["politics", "magic", "technology", "nature"],
    },
    {
        "key": "defining_detail",
        "prompt": "One unique detail about this world?",
        "options": [],
        "free_text": True,
    },
    {
        "key": "character_name",
        "prompt": "What's your character's name?",
        "options": [],
        "free_text": True,
    },
    {
        "key": "character_concept",
        "prompt": "A few words about your character's background?",
        "options": [],
        "free_text": True,
    },
]

_PREF_KEYS = {q["key"] for q in GENESIS_QUESTIONS}

# ── State machine ──────────────────────────────────────────────


class PlayerPhase(StrEnum):
    IDLE = "idle"
    GENESIS = "genesis"  # answering genesis questions
    CREATING = "creating"  # game creation in progress
    PLAYING = "playing"


@dataclass
class PlayerSession:
    """Per-Discord-user game state (in-memory for v1)."""

    phase: PlayerPhase = PlayerPhase.IDLE
    genesis_index: int = 0
    genesis_prefs: dict[str, str] = field(default_factory=dict)
    player_id: UUID | None = None
    game_id: UUID | None = None
    character_name: str | None = None


# ── Helper: parse narrative into choice buttons ────────────────

_CHOICE_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:\d+[.)]\s*|[-•]\s+)(.+?)(?=\n\s*(?:\d+[.)]\s*|[-•]\s+)|\Z)",
    re.MULTILINE,
)


def _extract_choices(text: str, max_choices: int = 5) -> list[str]:
    """Extract numbered or bulleted choices from narrative text."""
    if not text:
        return []
    # Look for lines starting with digits or bullets
    matches = _CHOICE_PATTERN.findall(text)
    choices = [m.strip() for m in matches if len(m.strip()) > 3]
    return choices[:max_choices]


# ── Helper: internal game operations ───────────────────────────
async def _get_or_create_player(
    session_factory: async_sessionmaker[AsyncSession],
    discord_id: int,
    discord_name: str,
) -> UUID:
    """Find existing player by Discord handle or create a new anonymous one."""
    handle = f"discord:{discord_id}"
    async with session_factory() as pg:
        result = await pg.execute(
            sa.text(
                "SELECT id FROM players WHERE handle = :handle LIMIT 1"
            ),
            {"handle": handle},
        )
        row = result.one_or_none()
        if row is not None:
            return row.id  # type: ignore[return-value]

        # Create new anonymous player
        player_id = uuid4()
        await pg.execute(
            sa.text(
                "INSERT INTO players (id, handle) "
                "VALUES (:id, :handle)"
            ),
            {"id": player_id, "handle": handle},
        )
        await pg.commit()
        log.info(
            "discord_player_created",
            discord_id=str(discord_id),
            player_id=str(player_id),
        )
        return player_id


async def _create_game(
    session_factory: async_sessionmaker[AsyncSession],
    player_id: UUID,
    prefs: dict[str, str],
    app_state: Any,
) -> tuple[UUID, str | None, str | None]:
    """Create a game session with genesis, return (game_id, intro, error)."""
    game_id = uuid4()
    now = datetime.now(UTC)
    profile = "balanced"
    world_seed_json = {
        "world_id": None,
        "preferences": {k: v for k, v in prefs.items() if k in _PREF_KEYS},
        "generation_profile": profile,
    }

    async with session_factory() as pg:
        await pg.execute(
            sa.text(
                "INSERT INTO game_sessions "
                "(id, player_id, status, world_seed, generation_profile, "
                "created_at, updated_at, last_played_at) "
                "VALUES (:id, :pid, :status, cast(:seed AS jsonb), "
                ":profile, :now, :now, :now)"
            ),
            {
                "id": game_id,
                "pid": player_id,
                "status": "created",
                "seed": json.dumps(world_seed_json),
                "profile": profile,
                "now": now,
            },
        )
        await pg.commit()

    # --- Genesis ---
    narrative_intro: str | None = None
    error_msg: str | None = None

    try:
        registry = getattr(app_state, "template_registry", None)
        if registry is None:
            raise RuntimeError("template_registry not on app state")

        from tta.models.world import WorldSeed

        template = registry.select_by_preferences(prefs)
        seed = WorldSeed(
            template=template,
            tone=prefs.get("tone"),
            tech_level=prefs.get("tech_level"),
            magic_presence=prefs.get("magic_presence"),
            world_scale=prefs.get("world_scale"),
            player_position=prefs.get("player_position"),
            power_source=prefs.get("power_source"),
            defining_detail=prefs.get("defining_detail"),
            character_name=prefs.get("character_name"),
            character_concept=prefs.get("character_concept"),
        )

        from tta.genesis.genesis_lite import run_genesis_lite

        settings: Settings = app_state.settings
        abort_s = settings.latency_budget_abort_ms / 1000.0
        budget_s = max(0.05, min(settings.pipeline_timeout_seconds, abort_s * 0.8))

        result = await asyncio.wait_for(
            run_genesis_lite(
                session_id=game_id,
                player_id=player_id,
                world_seed=seed,
                llm=app_state.llm_client,
                world_service=app_state.world_service,
                generation_profile=profile,
            ),
            timeout=budget_s,
        )
        narrative_intro = result.narrative_intro

        # Persist genesis result
        world_seed_json["genesis"] = {
            "status": "complete",
            "world_id": result.world_id,
            "player_location_id": result.player_location_id,
            "template_key": result.template_key,
            "narrative_intro": result.narrative_intro,
            "genesis_elements": result.genesis_elements,
        }
        async with session_factory() as pg:
            await pg.execute(
                sa.text(
                    "UPDATE game_sessions "
                    "SET world_seed = cast(:seed AS jsonb), "
                    "status = 'active', updated_at = :now "
                    "WHERE id = :gid"
                ),
                {
                    "seed": json.dumps(world_seed_json),
                    "now": datetime.now(UTC),
                    "gid": game_id,
                },
            )
            await pg.commit()
        log.info("discord_genesis_complete", game_id=str(game_id))
    except TimeoutError:
        error_msg = "World generation timed out before the intro was ready."
    except Exception as exc:
        error_msg = f"World generation failed: {exc}"
        log.warning("discord_genesis_failed", game_id=str(game_id), error=str(exc))

    return game_id, narrative_intro, error_msg


async def _submit_turn(
    session_factory: async_sessionmaker[AsyncSession],
    game_id: UUID,
    player_input: str,
    app_state: Any,
) -> dict[str, Any]:
    """Submit a turn via the pipeline, return the result dict."""
    from tta.pipeline.orchestrator import dispatch_pipeline

    settings: Settings = app_state.settings
    try:
        report = await asyncio.wait_for(
            dispatch_pipeline(
                game_session_id=game_id,
                player_input=player_input,
                deps=app_state.pipeline_deps,
            ),
            timeout=settings.pipeline_timeout_seconds,
        )
        return {
            "success": True,
            "narrative": report.narrative_output or "",
            "turn_id": str(report.turn_id) if report.turn_id else None,
            "turn_number": getattr(report, "turn_number", None),
        }
    except Exception as exc:
        log.warning("discord_turn_failed", game_id=str(game_id), error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Bot ────────────────────────────────────────────────────────


class TTAPlaytesterBot(commands.Bot):
    """Discord bot that wraps the full TTA game loop."""

    def __init__(
        self,
        *,
        channel_id: int,
        session_factory: async_sessionmaker[AsyncSession],
        app_state: Any,
        **kwargs: Any,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,  # custom help
            **kwargs,
        )
        self._channel_id = channel_id
        self._pg = session_factory
        self._app_state = app_state
        self._sessions: dict[int, PlayerSession] = {}  # discord_id → session

    def _get_session(self, user_id: int) -> PlayerSession:
        if user_id not in self._sessions:
            self._sessions[user_id] = PlayerSession()
        return self._sessions[user_id]

    async def on_ready(self) -> None:
        log.info("discord_bot_ready", user=str(self.user))
        channel = self.get_channel(self._channel_id)
        if channel:
            await channel.send(
                embed=discord.Embed(
                    title="TTA Playtester Online",
                    description="Type **!play** to begin your adventure!",
                    color=COLOUR_SYSTEM,
                )
            )

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.channel.id != self._channel_id:
            return
        # Diagnostic: echo what the bot sees
        log.info(
            "discord_message_received",
            author=str(message.author),
            content=message.content[:100],
        )

        user_id = message.author.id
        content = message.content.strip()
        session = self._get_session(user_id)

        # Commands always work
        if content.lower() == "!play":
            await self.cmd_play_direct(message)
            return
        if content.lower() == "!help":
            await self.cmd_help_direct(message)
            return
        if content.lower() == "!status":
            await self.cmd_status_direct(message)
            return
        if content.lower() == "!end":
            await self.cmd_end_direct(message)
            return
        if content.lower() == "!save":
            await self.cmd_save_direct(message)
            return
        if content.startswith("!"):
            await message.channel.send(f"Unknown command. Type **!help** for commands.")
            return

        # Route by phase
        if session.phase == PlayerPhase.IDLE:
            if content:
                await message.channel.send(
                    embed=discord.Embed(
                        title="TTA Playtester",
                        description=(
                            "Type **!play** to start a new adventure!\n"
                            "Type **!help** for commands."
                        ),
                        color=COLOUR_SYSTEM,
                    )
                )
        elif session.phase == PlayerPhase.GENESIS:
            await self._handle_genesis_answer(message, session)
        elif session.phase == PlayerPhase.PLAYING:
            await self._handle_turn(message, session)

    # ── Commands ────────────────────────────────────────────

    @commands.command(name="play")
    async def cmd_play(self, ctx: commands.Context) -> None:
        """Start a new game."""
        session = self._get_session(ctx.author.id)
        if session.phase != PlayerPhase.IDLE:
            await ctx.send("You're already in a game! Type **!end** to stop.")
            return
        session.phase = PlayerPhase.GENESIS
        session.genesis_index = 0
        session.genesis_prefs = {}
        await self._send_genesis_question(ctx.channel, session)

    @commands.command(name="end")
    async def cmd_end(self, ctx: commands.Context) -> None:
        """End the current game."""
        session = self._get_session(ctx.author.id)
        if session.phase == PlayerPhase.IDLE:
            await ctx.send("No game in progress.")
            return
        gid = session.game_id
        session.phase = PlayerPhase.IDLE
        session.game_id = None
        session.genesis_prefs = {}
        session.genesis_index = 0
        if gid:
            async with self._pg() as pg:
                await pg.execute(
                    sa.text(
                        "UPDATE game_sessions SET status = 'ended', "
                        "updated_at = :now WHERE id = :gid"
                    ),
                    {"gid": gid, "now": datetime.now(UTC)},
                )
                await pg.commit()
        await ctx.send(
            embed=discord.Embed(
                title="Game Ended",
                description=(
                    "Your adventure has ended. "
                    "Type **!play** to start a new one."
                ),
                color=COLOUR_SYSTEM,
            )
        )

    @commands.command(name="save")
    async def cmd_save(self, ctx: commands.Context) -> None:
        """Save the current game."""
        session = self._get_session(ctx.author.id)
        if session.phase != PlayerPhase.PLAYING or not session.game_id:
            await ctx.send("No active game to save.")
            return
        async with self._pg() as pg:
            await pg.execute(
                sa.text("UPDATE game_sessions SET updated_at = :now WHERE id = :gid"),
                {"gid": session.game_id, "now": datetime.now(UTC)},
            )
            await pg.commit()
        await ctx.send(
            embed=discord.Embed(
                title="Game Saved",
                description="Your progress has been saved.",
                color=COLOUR_SYSTEM,
            )
        )

    @commands.command(name="status")
    async def cmd_status(self, ctx: commands.Context) -> None:
        """Show current game status."""
        session = self._get_session(ctx.author.id)
        if session.phase == PlayerPhase.IDLE:
            await ctx.send("No game in progress. Type **!play** to start.")
            return
        phase_str = {
            PlayerPhase.IDLE: "Idle",
            PlayerPhase.GENESIS: f"Genesis (question {session.genesis_index + 1}/9)",
            PlayerPhase.CREATING: "Creating world...",
            PlayerPhase.PLAYING: "Playing",
        }.get(session.phase, str(session.phase))
        name = session.character_name or "Unknown"
        await ctx.send(
            embed=discord.Embed(
                title="Game Status",
                description=(
                    f"**Phase**: {phase_str}\n"
                    f"**Character**: {name}\n"
                    f"**Game ID**: {session.game_id or 'N/A'}"
                ),
                color=COLOUR_SYSTEM,
            )
        )

    @commands.command(name="help")
    async def cmd_help(self, ctx: commands.Context) -> None:
        """Show available commands."""
        await ctx.send(
            embed=discord.Embed(
                title="TTA Playtester — Commands",
                description=(
                    "**!play** — Start a new adventure\n"
                    "**!end** — End your current game\n"
                    "**!save** — Save your progress\n"
                    "**!status** — Show game status\n"
                    "**!quick** — Skip genesis questions (use defaults)\n"
                    "**!help** — Show this help\n"
                    "\nDuring genesis, type a number (1-4) to pick an "
                    "option, or type your own answer.\n"
                    "During play, just type your action!"
                ),
                color=COLOUR_SYSTEM,
            )
        )

    @commands.command(name="quick")
    async def cmd_quick(self, ctx: commands.Context) -> None:
        """Skip genesis questions with defaults."""
        session = self._get_session(ctx.author.id)
        if session.phase != PlayerPhase.GENESIS:
            await ctx.send("Not in genesis. Type **!play** to start.")
            return
        # Fill remaining questions with defaults (first option)
        for q in GENESIS_QUESTIONS[session.genesis_index :]:
            key = q["key"]
            options = q.get("options", [])
            session.genesis_prefs[key] = options[0] if options else "mystery"
        session.genesis_index = len(GENESIS_QUESTIONS)
        await self._finish_genesis(ctx.channel, ctx.author.id, session)

    # ── Direct command handlers (bypass commands.Bot decorator issues) ──

    async def cmd_play_direct(self, message: discord.Message) -> None:
        """Handle !play directly."""
        session = self._get_session(message.author.id)
        if session.phase != PlayerPhase.IDLE:
            await message.channel.send(
                "You're already in a game! Type **!end** to stop."
            )
            return
        session.phase = PlayerPhase.GENESIS
        session.genesis_index = 0
        session.genesis_prefs = {}
        await self._send_genesis_question(message.channel, session)

    async def cmd_help_direct(self, message: discord.Message) -> None:
        """Handle !help directly."""
        await message.channel.send(
            embed=discord.Embed(
                title="TTA Playtester — Commands",
                description=(
                    "**!play** — Start a new adventure\n"
                    "**!end** — End your current game\n"
                    "**!save** — Save your progress\n"
                    "**!status** — Show game status\n"
                    "**!help** — Show this help"
                ),
                color=COLOUR_SYSTEM,
            )
        )

    async def cmd_status_direct(self, message: discord.Message) -> None:
        """Handle !status directly."""
        session = self._get_session(message.author.id)
        if session.phase == PlayerPhase.IDLE:
            await message.channel.send(
                "No game in progress. Type **!play** to start."
            )
            return
        phase_str = {
            PlayerPhase.GENESIS: f"Genesis (question {session.genesis_index + 1}/9)",
            PlayerPhase.CREATING: "Creating world...",
            PlayerPhase.PLAYING: "Playing",
        }.get(session.phase, str(session.phase))
        await message.channel.send(
            f"**Phase**: {phase_str}\n**Game ID**: {session.game_id or 'N/A'}"
        )

    async def cmd_end_direct(self, message: discord.Message) -> None:
        """Handle !end directly."""
        session = self._get_session(message.author.id)
        if session.phase == PlayerPhase.IDLE:
            await message.channel.send("No game in progress.")
            return
        gid = session.game_id
        session.phase = PlayerPhase.IDLE
        session.game_id = None
        session.genesis_prefs = {}
        session.genesis_index = 0
        if gid:
            async with self._pg() as pg:
                await pg.execute(
                    sa.text(
                        "UPDATE game_sessions SET status = 'ended', "
                        "updated_at = :now WHERE id = :gid"
                    ),
                    {"gid": gid, "now": datetime.now(UTC)},
                )
                await pg.commit()
        await message.channel.send("Game ended. Type **!play** to start a new one.")

    async def cmd_save_direct(self, message: discord.Message) -> None:
        """Handle !save directly."""
        session = self._get_session(message.author.id)
        if session.phase != PlayerPhase.PLAYING or not session.game_id:
            await message.channel.send("No active game to save.")
            return
        async with self._pg() as pg:
            await pg.execute(
                sa.text(
                    "UPDATE game_sessions SET updated_at = :now "
                    "WHERE id = :gid"
                ),
                {"gid": session.game_id, "now": datetime.now(UTC)},
            )
            await pg.commit()
        await message.channel.send("Game saved.")

    # ── Genesis flow ────────────────────────────────────────

    async def _send_genesis_question(
        self, channel: discord.TextChannel, session: PlayerSession
    ) -> None:
        q = GENESIS_QUESTIONS[session.genesis_index]
        options_text = ""
        for i, opt in enumerate(q.get("options", []), 1):
            options_text += f"{i}. {opt}\n"
        desc = q["prompt"]
        if options_text:
            desc += f"\n\n{options_text}"
        if q.get("free_text"):
            desc += "\n*(type your own answer)*"

        await channel.send(
            embed=discord.Embed(
                title=f"Genesis — Question {session.genesis_index + 1}/9",
                description=desc,
                color=COLOUR_MYSTERIOUS,
            )
        )

    async def _handle_genesis_answer(
        self, message: discord.Message, session: PlayerSession
    ) -> None:
        q = GENESIS_QUESTIONS[session.genesis_index]
        options = q.get("options", [])
        content = message.content.strip()

        # Try numeric choice
        answer = content
        if content.isdigit() and options:
            idx = int(content) - 1
            if 0 <= idx < len(options):
                answer = options[idx]

        session.genesis_prefs[q["key"]] = answer
        session.genesis_index += 1

        if session.genesis_index >= len(GENESIS_QUESTIONS):
            await self._finish_genesis(message.channel, message.author.id, session)
        else:
            await self._send_genesis_question(message.channel, session)

    async def _finish_genesis(
        self,
        channel: discord.TextChannel,
        user_id: int,
        session: PlayerSession,
    ) -> None:
        session.phase = PlayerPhase.CREATING
        await channel.send(
            embed=discord.Embed(
                title="Shaping your world...",
                description=(
                    f"**{session.genesis_prefs.get('character_name', 'Hero')}** "
                    f"enters a {session.genesis_prefs.get('tone', 'mysterious')} "
                    f"world...\n\n"
                    "Genesis may take 30-60 seconds — the world is being built."
                ),
                color=COLOUR_DARK,
            )
        )

        try:
            player_id = await _get_or_create_player(
                self._pg,
                user_id,
                getattr(
                    channel.guild.get_member(user_id) if channel.guild else None,
                    "display_name",
                    "player",
                ),
            )
            session.player_id = player_id

            game_id, intro, error = await _create_game(
                self._pg, player_id, session.genesis_prefs, self._app_state
            )

            if error:
                session.phase = PlayerPhase.IDLE
                await channel.send(
                    embed=discord.Embed(
                        title="Genesis Failed",
                        description=error,
                        color=COLOUR_ERROR,
                    )
                )
                return

            session.game_id = game_id
            session.character_name = session.genesis_prefs.get("character_name", "Hero")
            session.phase = PlayerPhase.PLAYING

            # Send narrative intro
            intro_text = intro or "Your adventure begins..."
            # Truncate to Discord embed limit
            if len(intro_text) > 4000:
                intro_text = intro_text[:3997] + "..."

            # Pick color by tone
            tone = session.genesis_prefs.get("tone", "mysterious")
            tone_colour = {
                "dark": COLOUR_DARK,
                "hopeful": COLOUR_HOPEFUL,
                "mysterious": COLOUR_MYSTERIOUS,
                "comedic": COLOUR_COMEDIC,
            }.get(tone, COLOUR_MYSTERIOUS)

            name = session.character_name
            await channel.send(
                embed=discord.Embed(
                    title=f"Turn 1 — {name}'s Story Begins",
                    description=intro_text,
                    color=tone_colour,
                ).set_footer(text=f"Game {str(game_id)[:8]}... — type your action")
            )

            # Show choices if extractable
            choices = _extract_choices(intro_text)
            if choices:
                choice_text = "\n".join(
                    f"{i + 1}. {c}" for i, c in enumerate(choices[:5])
                )
                await channel.send(
                    embed=discord.Embed(
                        title="What do you do?",
                        description=choice_text,
                        color=tone_colour,
                    )
                )

        except Exception as exc:
            session.phase = PlayerPhase.IDLE
            log.exception("discord_genesis_crash", user_id=user_id)
            await channel.send(
                embed=discord.Embed(
                    title="Error",
                    description=f"Something went wrong: {exc}",
                    color=COLOUR_ERROR,
                )
            )

    # ── Turn flow ───────────────────────────────────────────

    async def _handle_turn(
        self, message: discord.Message, session: PlayerSession
    ) -> None:
        assert session.game_id is not None
        user_input = message.content.strip()

        thinking = await message.channel.send(
            embed=discord.Embed(
                title="Thinking...",
                description=f"*{session.character_name or 'You'} {user_input}*",
                color=COLOUR_SYSTEM,
            )
        )

        result = await _submit_turn(
            self._pg, session.game_id, user_input, self._app_state
        )

        await thinking.delete()

        if not result["success"]:
            await message.channel.send(
                embed=discord.Embed(
                    title="Turn Failed",
                    description=result.get("error", "Unknown error"),
                    color=COLOUR_ERROR,
                )
            )
            return

        narrative = result["narrative"]
        turn_num = result.get("turn_number") or 1

        # Truncate
        if len(narrative) > 4000:
            narrative = narrative[:3997] + "..."

        await message.channel.send(
            embed=discord.Embed(
                title=f"Turn {turn_num}",
                description=narrative,
                color=COLOUR_MYSTERIOUS,
            ).set_footer(
                text=f"Game {str(session.game_id)[:8]}... — type your next action"
            )
        )

        # Extract and show choices
        choices = _extract_choices(narrative)
        if choices:
            choice_text = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(choices[:5]))
            await message.channel.send(
                embed=discord.Embed(
                    title="Suggested Actions",
                    description=choice_text,
                    color=COLOUR_SYSTEM,
                )
            )


# ── Lifespan integration ──────────────────────────────────────


def create_bot(
    *,
    channel_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    app_state: Any,
) -> TTAPlaytesterBot:
    """Factory for the Discord bot (called from app lifespan)."""
    return TTAPlaytesterBot(
        channel_id=channel_id,
        session_factory=session_factory,
        app_state=app_state,
    )
