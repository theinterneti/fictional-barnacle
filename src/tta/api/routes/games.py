"""Game session routes (plan §2.4–2.12)."""

from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.deps import get_current_player, get_pg, require_active_player
from tta.api.errors import AppError
from tta.api.sse import SSECounter
from tta.config import Settings, get_settings
from tta.errors import ErrorCategory
from tta.logging import bind_context
from tta.models.events import (
    ErrorEvent,
    KeepaliveEvent,
    ModerationEvent,
    NarrativeBlockEvent,
    TurnCompleteEvent,
    TurnStartEvent,
)
from tta.models.game import GameStatus
from tta.models.player import Player
from tta.models.turn import TurnState, TurnStatus
from tta.models.world import WorldChange, WorldChangeType, WorldSeed
from tta.observability.metrics import (
    SESSION_DURATION,
    SESSION_TURNS,
    SESSIONS_ACTIVE,
)
from tta.pipeline.orchestrator import run_pipeline

log = structlog.get_logger()

router = APIRouter(prefix="/games", tags=["games"])

# Mapping from LLM-extracted attribute keywords to WorldChangeType
_ATTRIBUTE_TYPE_MAP: dict[str, WorldChangeType] = {
    "location": WorldChangeType.PLAYER_MOVED,
    "position": WorldChangeType.PLAYER_MOVED,
    "moved": WorldChangeType.PLAYER_MOVED,
    "disposition": WorldChangeType.NPC_DISPOSITION_CHANGED,
    "mood": WorldChangeType.NPC_DISPOSITION_CHANGED,
    "attitude": WorldChangeType.NPC_DISPOSITION_CHANGED,
    "state": WorldChangeType.LOCATION_STATE_CHANGED,
    "status": WorldChangeType.LOCATION_STATE_CHANGED,
    "locked": WorldChangeType.CONNECTION_LOCKED,
    "unlocked": WorldChangeType.CONNECTION_UNLOCKED,
    "taken": WorldChangeType.ITEM_TAKEN,
    "picked": WorldChangeType.ITEM_TAKEN,
    "dropped": WorldChangeType.ITEM_DROPPED,
    "quest_status": WorldChangeType.QUEST_STATUS_CHANGED,
    "quest": WorldChangeType.QUEST_STATUS_CHANGED,
    "visibility": WorldChangeType.ITEM_VISIBILITY_CHANGED,
    "relationship": WorldChangeType.RELATIONSHIP_CHANGED,
}


def _build_typed_payload(change_type: WorldChangeType, item: dict) -> dict:
    """Build a payload dict with the keys required by validate_change()."""
    base: dict = {
        "attribute": str(item.get("attribute") or ""),
        "old_value": item.get("old_value"),
        "new_value": item.get("new_value"),
        "reason": item.get("reason", ""),
    }
    # Merge any extra keys the LLM may have provided (e.g. from_id, to_id)
    for k, v in item.items():
        if k not in ("entity", "attribute", "old_value", "new_value", "reason"):
            base[k] = v

    nv = item.get("new_value")
    ct = change_type
    if ct == WorldChangeType.PLAYER_MOVED:
        base.setdefault("from_id", item.get("old_value", ""))
        base.setdefault("to_id", item.get("new_value", ""))
    elif ct == WorldChangeType.NPC_DISPOSITION_CHANGED:
        base.setdefault("disposition", nv if nv is not None else "")
    elif ct == WorldChangeType.NPC_STATE_CHANGED:
        base.setdefault("state", nv if nv is not None else "")
    elif ct == WorldChangeType.NPC_MOVED:
        base.setdefault("to_location_id", nv if nv is not None else "")
    elif ct == WorldChangeType.CONNECTION_LOCKED:
        base.setdefault("from_id", item.get("old_value", ""))
        base.setdefault("to_id", str(item.get("entity", "")))
    elif ct == WorldChangeType.CONNECTION_UNLOCKED:
        base.setdefault("from_id", item.get("old_value", ""))
        base.setdefault("to_id", str(item.get("entity", "")))
    elif ct == WorldChangeType.QUEST_STATUS_CHANGED:
        base.setdefault("new_status", nv if nv is not None else "")
    elif ct == WorldChangeType.ITEM_VISIBILITY_CHANGED:
        hidden = nv if isinstance(nv, bool) else str(nv).lower() == "true"
        base.setdefault("hidden", hidden)
    return base


