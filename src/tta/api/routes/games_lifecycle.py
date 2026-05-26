"""Game lifecycle routes — save, restore, resume, update, end.

Extracted from games.py during code health decomposition.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from redis.asyncio import Redis

from tta.api.deps import get_current_player, get_pg, get_redis
from tta.api.errors import AppError
from tta.api.routes.games_helpers import _get_owned_game, _get_turn_count
from tta.config import Settings
from tta.errors import ErrorCategory
from tta.models.game import (
    DeleteGameRequest,
    GameData,
    SaveResult,
    UpdateGameRequest,
)
from tta.models.player import Player
from tta.observability.metrics import (
    SESSION_DURATION,
    SESSION_TURNS,
    SESSIONS_ACTIVE,
)
from tta.persistence.redis_session import set_active_session
from tta.pipeline.orchestrator import _regen_summary_bg

log = structlog.get_logger(__name__)

router = APIRouter(tags=["games"])

# Valid state transitions (plan §6.1, S27 FR-27.01)
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "created": {"active", "abandoned"},
    "active": {"paused", "completed", "ended"},
    "paused": {"active", "expired", "ended"},
    "expired": {"active"},
}


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
            "generation_profile": (
                getattr(row, "generation_profile", None) or "balanced"
            ),
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
