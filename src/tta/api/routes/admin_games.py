"""Admin game inspection routes (§3.3).

Extracted from admin.py — game lookup, turns, terminate.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from tta.admin.auth import AdminIdentity, require_admin
from tta.api.errors import AppError
from tta.api.routes._admin_helpers import audit
from tta.errors import ErrorCategory
from tta.models.admin import TerminateRequest
from tta.observability.metrics import SESSIONS_ACTIVE
from tta.persistence.redis_session import evict_game_state

router = APIRouter(tags=["admin"])
log = structlog.get_logger(__name__)


def _serialize_flags(
    flags: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Convert moderation records to JSON-safe dicts."""
    out: list[dict[str, object]] = []
    for f in flags:
        entry: dict[str, object] = {}
        for k, v in f.items():
            if hasattr(v, "isoformat"):
                entry[k] = v.isoformat()  # type: ignore[union-attr]
            elif hasattr(v, "value"):
                entry[k] = v.value  # type: ignore[union-attr]
            else:
                entry[k] = str(v) if isinstance(v, UUID) else v
        out.append(entry)
    return out


@router.get("/games/{game_id}")
async def get_game(
    game_id: UUID,
    request: Request,
    _admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Full game state with moderation flags (FR-26.10)."""
    import sqlalchemy as sa

    async with request.app.state.pg() as session:
        row = await session.execute(
            sa.text(
                "SELECT id, player_id, status, world_seed, title, "
                "summary, turn_count, needs_recovery, "
                "last_played_at, created_at, updated_at "
                "FROM game_sessions WHERE id = :gid"
            ),
            {"gid": game_id},
        )
        game = row.first()

    if game is None:
        raise AppError(
            ErrorCategory.NOT_FOUND,
            "GAME_NOT_FOUND",
            f"Game {game_id} not found.",
        )

    # Moderation flags for this game
    recorder = getattr(request.app.state, "moderation_recorder", None)
    flags: list[dict[str, object]] = []
    if recorder is not None:
        flags = await recorder.query(game_id=str(game_id), limit=20)

    return JSONResponse(
        content={
            "game_id": str(game.id),
            "player_id": str(game.player_id),
            "status": game.status,
            "world_seed": game.world_seed,
            "title": game.title,
            "summary": game.summary,
            "turn_count": game.turn_count,
            "needs_recovery": game.needs_recovery,
            "last_played_at": (
                game.last_played_at.isoformat() if game.last_played_at else None
            ),
            "created_at": game.created_at.isoformat(),
            "updated_at": (game.updated_at.isoformat() if game.updated_at else None),
            "moderation_flags": _serialize_flags(flags),
        }
    )


@router.get("/games/{game_id}/turns")
async def get_game_turns(
    game_id: UUID,
    request: Request,
    cursor: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    _admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Paginated turns with LLM metadata (FR-26.11)."""
    import sqlalchemy as sa

    clauses = ["session_id = :gid"]
    params: dict[str, object] = {"gid": game_id, "lim": limit}

    if cursor is not None:
        clauses.append("turn_number < :cursor")
        params["cursor"] = cursor

    where = " AND ".join(clauses)
    async with request.app.state.pg() as session:
        result = await session.execute(
            sa.text(
                f"SELECT id, session_id, turn_number, player_input, "
                f"status, narrative_output, model_used, latency_ms, "
                f"token_count, created_at, completed_at "
                f"FROM turns WHERE {where} "
                f"ORDER BY turn_number DESC LIMIT :lim"
            ),
            params,
        )
        rows = result.all()

    turns = [
        {
            "turn_id": str(r.id),
            "game_id": str(r.session_id),
            "turn_number": r.turn_number,
            "player_input": r.player_input,
            "status": r.status,
            "narrative_output": r.narrative_output,
            "model_used": r.model_used,
            "latency_ms": r.latency_ms,
            "token_count": r.token_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "completed_at": (r.completed_at.isoformat() if r.completed_at else None),
        }
        for r in rows
    ]
    next_cursor = rows[-1].turn_number if rows else None
    return JSONResponse(content={"turns": turns, "next_cursor": next_cursor})


@router.post("/games/{game_id}/terminate")
async def terminate_game(
    game_id: UUID,
    body: TerminateRequest,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Force-terminate a game (FR-26.12)."""
    import sqlalchemy as sa

    # Atomic UPDATE: only matches active/paused games (EC-26.2)
    async with request.app.state.pg() as session:
        result = await session.execute(
            sa.text(
                "UPDATE game_sessions SET status = 'completed' "
                "WHERE id = :gid AND status IN ('active', 'paused') "
                "RETURNING id"
            ),
            {"gid": game_id},
        )
        await session.commit()
        updated = result.first()

    if updated is None:
        # Disambiguate: 404 if game does not exist, 409 if already terminated
        async with request.app.state.pg() as session:
            check = await session.execute(
                sa.text("SELECT status FROM game_sessions WHERE id = :gid"),
                {"gid": game_id},
            )
            existing = check.first()
        if existing is None:
            raise AppError(
                ErrorCategory.NOT_FOUND,
                "GAME_NOT_FOUND",
                f"Game {game_id} not found.",
            )
        raise AppError(
            ErrorCategory.CONFLICT,
            "GAME_ALREADY_TERMINATED",
            "Game is already completed.",
        )

    SESSIONS_ACTIVE.dec()

    await audit(
        request,
        admin,
        action="terminate_game",
        target_type="game",
        target_id=str(game_id),
        reason=body.reason,
    )

    # Best-effort: evict cached session and close any active SSE connections
    redis = request.app.state.redis
    if redis is not None:
        try:
            await evict_game_state(redis, game_id)
        except Exception:
            log.warning("admin.terminate_game.redis_evict_failed", game_id=str(game_id))

    return JSONResponse(content={"status": "completed", "game_id": str(game_id)})