def _translate_world_updates(raw: list[dict]) -> list[WorldChange]:
    """Convert LLM-extracted dicts to WorldChange objects (best-effort)."""
    changes: list[WorldChange] = []
    for item in raw:
        entity = item.get("entity", "")
        attribute = str(item.get("attribute") or "")
        if not entity:
            continue
        # Infer change type from attribute keywords
        change_type = WorldChangeType.LOCATION_STATE_CHANGED
        attr_lower = attribute.lower()
        for keyword, ct in sorted(
            _ATTRIBUTE_TYPE_MAP.items(), key=lambda x: -len(x[0])
        ):
            if keyword in attr_lower:
                change_type = ct
                break
        changes.append(
            WorldChange(
                type=change_type,
                entity_id=str(entity),
                payload=_build_typed_payload(change_type, item),
            )
        )
    return changes


async def _dispatch_pipeline(
    app_state: object,
    game_id: UUID,
    turn_id: UUID,
    turn_number: int,
    player_input: str,
    game_state: dict,
) -> None:
    """Run the pipeline as a background task and persist results."""
    deps = app_state.pipeline_deps  # type: ignore[attr-defined]
    turn_repo = deps.turn_repo

    # Bind game/turn context for correlated logging (S15 §7).
    bind_context(session_id=game_id, turn_id=turn_id)

    state = TurnState(
        session_id=game_id,
        turn_id=turn_id,
        turn_number=turn_number,
        player_input=player_input,
        game_state=game_state,
    )

    start = time.monotonic()
    try:
        result = await run_pipeline(state, deps)
    except Exception:
        log.error("pipeline_dispatch_failed", game_id=str(game_id), exc_info=True)
        result = state.model_copy(update={"status": TurnStatus.failed})

    elapsed_ms = (time.monotonic() - start) * 1000
    result = result.model_copy(update={"latency_ms": elapsed_ms})

    # Persist turn result via repository
    turn_persisted = False
    try:
        if (
            result.status
            in (
                TurnStatus.complete,
                TurnStatus.moderated,
            )
            and result.narrative_output
        ):
            token_dict = result.token_count.model_dump() if result.token_count else {}
            await turn_repo.complete_turn(
                turn_id=turn_id,
                narrative_output=result.narrative_output,
                model_used=result.model_used or "unknown",
                latency_ms=elapsed_ms,
                token_count=token_dict,
            )
            # FR-24.06 item 5: mark moderated turns distinctly
            if result.status == TurnStatus.moderated:
                await turn_repo.update_status(turn_id, "moderated")
            turn_persisted = True
        else:
            # FR-23.18: preserve partial narrative on failure
            await turn_repo.fail_turn(turn_id, narrative_output=result.narrative_output)
    except Exception:
        log.error("turn_persist_failed", turn_id=str(turn_id), exc_info=True)
        # Last-resort: ensure turn exits processing state to prevent
        # permanent concurrent-turn lock (critique finding #5).
        try:
            await turn_repo.update_status(turn_id, "failed")
        except Exception:
            log.error(
                "turn_failsafe_status_update_failed",
                turn_id=str(turn_id),
                exc_info=True,
            )

    # --- FR-27.05/06: Post-turn auto-save (metadata) ---
    # Gate on turn_persisted to avoid incrementing counters for failed saves.
    if turn_persisted:
        # TODO: inject session factory via PipelineDeps instead of
        # reaching into repo internals (_sf).
        sf = app_state.pipeline_deps.turn_repo._sf  # type: ignore[attr-defined]
        try:
            async with sf() as meta_sess:
                now = datetime.now(UTC)
                await meta_sess.execute(
                    sa.text(
                        "UPDATE game_sessions "
                        "SET turn_count = turn_count + 1, "
                        "last_played_at = :now, updated_at = :now "
                        "WHERE id = :gid"
                    ),
                    {"gid": game_id, "now": now},
                )
                await meta_sess.commit()
        except Exception:
            log.warning(
                "auto_save_metadata_failed",
                game_id=str(game_id),
                exc_info=True,
            )
            # FR-27.07: mark needs_recovery so resume can fix it
            try:
                async with sf() as recovery_sess:
                    await recovery_sess.execute(
                        sa.text(
                            "UPDATE game_sessions "
                            "SET needs_recovery = TRUE "
                            "WHERE id = :gid"
                        ),
                        {"gid": game_id},
                    )
                    await recovery_sess.commit()
            except Exception:
                log.error(
                    "needs_recovery_flag_failed",
                    game_id=str(game_id),
                    exc_info=True,
                )

        # FR-27.22: title from opening narrative (turn 1 IS genesis)
        if turn_number == 1 and result.narrative_output:
            asyncio.create_task(
                _generate_title_bg(app_state, game_id, result.narrative_output)
            )

        # FR-27.20: fire-and-forget summary regen every Nth turn
        settings = app_state.settings  # type: ignore[attr-defined]
        if (
            settings.summary_interval > 0
            and turn_number % settings.summary_interval == 0
        ):
            asyncio.create_task(_regen_summary_bg(app_state, game_id))

    # --- Apply world state changes (best-effort) ---
    if turn_persisted and result.world_state_updates:
        try:
            from tta.world.changes import apply_changes

            world_svc = deps.world
            changes = _translate_world_updates(result.world_state_updates)
            if changes:
                await apply_changes(changes, world_svc, game_id)
                log.info(
                    "world_changes_applied",
                    game_id=str(game_id),
                    count=len(changes),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning(
                "world_changes_failed_graceful_degradation",
                game_id=str(game_id),
                exc_info=True,
            )

    # Publish result for SSE endpoint
    try:
        store = app_state.turn_result_store  # type: ignore[attr-defined]
        await store.publish(str(turn_id), result)
    except Exception:
        log.error(
            "turn_result_publish_failed",
            turn_id=str(turn_id),
            exc_info=True,
        )
    log.info(
        "pipeline_dispatch_complete",
        game_id=str(game_id),
        turn_id=str(turn_id),
        status=result.status,
        latency_ms=round(elapsed_ms, 1),
    )


async def _generate_title_bg(app_state: object, game_id: UUID, narrative: str) -> None:
    """Fire-and-forget: generate a title from the opening narrative."""
    try:
        svc = app_state.summary_service  # type: ignore[attr-defined]
        title = await svc.generate_title(narrative)
        if title:
            sf = app_state.pipeline_deps.turn_repo._sf  # type: ignore[attr-defined]
            async with sf() as sess:
                await sess.execute(
                    sa.text(
                        "UPDATE game_sessions SET title = :t, "
                        "updated_at = :now WHERE id = :gid AND title IS NULL"
                    ),
                    {
                        "gid": game_id,
                        "t": title[:80],
                        "now": datetime.now(UTC),
                    },
                )
                await sess.commit()
            log.info("title_generated", game_id=str(game_id))
    except Exception:
        log.warning("title_generation_failed", game_id=str(game_id), exc_info=True)


async def _regen_summary_bg(app_state: object, game_id: UUID) -> None:
    """Fire-and-forget: regenerate the context summary for a game."""
    try:
        sf = app_state.pipeline_deps.turn_repo._sf  # type: ignore[attr-defined]
        turn_repo = app_state.pipeline_deps.turn_repo  # type: ignore[attr-defined]
        settings = app_state.settings  # type: ignore[attr-defined]

        turns = await turn_repo.get_recent_turns(
            game_id, limit=settings.resume_turn_count
        )
        if not turns:
            return

        svc = app_state.summary_service  # type: ignore[attr-defined]
        summary = await svc.generate_context_summary(turns)
        if summary:
            now = datetime.now(UTC)
            async with sf() as sess:
                await sess.execute(
                    sa.text(
                        "UPDATE game_sessions "
                        "SET summary = :s, summary_generated_at = :now, "
                        "updated_at = :now WHERE id = :gid"
                    ),
                    {"gid": game_id, "s": summary[:200], "now": now},
                )
                await sess.commit()
            log.info("summary_regenerated", game_id=str(game_id))
    except Exception:
        log.warning(
            "summary_regeneration_failed",
            game_id=str(game_id),
            exc_info=True,
        )


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
    "ended": "abandoned",
    "expired": "abandoned",
    "abandoned": "abandoned",
}


