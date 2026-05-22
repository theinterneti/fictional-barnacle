"""Game session routes (plan §2.4–2.12)."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from redis.asyncio import Redis

from tta.api.deps import (
    get_current_player,
    get_pg,
    get_redis,
    require_anonymous_game_limit,
)
from tta.api.errors import AppError
from tta.api.routes.games_helpers import (
    _count_active_games,
    _get_owned_game,
    _get_turn_count,
)
from tta.api.routes.games_lifecycle import router as _lifecycle
from tta.api.routes.games_turns import router as _turns
from tta.api.sse import SseEventBuffer
from tta.config import Settings, get_settings
from tta.errors import ErrorCategory
from tta.models.game import (
    CreateGameRequest,
    GameData,
    GameStatus,
    GameSummary,
    PaginationMeta,
)
from tta.models.player import Player
from tta.models.turn import TurnState, TurnStatus
from tta.models.world import (
    WorldSeed,
)
from tta.observability.metrics import (
    SESSIONS_ACTIVE,
    SSE_BUFFER_SIZE,
    SSE_REPLAY_HITS,
    SSE_REPLAY_MISSES,
)
from tta.pipeline.world_changes import (
    translate_world_updates,
)
from tta.transport import SSETransport

log = structlog.get_logger()

router = APIRouter(prefix="/games", tags=["games"])

router.include_router(_lifecycle)
router.include_router(_turns)
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


# ── Re-exports for backward compatibility ──
# Symbols extracted to games_commands.py
from tta.api.routes.games_commands import (  # noqa: E402, F401
    _KNOWN_COMMANDS,
    _build_character_response,
    _build_relationships_response,
    _dimension_label,
    _execute_end_command,
    _generate_epilogue,
)
