"""Game session routes (plan §2.4–2.12)."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.deps import get_current_player, get_pg
from tta.api.errors import AppError
from tta.api.sse import SSECounter
from tta.config import get_settings
from tta.models.events import (
    ErrorEvent,
    NarrativeBlockEvent,
    TurnCompleteEvent,
    TurnStartEvent,
)
from tta.models.game import GameStatus
from tta.models.player import Player
from tta.models.turn import TurnState, TurnStatus
from tta.pipeline.orchestrator import run_pipeline

log = structlog.get_logger()

router = APIRouter(prefix="/games", tags=["games"])

# In-memory store for completed turn results, keyed by game_id.
# SSE endpoint polls this until the result arrives.
# Production would use Redis pub/sub — this is sufficient for v1.
_MAX_PENDING_RESULTS = 1000
_turn_results: dict[str, TurnState] = {}


def _store_turn_result(game_id: str, result: TurnState) -> None:
    """Store a turn result with bounded eviction."""
    if len(_turn_results) >= _MAX_PENDING_RESULTS:
        # Evict oldest half (dict is insertion-ordered in 3.7+)
        keys = list(_turn_results.keys())[: _MAX_PENDING_RESULTS // 2]
        for k in keys:
            _turn_results.pop(k, None)
    _turn_results[game_id] = result


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
    try:
        if result.status == TurnStatus.complete and result.narrative_output:
            token_dict = (
                result.token_count.model_dump() if result.token_count else {}
            )
            await turn_repo.complete_turn(
                turn_id=turn_id,
                narrative_output=result.narrative_output,
                model_used=result.model_used or "unknown",
                latency_ms=elapsed_ms,
                token_count=token_dict,
            )
        else:
            await turn_repo.update_status(turn_id, "failed")
    except Exception:
        log.error("turn_persist_failed", turn_id=str(turn_id), exc_info=True)

    # Publish result for SSE endpoint
    _store_turn_result(str(game_id), result)
    log.info(
        "pipeline_dispatch_complete",
        game_id=str(game_id),
        turn_id=str(turn_id),
        status=result.status,
        latency_ms=round(elapsed_ms, 1),
    )


# Valid state transitions (plan §6.1)
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "created": {"active", "abandoned"},
    "active": {"paused", "ended"},
    "paused": {"active", "expired", "ended"},
    "expired": {"active"},
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
    created_at: datetime
    updated_at: datetime


class GameSummary(BaseModel):
    game_id: str
    status: str
    turn_count: int
    created_at: datetime
    updated_at: datetime


class PaginationMeta(BaseModel):
    next_cursor: str | None
    has_more: bool


class SubmitTurnRequest(BaseModel):
    input: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Player's natural-language input.",
    )
    idempotency_key: UUID | None = Field(
        None,
        description="Client-generated UUID for deduplication.",
    )

    @field_validator("input")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            msg = "Input must not be blank"
            raise ValueError(msg)
        return v


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


# --- Helper functions ---


async def _get_owned_game(pg: AsyncSession, game_id: UUID, player: Player) -> sa.Row:
    """Fetch a game row and verify ownership. Raises 404 if not found."""
    result = await pg.execute(
        sa.text(
            "SELECT id, player_id, status, world_seed, "
            "created_at, updated_at "
            "FROM game_sessions WHERE id = :id"
        ),
        {"id": game_id},
    )
    row = result.one_or_none()
    if row is None or row.player_id != player.id:
        raise AppError(404, "GAME_NOT_FOUND", "Game not found.")
    return row


async def _count_active_games(pg: AsyncSession, player_id: UUID) -> int:
    """Count non-terminal games for the player."""
    result = await pg.execute(
        sa.text(
            "SELECT count(*) FROM game_sessions "
            "WHERE player_id = :pid "
            "AND status IN ('created', 'active', 'paused')"
        ),
        {"pid": player_id},
    )
    return result.scalar_one()


async def _get_turn_count(pg: AsyncSession, game_id: UUID) -> int:
    """Get the number of completed turns for a game."""
    result = await pg.execute(
        sa.text(
            "SELECT count(*) FROM turns WHERE session_id = :sid AND status = 'complete'"
        ),
        {"sid": game_id},
    )
    return result.scalar_one()


async def _get_max_turn_number(pg: AsyncSession, game_id: UUID) -> int:
    """Get the highest turn number for a game (0 if none)."""
    result = await pg.execute(
        sa.text(
            "SELECT coalesce(max(turn_number), 0) FROM turns WHERE session_id = :sid"
        ),
        {"sid": game_id},
    )
    return result.scalar_one()


# --- Routes ---


@router.post("", status_code=201)
async def create_game(
    body: CreateGameRequest,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """Create a new game session."""
    settings = get_settings()
    active_count = await _count_active_games(pg, player.id)
    if active_count >= settings.max_active_games:
        raise AppError(
            409,
            "MAX_GAMES_REACHED",
            f"Maximum of {settings.max_active_games} active games reached.",
        )

    game_id = uuid4()
    now = datetime.now(UTC)
    world_seed = {"world_id": body.world_id, "preferences": body.preferences}

    await pg.execute(
        sa.text(
            "INSERT INTO game_sessions "
            "(id, player_id, status, world_seed, created_at, updated_at) "
            "VALUES (:id, :pid, :status, "
            "cast(:seed AS jsonb), :now, :now)"
        ),
        {
            "id": game_id,
            "pid": player.id,
            "status": GameStatus.created.value,
            "seed": json.dumps(world_seed),
            "now": now,
        },
    )
    await pg.commit()

    return {
        "data": GameData(
            game_id=str(game_id),
            player_id=str(player.id),
            status=GameStatus.created.value,
            turn_count=0,
            created_at=now,
            updated_at=now,
        ).model_dump(mode="json")
    }


@router.get("")
async def list_games(
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
    status: str | None = Query(None),
    cursor: datetime | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """List the authenticated player's games."""
    params: dict = {"pid": player.id, "lim": limit + 1}
    where_clauses = ["gs.player_id = :pid"]

    if status is not None:
        where_clauses.append("gs.status = :status")
        params["status"] = status
    if cursor is not None:
        where_clauses.append("gs.updated_at < :cursor")
        params["cursor"] = cursor

    where = " AND ".join(where_clauses)
    result = await pg.execute(
        sa.text(
            f"SELECT gs.id, gs.player_id, gs.status, gs.world_seed, "  # noqa: S608
            f"gs.created_at, gs.updated_at, "
            f"coalesce(tc.cnt, 0) AS turn_count "
            f"FROM game_sessions gs "
            f"LEFT JOIN ("
            f"  SELECT session_id, count(*) AS cnt "
            f"  FROM turns WHERE status = 'complete' "
            f"  GROUP BY session_id"
            f") tc ON tc.session_id = gs.id "
            f"WHERE {where} "
            f"ORDER BY gs.updated_at DESC LIMIT :lim"
        ),
        params,
    )
    rows = result.all()
    has_more = len(rows) > limit
    items = rows[:limit]

    games = [
        GameSummary(
            game_id=str(r.id),
            status=r.status,
            turn_count=r.turn_count,
            created_at=r.created_at,
            updated_at=r.updated_at,
        ).model_dump(mode="json")
        for r in items
    ]

    next_cursor = items[-1].updated_at.isoformat() if has_more and items else None

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
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "recent_turns": recent,
            "processing_turn": (str(processing_row.id) if processing_row else None),
        }
    }