# --- Request / Response schemas ---


class CreateGameRequest(BaseModel):
    world_id: str | None = None
    preferences: dict[str, str] = Field(default_factory=dict)


class GameData(BaseModel):
    game_id: str
    player_id: str
    status: str
    turn_count: int
    title: str | None = None
    summary: str | None = None
    narrative_intro: str | None = None
    created_at: datetime
    updated_at: datetime
    last_played_at: datetime | None = None


class GameSummary(BaseModel):
    game_id: str
    status: str
    turn_count: int
    title: str | None = None
    summary: str | None = None
    created_at: datetime
    updated_at: datetime
    last_played_at: datetime | None = None


class PaginationMeta(BaseModel):
    next_cursor: str | None
    has_more: bool


class SubmitTurnRequest(BaseModel):
    input: str = Field(
        ...,
        max_length=2000,
        description="Player's natural-language input. Empty string triggers a nudge.",
    )
    idempotency_key: UUID | None = Field(
        None,
        description="Client-generated UUID for deduplication.",
    )


class TurnAccepted(BaseModel):
    turn_id: str
    turn_number: int
    stream_url: str


class SaveResult(BaseModel):
    game_id: str
    saved_at: datetime
    turn_count: int


class UpdateGameRequest(BaseModel):
    status: str = Field(
        ...,
        description=(
            "Target status. Supported transitions depend on current "
            "game status (e.g. active → paused, paused → active/ended)."
        ),
    )


