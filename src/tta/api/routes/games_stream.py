"""SSE streaming endpoint for turn processing events.

Extracted from games.py during code health decomposition.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from redis.asyncio import Redis

from tta.api.deps import get_current_player, get_pg, get_redis
from tta.api.routes.games_helpers import _get_owned_game
from tta.api.sse import SseEventBuffer
from tta.config import Settings
from tta.models.player import Player
from tta.models.turn import TurnState, TurnStatus
from tta.observability.metrics import (
    SSE_BUFFER_SIZE,
    SSE_REPLAY_HITS,
    SSE_REPLAY_MISSES,
)
from tta.pipeline.world_changes import translate_world_updates
from tta.transport import SSETransport

log = structlog.get_logger(__name__)

router = APIRouter(tags=["games"])


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
