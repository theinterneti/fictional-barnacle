"""Game session routes (plan §2.4–2.12)."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from redis.asyncio import Redis

from tta.api.deps import (
    get_current_player,
    get_pg,
    get_redis,
    require_anonymous_game_limit,
    require_consent,
)
from tta.api.errors import AppError
from tta.api.sse import SseEventBuffer
from tta.config import Settings, get_settings
from tta.errors import ErrorCategory
from tta.models.game import (
    CreateGameRequest,
    DeleteGameRequest,
    GameData,
    GameStatus,
    GameSummary,
    PaginationMeta,
    SaveResult,
    SubmitTurnRequest,
    TurnAccepted,
    UpdateGameRequest,
)
from tta.models.player import Player
from tta.models.turn import TurnState, TurnStatus
from tta.models.world import (
    WorldSeed,
)
from tta.observability.metrics import (
    SESSION_DURATION,
    SESSION_TURNS,
    SESSIONS_ACTIVE,
    SSE_BUFFER_SIZE,
    SSE_REPLAY_HITS,
    SSE_REPLAY_MISSES,
    TURN_STORAGE_OPS_DURATION,
)
from tta.persistence.redis_session import set_active_session
from tta.pipeline.orchestrator import (
    _regen_summary_bg,
    dispatch_pipeline,
)
from tta.pipeline.world_changes import (
    translate_world_updates,
)
from tta.transport import SSETransport

log = structlog.get_logger()

router = APIRouter(prefix="/games", tags=["games"])

# ── Command router (S01 AC-1.10) ──
# Valid state transitions (plan §6.1, S27 FR-27.01)
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "created": {"active", "abandoned"},
    "active": {"paused", "completed", "ended"},
    "paused": {"active", "expired", "ended"},
    "expired": {"active"},
}

# Map internal states to S27 public states (active | completed | abandoned)
_PUBLIC_STATE_MAP: dict[str, str] = {
    "created": "active",
    "active": "active",
    "paused": "active",
    "completed": "completed",
    "ended": "completed",
    "expired": "abandoned",
    "abandoned": "abandoned",
}


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


# --- Helper functions ---


async def _get_owned_game(pg: AsyncSession, game_id: UUID, player: Player) -> sa.Row:
    """Fetch a game row and verify ownership. Raises 404 if not found."""
    result = await pg.execute(
        sa.text(
            "SELECT id, player_id, status, world_seed, "
            "title, summary, turn_count, last_played_at, "
            "deleted_at, needs_recovery, summary_generated_at, "
            "total_cost_usd, cost_warning_sent, "
            "created_at, updated_at "
            "FROM game_sessions WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": game_id},
    )
    row = result.one_or_none()
    if row is None or row.player_id != player.id:
        raise AppError(ErrorCategory.NOT_FOUND, "GAME_NOT_FOUND", "Game not found.")
    return row


async def _count_active_games(pg: AsyncSession, player_id: UUID) -> int:
    """Count non-terminal games for the player."""
    result = await pg.execute(
        sa.text(
            "SELECT count(*) FROM game_sessions "
            "WHERE player_id = :pid "
            "AND status IN ('created', 'active', 'paused') "
            "AND deleted_at IS NULL"
        ),
        {"pid": player_id},
    )
    return result.scalar_one()


async def _get_turn_count(pg: AsyncSession, game_id: UUID) -> int:
    """Get the number of terminal turns (complete or moderated) for a game."""
    result = await pg.execute(
        sa.text(
            "SELECT count(*) FROM turns "
            "WHERE session_id = :sid AND status IN ('complete', 'moderated')"
        ),
        {"sid": game_id},
    )
    return result.scalar_one()


async def _get_max_turn_number(pg: AsyncSession, game_id: UUID) -> int:
    """Get the highest turn number for a game (0 if none).

    We count ALL turns regardless of status so that a failed turn still
    occupies its slot — preventing duplicate turn_number on retry
    (uq_turns_session_turn unique constraint).  Turn numbers may therefore
    skip if a turn fails, but the sequence is still monotonically increasing.
    """
    result = await pg.execute(
        sa.text(
            "SELECT coalesce(max(turn_number), 0) FROM turns WHERE session_id = :sid"
        ),
        {"sid": game_id},
    )
    return result.scalar_one()


# --- Routes ---


@router.post("", status_code=201, dependencies=[Depends(require_anonymous_game_limit)])
async def create_game(
    body: CreateGameRequest,
    request: Request,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """Create a new game session, optionally running world genesis."""
    settings: Settings = request.app.state.settings
    active_count = await _count_active_games(pg, player.id)
    if active_count >= settings.max_active_games:
        raise AppError(
            ErrorCategory.CONFLICT,
            "MAX_GAMES_REACHED",
            f"Maximum of {settings.max_active_games} active games reached.",
        )

    game_id = uuid4()
    now = datetime.now(UTC)
    world_seed_json = {
        "world_id": body.world_id,
        "preferences": body.preferences,
    }

    # Persist game row first — game exists even if genesis fails (S01)
    await pg.execute(
        sa.text(
            "INSERT INTO game_sessions "
            "(id, player_id, status, world_seed, "
            "created_at, updated_at, last_played_at) "
            "VALUES (:id, :pid, :status, "
            "cast(:seed AS jsonb), :now, :now, :now)"
        ),
        {
            "id": game_id,
            "pid": player.id,
            "status": GameStatus.created.value,
            "seed": json.dumps(world_seed_json),
            "now": now,
        },
    )
    await pg.commit()
    SESSIONS_ACTIVE.inc()

    # --- Genesis (best-effort) ---
    narrative_intro: str | None = None
    try:
        registry = request.app.state.template_registry

        # Select template: explicit key or best-match by preferences
        if body.world_id:
            template = registry.get(body.world_id)
        else:
            template = registry.select_by_preferences(body.preferences)

        # Build WorldSeed with selected template + preferences
        pref = body.preferences
        seed = WorldSeed(
            template=template,
            tone=pref.get("tone"),
            tech_level=pref.get("tech_level"),
            magic_presence=pref.get("magic_presence"),
            world_scale=pref.get("world_scale"),
            player_position=pref.get("player_position"),
            power_source=pref.get("power_source"),
            defining_detail=pref.get("defining_detail"),
            character_name=pref.get("character_name"),
            character_concept=pref.get("character_concept"),
        )

        from tta.genesis.genesis_lite import run_genesis_lite

        result = await run_genesis_lite(
            session_id=game_id,
            player_id=player.id,
            world_seed=seed,
            llm=request.app.state.llm_client,
            world_service=request.app.state.world_service,
        )
        narrative_intro = result.narrative_intro

        # Persist genesis result alongside original seed
        world_seed_json["genesis"] = {
            "world_id": result.world_id,
            "player_location_id": result.player_location_id,
            "template_key": result.template_key,
            "narrative_intro": result.narrative_intro,
            "genesis_elements": result.genesis_elements,
        }
        await pg.execute(
            sa.text(
                "UPDATE game_sessions "
                "SET world_seed = cast(:seed AS jsonb), "
                "updated_at = :now "
                "WHERE id = :gid"
            ),
            {
                "seed": json.dumps(world_seed_json),
                "now": datetime.now(UTC),
                "gid": game_id,
            },
        )
        await pg.commit()
        log.info("genesis_complete", game_id=str(game_id))
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning(
            "genesis_failed_graceful_degradation",
            game_id=str(game_id),
            exc_info=True,
        )

    return {
        "data": GameData(
            game_id=str(game_id),
            player_id=str(player.id),
            status=GameStatus.active.value,
            turn_count=0,
            narrative_intro=narrative_intro,
            created_at=now,
            updated_at=now,
            last_played_at=now,
        ).model_dump(mode="json")
    }


@router.get("")
async def list_games(
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
    status: str | None = Query(None),
    cursor: datetime | None = Query(None),
    limit: int | None = Query(None, ge=1, le=50),
) -> dict:
    """List the authenticated player's games (S27 FR-27.08–FR-27.11)."""
    settings: Settings = get_settings()
    effective_limit = min(
        limit or settings.game_listing_default_size,
        settings.game_listing_max_size,
    )

    params: dict = {"pid": player.id, "lim": effective_limit + 1}
    where_clauses = [
        "gs.player_id = :pid",
        "gs.deleted_at IS NULL",
    ]

    if status is not None:
        where_clauses.append("gs.status = :status")
        params["status"] = status
    else:
        # Exclude abandoned games by default (S27 FR-27.10)
        where_clauses.append("gs.status != 'abandoned'")

    if cursor is not None:
        where_clauses.append("gs.last_played_at < :cursor")
        params["cursor"] = cursor

    where = " AND ".join(where_clauses)
    result = await pg.execute(
        sa.text(
            f"SELECT gs.id, gs.player_id, gs.status, gs.world_seed, "  # noqa: S608
            f"gs.title, gs.summary, "
            f"COALESCE(tc.cnt, 0) AS turn_count, "
            f"gs.created_at, gs.updated_at, gs.last_played_at "
            f"FROM game_sessions gs "
            f"LEFT JOIN ("
            f"  SELECT session_id, count(*) AS cnt "
            f"  FROM turns WHERE status = 'complete' "
            f"  GROUP BY session_id"
            f") tc ON tc.session_id = gs.id "
            f"WHERE {where} "
            f"ORDER BY gs.last_played_at DESC NULLS LAST "
            f"LIMIT :lim"
        ),
        params,
    )
    rows = result.all()
    has_more = len(rows) > effective_limit
    items = rows[:effective_limit]

    games = [
        GameSummary(
            game_id=str(r.id),
            status=_PUBLIC_STATE_MAP.get(r.status or "", r.status or ""),
            turn_count=r.turn_count or 0,
            title=r.title,
            summary=r.summary,
            created_at=r.created_at,
            updated_at=r.updated_at,
            last_played_at=r.last_played_at,
        ).model_dump(mode="json")
        for r in items
    ]

    next_cursor = (
        items[-1].last_played_at.isoformat()
        if has_more and items and items[-1].last_played_at
        else None
    )

    return {
        "data": games,
        "meta": PaginationMeta(
            next_cursor=next_cursor,
            has_more=has_more,
        ).model_dump(mode="json"),
    }