class GameEndedData(BaseModel):
    game_id: str
    status: str
    turn_count: int
    ended_at: datetime


class DeleteGameRequest(BaseModel):
    confirm: bool = Field(
        ...,
        description="Must be true to confirm deletion (S27 FR-27.18).",
    )


# --- Command router & nudge phrases (S01 AC-1.2, AC-1.10) ---

_NUDGE_PHRASES = (
    "The world waits for your next move\u2026",
    "A gentle breeze stirs. What do you do?",
    "Silence stretches around you, full of possibility.",
    "The moment hangs, expectant. What catches your attention?",
    "You pause, taking in your surroundings. What draws you forward?",
    "Time seems to slow. The world is yours to explore.",
    "Something shifts in the air. Where do you turn your attention?",
    "The path ahead is yours to choose. What will it be?",
    "A quiet opening appears before you. How do you step into it?",
    "The scene invites a choice. What feels right to do next?",
)

_KNOWN_COMMANDS = frozenset({"help", "save", "status"})

_HELP_TEXT = (
    "Available commands:\n"
    "  /help   \u2014 Show this list of commands\n"
    "  /save   \u2014 Save your current progress\n"
    "  /status \u2014 View your game session info\n"
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
        turn_count = await _get_turn_count(pg, game_id)
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

    return {"type": "command", "command": "help", "message": _HELP_TEXT}


# --- Helper functions ---


async def _get_owned_game(pg: AsyncSession, game_id: UUID, player: Player) -> sa.Row:
    """Fetch a game row and verify ownership. Raises 404 if not found."""
    result = await pg.execute(
        sa.text(
            "SELECT id, player_id, status, world_seed, "
            "title, summary, turn_count, last_played_at, "
            "deleted_at, needs_recovery, summary_generated_at, "
            "created_at, updated_at "
            "FROM game_sessions WHERE id = :id"
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
    """Get the highest completed turn number for a game (0 if none).

    FR-23.17: failed turns do NOT advance the turn counter,
    so we only count turns that reached 'complete' status.
    """
    result = await pg.execute(
        sa.text(
            "SELECT coalesce(max(turn_number), 0) FROM turns "
            "WHERE session_id = :sid AND status = 'complete'"
        ),
        {"sid": game_id},
    )
    return result.scalar_one()


# --- Routes ---


@router.post("", status_code=201, dependencies=[Depends(require_active_player)])
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
            "status": GameStatus.active.value,
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


@router.post(
    "/{game_id}/turns",
    status_code=202,
    response_model=None,
    dependencies=[Depends(require_active_player)],
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
            "INVALID_STATE_TRANSITION",
            f"Cannot submit turns for a game in '{row.status}' status.",
        )

    # --- Pre-pipeline routing: commands and nudges (S01 AC-1.2, AC-1.10) ---
    normalized = body.input.strip()

    # Empty input → atmospheric nudge (no DB row, no turn_count change)
    if not normalized:
        return JSONResponse(
            content={
                "data": {
                    "type": "nudge",
                    "message": random.choice(_NUDGE_PHRASES),
                }
            },
            status_code=200,
        )

    # Slash commands → instant response (no DB row, no pipeline)
    if normalized.startswith("/") and len(normalized) > 1:
        known_cmd = _parse_slash_command(normalized)
        if known_cmd:
            payload = await _execute_command(known_cmd, game_id, row, pg)
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

    # Create turn
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

    # Dispatch pipeline as background task
    game_state = row.world_seed if row.world_seed else {}
    if isinstance(game_state, str):
        game_state = json.loads(game_state)
    asyncio.create_task(
        _dispatch_pipeline(
            app_state=request.app.state,
            game_id=game_id,
            turn_id=turn_id,
            turn_number=turn_number,
            player_input=body.input,
            game_state=game_state,
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
) -> StreamingResponse:
    """SSE endpoint — streams turn processing events to the client."""
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
    counter = SSECounter()
    correlation_id = getattr(request.state, "request_id", "unknown")

    # NOTE: event_stream is a complex generator because SSE streaming
    # requires a single async function yielding formatted events.
    # TODO: decompose into _wait_for_result() and _emit_turn_events()
    # helpers once the streaming contract stabilises.
    async def event_stream():  # noqa: C901
        if proc_row is None:
            yield ErrorEvent(
                code="NO_TURN_FOUND",
                message="No turn found for this game.",
                correlation_id=correlation_id,
                retry_after_seconds=2,
            ).format_sse(counter.next_id())
            return

        current_turn_number = proc_row.turn_number
        current_turn_id = str(proc_row.id)

        # Send turn_start
        yield TurnStartEvent(
            turn_id=current_turn_id,
            turn_number=current_turn_number,
        ).format_sse(counter.next_id())

        # FR-23.22: keepalive loop while waiting for pipeline result
        store = request.app.state.turn_result_store
        keepalive_interval = 15.0
        settings: Settings = request.app.state.settings
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
                yield KeepaliveEvent().format_sse(counter.next_id())

        if result is None:
            yield ErrorEvent(
                code="PIPELINE_TIMEOUT",
                message="Turn processing timed out.",
                correlation_id=correlation_id,
                retry_after_seconds=5,
            ).format_sse(counter.next_id())
            return

        if result.status == TurnStatus.failed:
            yield ErrorEvent(
                code="PIPELINE_FAILED",
                message="Turn processing failed.",
                correlation_id=correlation_id,
                retry_after_seconds=2,
            ).format_sse(counter.next_id())
            return

        # FR-24.06/FR-24.08: emit moderation event before narrative
        # when content was redirected by the moderation pipeline.
        if result.status == TurnStatus.moderated:
            log.info(
                "sse_moderation_event",
                turn_id=current_turn_id,
                safety_flags=result.safety_flags,
            )
            yield ModerationEvent(
                reason=(
                    "The story has been gently redirected "
                    "to maintain a supportive experience."
                ),
            ).format_sse(counter.next_id())

        # Stream the narrative as a complete block
        if result.narrative_output:
            yield NarrativeBlockEvent(
                full_text=result.narrative_output,
            ).format_sse(counter.next_id())

        # Turn complete
        yield TurnCompleteEvent(
            turn_number=result.turn_number,
            model_used=result.model_used or "unknown",
            latency_ms=result.latency_ms or 0.0,
        ).format_sse(counter.next_id())

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


@router.delete("/{game_id}")
async def end_game(
    game_id: UUID,
    body: DeleteGameRequest | None = None,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """Soft-delete a game (S27 FR-27.16–FR-27.19)."""
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

    return {
        "data": GameEndedData(
            game_id=str(row.id),
            status="abandoned",
            turn_count=turn_count,
            ended_at=now,
        ).model_dump(mode="json")
    }