@router.post("/{game_id}/turns", status_code=202)
async def submit_turn(
    game_id: UUID,
    body: SubmitTurnRequest,
    request: Request,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """Submit a player turn for processing."""
    row = await _get_owned_game(pg, game_id, player)

    # Must be active or created
    if row.status not in ("active", "created"):
        raise AppError(
            422,
            "INVALID_STATE_TRANSITION",
            f"Cannot submit turns for a game in '{row.status}' status.",
        )

    # Concurrent turn check — advisory lock serialises per-game
    await pg.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtext(:gid))"),
        {"gid": str(game_id)},
    )
    in_flight = await pg.execute(
        sa.text(
            "SELECT id FROM turns "
            "WHERE session_id = :sid AND status = 'processing'"
        ),
        {"sid": game_id},
    )
    if in_flight.one_or_none() is not None:
        raise AppError(
            409,
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

    # Transition created → active on first turn
    if row.status == "created":
        await pg.execute(
            sa.text(
                "UPDATE game_sessions SET status = 'active', "
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

    # Look up the current processing turn for its number
    proc_result = await pg.execute(
        sa.text(
            "SELECT turn_number FROM turns "
            "WHERE session_id = :sid AND status = 'processing' "
            "LIMIT 1"
        ),
        {"sid": game_id},
    )
    proc_row = proc_result.one_or_none()
    current_turn_number = proc_row.turn_number if proc_row else 0
    counter = SSECounter()

    async def event_stream():  # noqa: C901
        gid = str(game_id)

        # Send turn_start
        yield TurnStartEvent(
            turn_number=current_turn_number,
        ).format_sse(counter.next_id())

        # Poll for pipeline result (max ~120s)
        result: TurnState | None = None
        for _ in range(240):
            if gid in _turn_results:
                result = _turn_results.pop(gid)
                break
            # Check if client disconnected
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.5)

        if result is None:
            yield ErrorEvent(
                code="PIPELINE_TIMEOUT",
                message="Turn processing timed out.",
            ).format_sse(counter.next_id())
            return

        if result.status == TurnStatus.failed:
            yield ErrorEvent(
                code="PIPELINE_FAILED",
                message="Turn processing failed.",
            ).format_sse(counter.next_id())
            return

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
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """Resume a paused or expired game."""
    row = await _get_owned_game(pg, game_id, player)

    if row.status == "active":
        # Already active — return current state (no-op)
        turn_count = await _get_turn_count(pg, game_id)
        return {
            "data": {
                "game_id": str(row.id),
                "player_id": str(row.player_id),
                "status": row.status,
                "turn_count": turn_count,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
        }

    if row.status not in ("paused", "expired"):
        raise AppError(
            422,
            "GAME_NOT_RESUMABLE",
            f"Cannot resume a game in '{row.status}' status.",
        )

    now = datetime.now(UTC)
    await pg.execute(
        sa.text(
            "UPDATE game_sessions SET status = 'active', "
            "updated_at = :now WHERE id = :id"
        ),
        {"id": game_id, "now": now},
    )
    await pg.commit()

    turn_count = await _get_turn_count(pg, game_id)

    return {
        "data": {
            "game_id": str(row.id),
            "player_id": str(row.player_id),
            "status": "active",
            "turn_count": turn_count,
            "created_at": row.created_at.isoformat(),
            "updated_at": now.isoformat(),
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
            422,
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
            created_at=row.created_at,
            updated_at=now,
        ).model_dump(mode="json")
    }


@router.delete("/{game_id}")
async def end_game(
    game_id: UUID,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """End a game (soft delete)."""
    row = await _get_owned_game(pg, game_id, player)

    if row.status in ("ended", "abandoned"):
        raise AppError(
            422,
            "INVALID_STATE_TRANSITION",
            f"Game is already in '{row.status}' status.",
        )

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

    return {
        "data": GameEndedData(
            game_id=str(row.id),
            status="ended",
            turn_count=turn_count,
            ended_at=now,
        ).model_dump(mode="json")
    }