@router.get("/{game_id}")
async def get_game_state(
    game_id: UUID,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """Get full game state for a session."""
    row = await _get_owned_game(pg, game_id, player)
    turn_count = await _get_turn_count(pg, game_id)

    # Recent turns
    turns_result = await pg.execute(
        sa.text(
            "SELECT id, turn_number, player_input, narrative_output, "
            "created_at FROM turns "
            "WHERE session_id = :sid AND status = 'complete' "
            "ORDER BY turn_number DESC LIMIT 10"
        ),
        {"sid": game_id},
    )
    recent = [
        {
            "turn_id": str(t.id),
            "turn_number": t.turn_number,
            "player_input": t.player_input,
            "narrative_output": t.narrative_output,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in reversed(turns_result.all())
    ]

    # Check for in-flight turn
    processing_result = await pg.execute(
        sa.text(
            "SELECT id FROM turns "
            "WHERE session_id = :sid AND status = 'processing' "
            "LIMIT 1"
        ),
        {"sid": game_id},
    )
    processing_row = processing_result.one_or_none()

    return {
        "data": {
            "game_id": str(row.id),
            "player_id": str(row.player_id),
            "status": row.status,
            "turn_count": turn_count,
            "title": row.title,
            "summary": row.summary,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "last_played_at": (
                row.last_played_at.isoformat() if row.last_played_at else None
            ),
            "recent_turns": recent,
            "processing_turn": (str(processing_row.id) if processing_row else None),
        }
    }


@router.get("/{game_id}/turns")
async def list_turns(
    game_id: UUID,
    request: Request,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict:
    """Paginated turn history for a game (FR-10.13)."""
    await _get_owned_game(pg, game_id, player)

    # Decode cursor (base64-encoded turn_number)
    cursor_turn: int | None = None
    if cursor is not None:
        try:
            decoded = base64.urlsafe_b64decode(cursor).decode("utf-8")
            cursor_turn = int(decoded)
            if cursor_turn < 1:
                raise ValueError("non-positive cursor")
        except Exception:
            raise AppError(
                ErrorCategory.INPUT_INVALID,
                "INVALID_CURSOR",
                "Malformed pagination cursor.",
            ) from None

    # Build query — status='complete' only (matches get_game_state invariant)
    params: dict = {"sid": game_id, "lim": limit + 1}
    where = "session_id = :sid AND status = 'complete'"
    if cursor_turn is not None:
        where += " AND turn_number < :cursor_tn"
        params["cursor_tn"] = cursor_turn

    result = await pg.execute(
        sa.text(
            f"SELECT id, turn_number, player_input, narrative_output, "
            f"created_at FROM turns "
            f"WHERE {where} "
            f"ORDER BY turn_number DESC LIMIT :lim"
        ),
        params,
    )
    rows = result.all()

    has_more = len(rows) > limit
    items = rows[:limit]

    turns = [
        {
            "turn_id": str(t.id),
            "turn_number": t.turn_number,
            "player_input": t.player_input,
            "narrative_output": t.narrative_output,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in items
    ]

    next_cursor = (
        base64.urlsafe_b64encode(str(items[-1].turn_number).encode()).decode()
        if has_more and items
        else None
    )

    return {
        "data": turns,
        "meta": PaginationMeta(
            next_cursor=next_cursor,
            has_more=has_more,
        ).model_dump(mode="json"),
    }


@router.post(
    "/{game_id}/turns",
    status_code=202,
    response_model=None,
    dependencies=[Depends(require_consent)],
)
async def submit_turn(
    game_id: UUID,
    body: SubmitTurnRequest,
    request: Request,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict | JSONResponse:
    """Submit a player turn for processing."""
    row = await _get_owned_game(pg, game_id, player)

    # FR-27.15: attempt recovery before accepting new turns
    if row.needs_recovery:
        try:
            actual_tc = await _get_turn_count(pg, game_id)
            now_rec = datetime.now(UTC)
            await pg.execute(
                sa.text(
                    "UPDATE game_sessions "
                    "SET turn_count = :tc, needs_recovery = FALSE, "
                    "last_played_at = :now, updated_at = :now "
                    "WHERE id = :gid"
                ),
                {"gid": game_id, "tc": actual_tc, "now": now_rec},
            )
            await pg.commit()
            log.info("recovery_on_submit", game_id=str(game_id))
        except Exception:
            log.warning(
                "recovery_on_submit_failed",
                game_id=str(game_id),
                exc_info=True,
            )

    # Must be active or created
    if row.status not in ("active", "created"):
        raise AppError(
            ErrorCategory.CONFLICT,
            "GAME_NOT_ACTIVE",
            f"Cannot submit turns for a game in '{row.status}' status.",
        )

    # --- Pre-pipeline routing: commands (S01 AC-1.10), validation (S23 AC-23.11) ---
    normalized = body.input.strip()

    # Empty / whitespace-only input → 400 input_invalid (AC-23.11)
    if not normalized:
        raise AppError(
            ErrorCategory.INPUT_INVALID,
            "EMPTY_TURN_INPUT",
            "Turn text cannot be empty.",
        )

    # Slash commands → instant response (no DB row, no pipeline)
    if normalized.startswith("/") and len(normalized) > 1:
        known_cmd = _parse_slash_command(normalized)
        if known_cmd:
            reg = getattr(request.app.state, "template_registry", None)
            rel_svc = getattr(
                getattr(request.app.state, "pipeline_deps", None),
                "relationship_service",
                None,
            )
            llm = getattr(request.app.state, "llm_client", None)
            payload = await _execute_command(
                known_cmd,
                game_id,
                row,
                pg,
                template_registry=reg,
                relationship_service=rel_svc,
                llm_client=llm,
            )
        else:
            payload = {
                "type": "command",
                "command": "unknown",
                "message": (f"Unknown command. {_HELP_TEXT}"),
            }
        return JSONResponse(content={"data": payload}, status_code=200)

    # Concurrent turn check — advisory lock serialises per-game
    await pg.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtext(:gid))"),
        {"gid": str(game_id)},
    )
    in_flight = await pg.execute(
        sa.text(
            "SELECT id FROM turns WHERE session_id = :sid AND status = 'processing'"
        ),
        {"sid": game_id},
    )
    if in_flight.one_or_none() is not None:
        raise AppError(
            ErrorCategory.CONFLICT,
            "TURN_IN_PROGRESS",
            "A turn is already being processed for this game.",
        )

    # Idempotency check
    if body.idempotency_key is not None:
        dup = await pg.execute(
            sa.text(
                "SELECT id, turn_number FROM turns "
                "WHERE session_id = :sid AND idempotency_key = :key"
            ),
            {"sid": game_id, "key": body.idempotency_key},
        )
        dup_row = dup.one_or_none()
        if dup_row is not None:
            return {
                "data": TurnAccepted(
                    turn_id=str(dup_row.id),
                    turn_number=dup_row.turn_number,
                    stream_url=f"/api/v1/games/{game_id}/stream",
                ).model_dump(mode="json")
            }

    # Create turn — track storage latency (AC-12.07)
    _storage_t0 = time.monotonic()
    turn_id = uuid4()
    turn_number = await _get_max_turn_number(pg, game_id) + 1
    now = datetime.now(UTC)

    await pg.execute(
        sa.text(
            "INSERT INTO turns "
            "(id, session_id, turn_number, player_input, "
            "idempotency_key, status, created_at) "
            "VALUES (:id, :sid, :tn, :input, :ikey, 'processing', :now)"
        ),
        {
            "id": turn_id,
            "sid": game_id,
            "tn": turn_number,
            "input": body.input,
            "ikey": body.idempotency_key,
            "now": now,
        },
    )

    # Transition created → active on first turn; always update last_played_at
    if row.status == "created":
        await pg.execute(
            sa.text(
                "UPDATE game_sessions SET status = 'active', "
                "last_played_at = :now, updated_at = :now WHERE id = :id"
            ),
            {"id": game_id, "now": now},
        )
    else:
        await pg.execute(
            sa.text(
                "UPDATE game_sessions SET last_played_at = :now, "
                "updated_at = :now WHERE id = :id"
            ),
            {"id": game_id, "now": now},
        )

    await pg.commit()
    TURN_STORAGE_OPS_DURATION.labels(operation="turn_insert").observe(
        time.monotonic() - _storage_t0
    )

    # Dispatch pipeline as background task
    game_state = row.world_seed if row.world_seed else {}
    if isinstance(game_state, str):
        game_state = json.loads(game_state)
    asyncio.create_task(
        dispatch_pipeline(
            app_state=request.app.state,
            game_id=game_id,
            turn_id=turn_id,
            turn_number=turn_number,
            player_input=body.input,
            game_state=game_state,
            session_cost_usd=float(getattr(row, "total_cost_usd", 0) or 0),
        )
    )

    return {
        "data": TurnAccepted(
            turn_id=str(turn_id),
            turn_number=turn_number,
            stream_url=f"/api/v1/games/{game_id}/stream",
        ).model_dump(mode="json")
    }


@router.get("/{game_id}/stream")
async def stream_turn(
    game_id: UUID,
    request: Request,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
    redis: Redis = Depends(get_redis),
) -> StreamingResponse:
    """SSE endpoint — streams turn processing events to the client.

    Implements FR-10.40–10.44: clients may reconnect with a
    ``Last-Event-ID`` header to replay missed events from the Redis
    buffer (≥100 events, 5-min rolling window).
    """
    await _get_owned_game(pg, game_id, player)  # ownership check

    # Look up the latest turn for its ID and number
    proc_result = await pg.execute(
        sa.text(
            "SELECT id, turn_number FROM turns "
            "WHERE session_id = :sid "
            "ORDER BY turn_number DESC LIMIT 1"
        ),
        {"sid": game_id},
    )
    proc_row = proc_result.one_or_none()
    correlation_id = getattr(request.state, "request_id", "unknown")
    game_id_str = str(game_id)

    # Parse Last-Event-ID for reconnect detection (FR-10.40)
    raw_last_id = request.headers.get("Last-Event-ID", "").strip()
    last_event_id: int | None = None
    if raw_last_id:
        try:
            last_event_id = int(raw_last_id)
        except ValueError:
            last_event_id = None

    # NOTE: event_stream is a complex generator because SSE streaming
    # requires a single async function yielding formatted events.
    # TODO: decompose into _wait_for_result() and _emit_turn_events()
    # helpers once the streaming contract stabilises.
    async def event_stream():  # noqa: C901
        # FR-10.43: hint the client to reconnect after 3 s on disconnect.
        # This raw string is NOT stored in the replay buffer.
        yield "retry: 3000\n\n"

        # --- helper: get next global ID, format, buffer, and return raw ---
        # Defined early so it's available to NO_TURN_FOUND and all error paths.
        _pending: list[str] = []

        async def _emit(event_obj: object) -> str:  # type: ignore[override]
            eid = await SseEventBuffer.get_next_id(redis, game_id_str)
            raw = event_obj.format_sse(eid)  # type: ignore[attr-defined]
            await SseEventBuffer.append(redis, game_id_str, eid, raw)
            SSE_BUFFER_SIZE.labels(game_id=game_id_str).set(
                await redis.zcard(f"tta:sse_buffer:{game_id_str}")
            )
            _pending.append(raw)
            return raw

        transport = SSETransport(redis=redis, game_id=game_id_str, emit=_emit)

        if proc_row is None:
            await transport.send_error(
                code="NO_TURN_FOUND",
                message="No turn found for this game.",
                turn_id=None,
                correlation_id=correlation_id,
                retry_after_seconds=2,
            )
            for r in _pending:
                yield r
            _pending.clear()
            return

        current_turn_id = str(proc_row.id)

        # --- reconnect path (FR-10.42 / FR-10.44) ---
        if last_event_id is not None:
            replayed = await SseEventBuffer.replay_after(
                redis, game_id_str, last_event_id
            )

            if replayed is None:
                # Buffer miss (EC-10.13) — signal client to fetch state via REST
                SSE_REPLAY_MISSES.inc()
                await transport.send_error(
                    code="replay_unavailable",
                    message=(
                        "The event buffer for this session has expired. "
                        "Fetch current game state via GET /games/{id}."
                    ),
                    turn_id=None,
                    correlation_id=correlation_id,
                    retry_after_seconds=0,
                )
                for r in _pending:
                    yield r
                _pending.clear()
                # FR-10.44: continue to keepalive loop so the client receives
                # live events for the in-progress turn (no early return).
            else:
                # HIT — replay buffered events to the client
                SSE_REPLAY_HITS.inc()
                for raw_event in replayed:
                    yield raw_event

                # Check whether the turn pipeline has already completed
                store = request.app.state.turn_result_store
                result_check = await store.wait_for_result(current_turn_id, timeout=0.1)
                if result_check is not None:
                    # Only short-circuit if narrative_end was in the replayed
                    # events; otherwise fall through so the client gets finals.
                    if any("event: narrative_end" in e for e in replayed):
                        return
                # Turn still in progress — fall through to keepalive loop

        # FR-23.22 / S10 §6.5: heartbeat loop while waiting for pipeline result
        store = request.app.state.turn_result_store
        settings: Settings = request.app.state.settings
        keepalive_interval = settings.sse_heartbeat_interval
        total_timeout = settings.pipeline_timeout_seconds
        deadline = time.monotonic() + total_timeout
        result: TurnState | None = None

        while time.monotonic() < deadline:
            remaining = min(keepalive_interval, deadline - time.monotonic())
            if remaining <= 0:
                break
            result = await store.wait_for_result(current_turn_id, timeout=remaining)
            if result is not None:
                break
            if time.monotonic() < deadline:
                # S10 §6.5 heartbeat: bounded by remaining pipeline timeout.
                await transport.send_heartbeat()
                for r in _pending:
                    yield r
                _pending.clear()

        if result is None:
            await transport.send_error(
                code="PIPELINE_TIMEOUT",
                message="Turn processing timed out.",
                turn_id=current_turn_id,
                correlation_id=correlation_id,
                retry_after_seconds=5,
            )
            for r in _pending:
                yield r
            _pending.clear()
            return

        if result.status == TurnStatus.failed:
            # FR-10.36: emit the pipeline failure event, then end this response
            # stream by returning from the async generator.
            await transport.send_error(
                code="PIPELINE_FAILED",
                message="Turn processing failed.",
                turn_id=current_turn_id,
                correlation_id=correlation_id,
                retry_after_seconds=2,
            )
            for r in _pending:
                yield r
            _pending.clear()
            return

        # FR-24.06/FR-24.08: emit moderation event before narrative
        # when content was redirected by the moderation pipeline.
        if result.status == TurnStatus.moderated:
            log.info(
                "sse_moderation_event",
                turn_id=current_turn_id,
                safety_flags=result.safety_flags,
            )
            await transport.send_moderation(
                reason=(
                    "The story has been gently redirected "
                    "to maintain a supportive experience."
                ),
            )
            for r in _pending:
                yield r
            _pending.clear()

        # S10 §6.2 / FR-10.34: emit narrative as sentence-aligned chunks
        if result.narrative_output:
            total_chunks = await transport.send_narrative(
                result.narrative_output, current_turn_id
            )
        else:
            total_chunks = 0
        for r in _pending:
            yield r
        _pending.clear()

        # S10 §6.4 / FR-10.35: narrative_end with total_chunks count
        await transport.send_end(current_turn_id, total_chunks)
        for r in _pending:
            yield r
        _pending.clear()

        # S10 §6.2: state_update for world changes follows narrative_end
        if result.world_state_updates:
            world_changes = translate_world_updates(result.world_state_updates)
            if world_changes:
                await transport.send_state_update(world_changes)
                for r in _pending:
                    yield r
                _pending.clear()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{game_id}/save")
async def save_game(
    game_id: UUID,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """Explicit save — resets inactivity timers."""
    row = await _get_owned_game(pg, game_id, player)
    now = datetime.now(UTC)

    await pg.execute(
        sa.text("UPDATE game_sessions SET updated_at = :now WHERE id = :id"),
        {"id": game_id, "now": now},
    )
    await pg.commit()

    turn_count = await _get_turn_count(pg, game_id)

    return {
        "data": SaveResult(
            game_id=str(row.id),
            saved_at=now,
            turn_count=turn_count,
        ).model_dump(mode="json")
    }


@router.post("/{game_id}/restore")
async def restore_game_snapshot(
    game_id: UUID,
    request: Request,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Restore the game session to its most recent PostgreSQL snapshot (AC-12.04).

    Re-hydrates the Redis session cache from the latest stored snapshot.
    Returns the restored turn number and state.
    """
    await _get_owned_game(pg, game_id, player)

    svc = request.app.state.snapshot_service
    result = await svc.get_latest_snapshot(game_id)
    if result is None:
        raise AppError(
            ErrorCategory.NOT_FOUND,
            "SNAPSHOT_NOT_FOUND",
            "No snapshot found for this game session.",
        )

    turn_number, game_state = result

    # Re-hydrate Redis session cache
    await set_active_session(redis, game_id, game_state)

    log.info(
        "snapshot_restored",
        game_id=str(game_id),
        turn_number=turn_number,
    )
    return {
        "data": {
            "restored_to_turn": turn_number,
            "state": game_state.model_dump(mode="json"),
        }
    }


@router.post("/{game_id}/resume")
async def resume_game(
    game_id: UUID,
    request: Request,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """Resume a game — loads recent turns, context summary, handles recovery.

    FR-27.12–FR-27.15, FR-27.20–FR-27.21.
    """
    row = await _get_owned_game(pg, game_id, player)
    settings: Settings = request.app.state.settings

    if row.status not in ("active", "paused", "expired"):
        raise AppError(
            ErrorCategory.CONFLICT,
            "GAME_NOT_RESUMABLE",
            f"Cannot resume a game in '{row.status}' status.",
        )

    recovery_warning: str | None = None
    previous_status = row.status  # AC-11.07: capture for welcome back narrative

    # FR-27.15: attempt recovery if previous save failed
    if row.needs_recovery:
        try:
            actual_count = await _get_turn_count(pg, game_id)
            now_r = datetime.now(UTC)
            await pg.execute(
                sa.text(
                    "UPDATE game_sessions "
                    "SET turn_count = :tc, needs_recovery = FALSE, "
                    "last_played_at = :now, updated_at = :now "
                    "WHERE id = :gid"
                ),
                {"gid": game_id, "tc": actual_count, "now": now_r},
            )
            await pg.commit()
            log.info("recovery_succeeded", game_id=str(game_id))
        except Exception:
            log.warning("recovery_failed", game_id=str(game_id), exc_info=True)
            recovery_warning = (
                "Some progress may not have been saved. "
                "Continuing from last successful save."
            )

    # Transition to active if paused/expired
    now = datetime.now(UTC)
    status_updated = False
    if row.status != "active":
        await pg.execute(
            sa.text(
                "UPDATE game_sessions SET status = 'active', "
                "last_played_at = :now, updated_at = :now WHERE id = :id"
            ),
            {"id": game_id, "now": now},
        )
        await pg.commit()
        status_updated = True

    # Load recent turns (FR-27.12)
    limit = settings.resume_turn_count
    turns_result = await pg.execute(
        sa.text(
            "SELECT id, turn_number, player_input, narrative_output, "
            "created_at FROM turns "
            "WHERE session_id = :sid AND status IN ('complete', 'moderated') "
            "ORDER BY turn_number DESC LIMIT :lim"
        ),
        {"sid": game_id, "lim": limit},
    )
    recent_turns = [
        {
            "turn_id": str(t.id),
            "turn_number": t.turn_number,
            "player_input": t.player_input,
            "narrative_output": t.narrative_output,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in reversed(turns_result.all())
    ]

    turn_count = await _get_turn_count(pg, game_id)

    # FR-27.21: check context_summary staleness (>24h since last turn)
    context_summary = row.summary
    summary_stale = False
    if row.last_played_at is not None and row.summary is not None:
        age_hours = (now - row.last_played_at).total_seconds() / 3600
        if age_hours > settings.summary_staleness_hours:
            summary_stale = True
    elif recent_turns and row.summary is None:
        # Never generated — stale by definition
        summary_stale = True

    # Fire-and-forget summary regen if stale (FR-27.21)
    if summary_stale and recent_turns:
        asyncio.create_task(_regen_summary_bg(request.app.state, game_id))

    # FR-5.4: Build contextual recap for the player
    recap: str | None = None
    if turn_count > 0 and context_summary:
        recap = f"When we last left off: {context_summary}"
    elif turn_count == 0:
        # Zero-turn game — derive recap from genesis narrative intro
        ws = row.world_seed
        if isinstance(ws, dict):
            genesis = ws.get("genesis", {})
            intro = genesis.get("narrative_intro")
            if intro:
                recap = str(intro)

    # AC-11.07: Always emit welcome-back narrative for expired game resumes
    if previous_status == "expired":
        if recap:
            recap = f"Welcome back! It's been a while. {recap}"
        else:
            recap = "Welcome back! It's been a while."

    # Use actual timestamps — only reflect `now` when we updated.
    resp_updated = now.isoformat() if status_updated else row.updated_at.isoformat()
    resp_last_played = (
        now.isoformat()
        if status_updated
        else (row.last_played_at.isoformat() if row.last_played_at else None)
    )

    return {
        "data": {
            "game_id": str(row.id),
            "player_id": str(row.player_id),
            "status": "active",
            "turn_count": turn_count,
            "title": row.title,
            "context_summary": context_summary,
            "recap": recap,
            "recent_turns": recent_turns,
            "created_at": row.created_at.isoformat(),
            "updated_at": resp_updated,
            "last_played_at": resp_last_played,
            "summary_stale": summary_stale,
            "recovery_warning": recovery_warning,
        }
    }


@router.patch("/{game_id}")
async def update_game(
    game_id: UUID,
    body: UpdateGameRequest,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """Update game status (v1: pause only)."""
    row = await _get_owned_game(pg, game_id, player)

    allowed = _VALID_TRANSITIONS.get(row.status, set())
    if body.status not in allowed:
        raise AppError(
            ErrorCategory.CONFLICT,
            "INVALID_STATE_TRANSITION",
            f"Cannot transition from '{row.status}' to '{body.status}'.",
        )

    now = datetime.now(UTC)
    if body.status == "paused":
        await pg.execute(
            sa.text(
                "UPDATE game_sessions SET status = :status, "
                "paused_at = :now, updated_at = :now WHERE id = :id"
            ),
            {"id": game_id, "status": body.status, "now": now},
        )
    else:
        await pg.execute(
            sa.text(
                "UPDATE game_sessions SET status = :status, "
                "updated_at = :now WHERE id = :id"
            ),
            {"id": game_id, "status": body.status, "now": now},
        )
    await pg.commit()

    turn_count = await _get_turn_count(pg, game_id)

    return {
        "data": GameData(
            game_id=str(row.id),
            player_id=str(row.player_id),
            status=body.status,
            turn_count=turn_count,
            title=row.title,
            summary=row.summary,
            created_at=row.created_at,
            updated_at=now,
            last_played_at=row.last_played_at,
        ).model_dump(mode="json")
    }


@router.delete("/{game_id}", status_code=204, response_model=None)
async def end_game(
    game_id: UUID,
    request: Request,
    body: DeleteGameRequest | None = None,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> None:
    """Soft-delete a game and clean up its Neo4j world graph (S27 FR-27.16–FR-27.19)."""
    if body is None or not body.confirm:
        raise AppError(
            ErrorCategory.INPUT_INVALID,
            "CONFIRM_REQUIRED",
            "Set confirm: true to delete this game.",
        )

    row = await _get_owned_game(pg, game_id, player)

    if row.status in ("ended", "abandoned"):
        raise AppError(
            ErrorCategory.CONFLICT,
            "INVALID_STATE_TRANSITION",
            f"Game is already in '{row.status}' status.",
        )

    # Clean up Neo4j world graph before soft-deleting the PG row.
    # The game_id is the session_id used in all Neo4j nodes.
    neo4j_driver = getattr(request.app.state, "neo4j_driver", None)
    if neo4j_driver is not None:
        try:
            async with neo4j_driver.session() as session:
                await session.run(
                    "MATCH (n {session_id: $sid}) DETACH DELETE n",
                    sid=str(game_id),
                )
        except Exception:
            log.warning(
                "neo4j_cleanup_failed_during_delete",
                game_id=str(game_id),
                exc_info=True,
            )

    now = datetime.now(UTC)
    await pg.execute(
        sa.text(
            "UPDATE game_sessions SET status = 'abandoned', "
            "deleted_at = :now, updated_at = :now WHERE id = :id"
        ),
        {"id": game_id, "now": now},
    )
    await pg.commit()

    turn_count = await _get_turn_count(pg, game_id)

    # Session lifecycle metrics (S15 FR-15.8)
    SESSIONS_ACTIVE.dec()
    SESSION_TURNS.observe(turn_count)
    duration_s = (now - row.created_at).total_seconds()
    SESSION_DURATION.observe(duration_s)

    return None
