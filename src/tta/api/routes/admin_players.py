"""Admin player management routes (§3.2).

Extracted from admin.py — player lookup, search, suspend, unsuspend.
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
from tta.models.admin import SuspendRequest

router = APIRouter(tags=["admin"])
log = structlog.get_logger(__name__)


@router.get("/players/{player_id}")
async def get_player(
    player_id: UUID,
    request: Request,
    _admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Player profile + game counts + rate-limit state (FR-26.05)."""
    import sqlalchemy as sa

    async with request.app.state.pg() as session:
        row = await session.execute(
            sa.text(
                "SELECT id, handle, status, "
                "suspended_reason, created_at "
                "FROM players WHERE id = :pid"
            ),
            {"pid": player_id},
        )
        player = row.first()
    if player is None:
        raise AppError(
            ErrorCategory.NOT_FOUND,
            "PLAYER_NOT_FOUND",
            f"Player {player_id} not found.",
        )

    # Game counts
    import sqlalchemy as sa  # noqa: F811

    async with request.app.state.pg() as session:
        gc = await session.execute(
            sa.text(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE status = 'active') AS active "
                "FROM game_sessions WHERE player_id = :pid "
                "AND deleted_at IS NULL"
            ),
            {"pid": player_id},
        )
        counts = gc.first()

    # Abuse detector cooldown (keyed by player_id str)
    cooldown: dict[str, object] = {}
    detector = getattr(request.app.state, "abuse_detector", None)
    if detector is not None:
        cd = await detector.check_cooldown(str(player_id))
        cooldown = {
            "active": cd.active,
            "remaining_seconds": cd.remaining_seconds,
            "pattern": cd.pattern,
            "violation_count": cd.violation_count,
        }

    return JSONResponse(
        content={
            "player_id": str(player.id),
            "handle": player.handle,
            "status": player.status,
            "suspended_reason": player.suspended_reason,
            "created_at": player.created_at.isoformat(),
            "games": {
                "total": counts.total if counts else 0,
                "active": counts.active if counts else 0,
            },
            "rate_limit": cooldown,
        }
    )


@router.get("/players")
async def search_players(
    request: Request,
    search: str = Query("", min_length=0),
    cursor: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    _admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Search by handle prefix or exact player_id (FR-26.06)."""
    import sqlalchemy as sa

    clauses = ["1=1"]
    params: dict[str, object] = {"lim": limit}

    if search:
        # Try exact UUID match first, fall back to handle prefix
        try:
            exact_id = UUID(search)
            clauses.append("id = :exact_id")
            params["exact_id"] = exact_id
        except ValueError:
            clauses.append("handle ILIKE :prefix")
            params["prefix"] = f"{search}%"
    if cursor:
        clauses.append("id < :cursor")
        params["cursor"] = cursor

    where = " AND ".join(clauses)
    async with request.app.state.pg() as session:
        result = await session.execute(
            sa.text(
                f"SELECT id, handle, status, created_at "
                f"FROM players WHERE {where} "
                f"ORDER BY id DESC LIMIT :lim"
            ),
            params,
        )
        rows = result.all()

    players = [
        {
            "player_id": str(r.id),
            "handle": r.handle,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    next_cursor = str(rows[-1].id) if rows else None
    return JSONResponse(content={"players": players, "next_cursor": next_cursor})


@router.post("/players/{player_id}/suspend")
async def suspend_player(
    player_id: UUID,
    body: SuspendRequest,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Suspend a player account (FR-26.07)."""
    import sqlalchemy as sa

    async with request.app.state.pg() as session:
        result = await session.execute(
            sa.text(
                "UPDATE players SET status = 'suspended', "
                "suspended_reason = :reason "
                "WHERE id = :pid AND status != 'suspended' "
                "RETURNING id"
            ),
            {"pid": player_id, "reason": body.reason},
        )
        await session.commit()
        updated = result.first()

    if updated is None:
        # Disambiguate: 404 if player does not exist, 409 if already suspended
        async with request.app.state.pg() as session:
            check = await session.execute(
                sa.text("SELECT status FROM players WHERE id = :pid"),
                {"pid": player_id},
            )
            existing = check.first()
        if existing is None:
            raise AppError(
                ErrorCategory.NOT_FOUND,
                "PLAYER_NOT_FOUND",
                f"Player {player_id} not found.",
            )
        raise AppError(
            ErrorCategory.CONFLICT,
            "PLAYER_ALREADY_SUSPENDED",
            f"Player {player_id} is already suspended.",
        )

    await audit(
        request,
        admin,
        action="suspend_player",
        target_type="player",
        target_id=str(player_id),
        reason=body.reason,
    )

    return JSONResponse(content={"status": "suspended", "player_id": str(player_id)})


@router.post("/players/{player_id}/unsuspend")
async def unsuspend_player(
    player_id: UUID,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Remove suspension from a player (FR-26.08)."""
    import sqlalchemy as sa

    async with request.app.state.pg() as session:
        result = await session.execute(
            sa.text(
                "UPDATE players SET status = 'active', "
                "suspended_reason = NULL "
                "WHERE id = :pid AND status = 'suspended' "
                "RETURNING id"
            ),
            {"pid": player_id},
        )
        await session.commit()
        updated = result.first()

    if updated is None:
        raise AppError(
            ErrorCategory.NOT_FOUND,
            "PLAYER_NOT_FOUND_OR_NOT_SUSPENDED",
            f"Player {player_id} not found or not suspended.",
        )

    await audit(
        request,
        admin,
        action="unsuspend_player",
        target_type="player",
        target_id=str(player_id),
    )

    return JSONResponse(content={"status": "active", "player_id": str(player_id)})
