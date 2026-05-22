"""Slash-command implementation for games routes.

Handles /help, /save, /status, /character, /relationships, /end commands
and LLM-powered epilogue generation. Extracted from games.py during code
health decomposition.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.routes.games_helpers import _get_turn_count

log = structlog.get_logger(__name__)


# --- Command router (S01 AC-1.10) ---

_KNOWN_COMMANDS = frozenset(
    {
        "help",
        "save",
        "status",
        "character",
        "relationships",
        "end",
    }
)

_HELP_TEXT = (
    "Available commands:\n"
    "  /help          \u2014 Show this list of commands\n"
    "  /save          \u2014 Save your current progress\n"
    "  /status        \u2014 View your game session info\n"
    "  /character     \u2014 View your character details\n"
    "  /relationships \u2014 See the people you've met\n"
    "  /end           \u2014 End your story and see your epilogue\n"
    "\nOr simply type what you'd like to do in the world."
)


def _parse_slash_command(normalized: str) -> str | None:
    """Return the command name if input is a known slash command, else None."""
    if not normalized.startswith("/"):
        return None
    parts = normalized[1:].split(None, 1)
    if not parts:
        return None
    cmd = parts[0].lower()
    return cmd if cmd in _KNOWN_COMMANDS else None


async def _execute_command(
    cmd: str,
    game_id: UUID,
    row: object,
    pg: AsyncSession,
    *,
    template_registry: object | None = None,
    relationship_service: Any | None = None,
    llm_client: Any | None = None,
) -> dict:
    """Execute a known slash command and return response payload."""
    if cmd == "help":
        return {"type": "command", "command": "help", "message": _HELP_TEXT}

    if cmd == "save":
        now = datetime.now(UTC)
        await pg.execute(
            sa.text("UPDATE game_sessions SET updated_at = :now WHERE id = :id"),
            {"id": game_id, "now": now},
        )
        await pg.commit()
        return {
            "type": "command",
            "command": "save",
            "message": "Your progress has been saved.",
        }

    if cmd == "status":
        turn_count = getattr(row, "turn_count", 0)
        last_played = (
            row.last_played_at.strftime("%Y-%m-%d %H:%M UTC")  # type: ignore[union-attr]
            if getattr(row, "last_played_at", None)
            else "Never"
        )
        template = getattr(row, "template_id", None) or "custom"
        msg = (
            f"Game Status\n"
            f"  Session: {game_id}\n"
            f"  Status: {row.status}\n"  # type: ignore[union-attr]
            f"  World: {template}\n"
            f"  Turns played: {turn_count}\n"
            f"  Last played: {last_played}"
        )
        return {"type": "command", "command": "status", "message": msg}

    if cmd == "character":
        return _build_character_response(row)

    if cmd == "relationships":
        return await _build_relationships_response(
            row,
            game_id=game_id,
            template_registry=template_registry,
            relationship_service=relationship_service,
        )

    if cmd == "end":
        return await _execute_end_command(game_id, row, pg, llm_client=llm_client)

    return {"type": "command", "command": "help", "message": _HELP_TEXT}


def _build_character_response(row: object) -> dict:
    """Build response for /character command from persisted world_seed dict.

    Shows all available character and world fields richly (S06 AC-6.1).
    """
    ws_raw = getattr(row, "world_seed", None)
    if not ws_raw or not isinstance(ws_raw, dict):
        return {
            "type": "command",
            "command": "character",
            "message": "Your character hasn't been created yet. "
            "Play a turn to begin your story.",
        }
    prefs = ws_raw.get("preferences", {})
    name = prefs.get("character_name") or "Unknown"
    concept = prefs.get("character_concept") or "A wanderer with no known past"
    parts = [f"Character: {name}", f"  Concept: {concept}"]

    tone = prefs.get("tone")
    if tone:
        parts.append(f"  Tone: {tone}")
    genre = prefs.get("genre")
    if genre:
        parts.append(f"  Genre: {genre}")
    defining = prefs.get("defining_detail")
    if defining:
        parts.append(f"  Defining detail: {defining}")
    tech = prefs.get("tech_level")
    if tech:
        parts.append(f"  Tech level: {tech}")
    magic = prefs.get("magic_presence")
    if magic:
        parts.append(f"  Magic: {magic}")
    scale = prefs.get("world_scale")
    if scale:
        parts.append(f"  World scale: {scale}")

    return {
        "type": "command",
        "command": "character",
        "message": "\n".join(parts),
    }


def _dimension_label(value: int, positive: str, negative: str) -> str:
    """Map a dimension value to a narrative descriptor."""
    if value >= 60:
        return f"very {positive}"
    if value >= 30:
        return positive
    if value >= -10:
        return "neutral"
    if value >= -40:
        return negative
    return f"very {negative}"


async def _build_relationships_response(
    row: object,
    *,
    game_id: UUID | None = None,
    template_registry: object | None = None,
    relationship_service: Any | None = None,
) -> dict:
    """Build response for /relationships command.

    Prefers runtime relationship dimensions from RelationshipService.
    Falls back to template NPC list when no runtime data exists (S06 AC-6.3).
    """
    ws_raw = getattr(row, "world_seed", None)
    if not ws_raw or not isinstance(ws_raw, dict):
        return {
            "type": "command",
            "command": "relationships",
            "message": "You haven't met anyone yet.",
        }

    # Try runtime relationships first
    if relationship_service and game_id:
        try:
            rels = await relationship_service.get_relationships_for(
                session_id=game_id,
                entity_id="player",
            )
        except Exception:
            log.warning(
                "runtime relationship lookup failed; falling back to template NPCs",
                session_id=str(game_id),
                exc_info=True,
            )
            rels = []
        if rels:
            lines = ["People you know:"]
            for rel in rels:
                name = rel.target_id.replace("_", " ").title()
                d = rel.dimensions
                parts = [
                    _dimension_label(d.trust, "trusting", "wary"),
                    _dimension_label(d.affinity, "warm", "cold"),
                    _dimension_label(d.respect, "respectful", "dismissive"),
                ]
                if d.fear > 20:
                    parts.append("fearful" if d.fear < 60 else "very fearful")
                desc = ", ".join(parts)
                lines.append(f"  {name} — {desc}")
            return {
                "type": "command",
                "command": "relationships",
                "message": "\n".join(lines),
            }

    # Fallback: template NPCs
    template_key = ws_raw.get("genesis", {}).get("template_key")
    if not template_key or not template_registry:
        return {
            "type": "command",
            "command": "relationships",
            "message": "You haven't met anyone yet.",
        }
    try:
        template = template_registry.get(template_key)  # type: ignore[union-attr]
    except (KeyError, AttributeError):
        return {
            "type": "command",
            "command": "relationships",
            "message": "Relationship details are unavailable.",
        }
    npcs = getattr(template, "npcs", None) or []
    if not npcs:
        return {
            "type": "command",
            "command": "relationships",
            "message": "You haven't met anyone yet.",
        }
    lines = ["People you know:"]
    for npc in npcs:
        name = npc.key.replace("_", " ").title()
        role_label = npc.role.value if hasattr(npc.role, "value") else str(npc.role)
        lines.append(f"  {name} — {role_label}, {npc.disposition}")
    return {
        "type": "command",
        "command": "relationships",
        "message": "\n".join(lines),
    }


async def _execute_end_command(
    game_id: UUID,
    row: object,
    pg: AsyncSession,
    *,
    llm_client: Any | None = None,
) -> dict:
    """End the current game and return an epilogue message (AC-1.6).

    Generates an LLM-powered epilogue narrative referencing the player's
    journey, then archives the game and presents the option to begin a new
    adventure. Falls back to a static epilogue if the LLM is unavailable.
    """
    status = getattr(row, "status", None)
    if status in ("ended", "completed", "abandoned"):
        return {
            "type": "command",
            "command": "end",
            "message": "This story has already concluded.",
        }
    now = datetime.now(UTC)
    await pg.execute(
        sa.text(
            "UPDATE game_sessions SET status = 'ended', "
            "updated_at = :now WHERE id = :id"
        ),
        {"id": game_id, "now": now},
    )
    await pg.commit()
    turn_count = await _get_turn_count(pg, game_id)

    # Extract character/world context from world_seed
    name = "Traveler"
    world_name = "this world"
    ws_raw = getattr(row, "world_seed", None)
    if isinstance(ws_raw, dict):
        name = ws_raw.get("preferences", {}).get("character_name") or name
        world_name = ws_raw.get("world_name") or ws_raw.get("name") or world_name

    summary = getattr(row, "summary", None) or ""

    epilogue = await _generate_epilogue(
        llm_client=llm_client,
        character_name=name,
        world_name=world_name,
        turn_count=turn_count,
        summary=summary,
    )

    return {"type": "command", "command": "end", "message": epilogue}


async def _generate_epilogue(
    *,
    llm_client: Any | None,
    character_name: str,
    world_name: str,
    turn_count: int,
    summary: str,
) -> str:
    """Generate an LLM-powered epilogue or fall back to a static one."""
    fallback = (
        f"— Epilogue: What Remained —\n\n"
        f"The story of {character_name} comes to a close.\n"
        f"Over {turn_count} turn{'s' if turn_count != 1 else ''}, "
        f"you shaped {world_name} with your choices.\n\n"
        "Thank you for playing. "
        "Start a new game whenever you're ready for another adventure."
    )
    if llm_client is None:
        return fallback

    try:
        from tta.llm.client import Message, MessageRole
        from tta.llm.roles import ModelRole

        summary_ctx = f"\nJourney summary: {summary}" if summary else ""
        system_prompt = (
            "You are the narrator closing a text adventure story. "
            "Write a short, poignant epilogue (100-200 words). "
            "Begin with the chapter title '— Epilogue: What Remained —' on "
            "its own line. Describe the aftermath of the player's journey: "
            "what changed in the world, how NPCs remember the player's "
            "choices, and what legacy remains. End on a reflective, hopeful "
            "note. Do NOT break the fourth wall or mention game mechanics.\n\n"
            f"Character: {character_name}\n"
            f"World: {world_name}\n"
            f"Turns played: {turn_count}"
            f"{summary_ctx}"
        )
        messages = [
            Message(role=MessageRole.SYSTEM, content=system_prompt),
            Message(
                role=MessageRole.USER,
                content="Write the epilogue for this adventure.",
            ),
        ]
        resp = await llm_client.generate(ModelRole.GENERATION, messages)
        epilogue_text = resp.content.strip()
        if epilogue_text:
            epilogue_text += (
                "\n\nStart a new game whenever you're ready for another adventure."
            )
            return epilogue_text
    except Exception:
        pass

    return fallback
