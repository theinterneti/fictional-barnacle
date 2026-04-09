"""Admin API router (S26 — Admin & Operator Tooling).

All endpoints require ``Authorization: Bearer <admin_api_key>``
(FR-26.02–FR-26.04).  Non-GET requests create immutable audit-log
entries (FR-26.24).

Endpoint inventory (Appendix A):
  §3.2  Player management  — GET/POST /admin/players/…
  §3.3  Game inspection     — GET/POST /admin/games/…
  §3.4  System health       — GET /admin/health, /admin/metrics
  §3.5  Moderation queue    — GET/POST /admin/moderation/…
  §3.6  Rate-limit mgmt     — GET/POST /admin/rate-limits/…
  §3.7  Audit log           — GET /admin/audit-log
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from tta.admin.auth import AdminIdentity, require_admin
from tta.api.errors import AppError
from tta.errors import ErrorCategory
from tta.observability.metrics import REGISTRY, generate_latest

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])
log = structlog.get_logger()


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------


class SuspendRequest(BaseModel):
    reason: str = Field(..., min_length=10)


class TerminateRequest(BaseModel):
    reason: str = Field(..., min_length=10)


class ReviewRequest(BaseModel):
    action: str = Field(..., pattern=r"^(dismiss|warn|suspend_player)$")
    reason: str = Field("", min_length=0)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _audit(
    request: Request,
    admin: AdminIdentity,
    *,
    action: str,
    target_type: str,
    target_id: str,
    reason: str = "",
) -> None:
    """Create an audit-log entry (FR-26.24)."""
    repo = request.app.state.audit_repo
    await repo.create_and_append(
        admin_id=admin.admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        source_ip=_client_ip(request),
    )


# ==================================================================
# §3.2  Player management
# ==================================================================


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
                "SELECT id, handle, display_name, status, "
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
            "display_name": player.display_name,
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
    """Search players by handle prefix (FR-26.06)."""
    import sqlalchemy as sa

    clauses = ["1=1"]
    params: dict[str, object] = {"lim": limit}

    if search:
        clauses.append("handle ILIKE :prefix")
        params["prefix"] = f"{search}%"
    if cursor:
        clauses.append("id < :cursor")
        params["cursor"] = cursor

    where = " AND ".join(clauses)
    async with request.app.state.pg() as session:
        result = await session.execute(
            sa.text(
                f"SELECT id, handle, display_name, status, created_at "
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
            "display_name": r.display_name,
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
        raise AppError(
            ErrorCategory.NOT_FOUND,
            "PLAYER_NOT_FOUND_OR_ALREADY_SUSPENDED",
            f"Player {player_id} not found or already suspended.",
        )

    await _audit(
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

    await _audit(
        request,
        admin,
        action="unsuspend_player",
        target_type="player",
        target_id=str(player_id),
    )

    return JSONResponse(content={"status": "active", "player_id": str(player_id)})


# ==================================================================
# §3.3  Game inspection
# ==================================================================


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

    async with request.app.state.pg() as session:
        result = await session.execute(
            sa.text(
                "UPDATE game_sessions SET status = 'ended' "
                "WHERE id = :gid AND status IN ('active', 'paused') "
                "RETURNING id"
            ),
            {"gid": game_id},
        )
        await session.commit()
        updated = result.first()

    if updated is None:
        raise AppError(
            ErrorCategory.NOT_FOUND,
            "GAME_NOT_FOUND_OR_NOT_ACTIVE",
            f"Game {game_id} not found or not in active/paused state.",
        )

    await _audit(
        request,
        admin,
        action="terminate_game",
        target_type="game",
        target_id=str(game_id),
        reason=body.reason,
    )

    return JSONResponse(content={"status": "ended", "game_id": str(game_id)})


# ==================================================================
# §3.4  System health & metrics
# ==================================================================


@router.get("/health")
async def admin_health(
    request: Request,
    _admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Comprehensive subsystem health (FR-26.14)."""
    from tta.api.health import _derive_status, _run_checks

    checks = await _run_checks(request)

    # LLM semaphore info
    sem = getattr(request.app.state, "llm_semaphore", None)
    llm_info: dict[str, Any] = {}
    if sem is not None:
        llm_info = {
            "active": sem.active,
            "waiting": sem.waiting,
            "max_concurrent": sem.max_concurrent,
            "queue_size": sem.queue_size,
        }

    status = _derive_status(checks)
    return JSONResponse(
        status_code=503 if status == "unhealthy" else 200,
        content={
            "status": status,
            "checks": checks,
            "llm_semaphore": llm_info,
        },
    )


@router.get("/metrics")
async def admin_metrics(
    _admin: AdminIdentity = Depends(require_admin),
) -> Response:
    """Prometheus-format metrics (FR-26.16)."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ==================================================================
# §3.5  Moderation queue
# ==================================================================


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


@router.get("/moderation/flags")
async def list_moderation_flags(
    request: Request,
    status: str | None = Query(None),
    category: str | None = Query(None),
    game_id: str | None = Query(None),
    player_id: str | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    _admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Paginated moderation flags (FR-26.17)."""
    recorder = getattr(request.app.state, "moderation_recorder", None)
    if recorder is None:
        return JSONResponse(content={"flags": [], "next_cursor": None})

    flags = await recorder.query(
        status=status,
        category=category,
        game_id=game_id,
        player_id=player_id,
        cursor=cursor,
        limit=limit,
    )

    serialized = _serialize_flags(flags)
    next_cursor = str(flags[-1].get("moderation_id", "")) if flags else None
    return JSONResponse(content={"flags": serialized, "next_cursor": next_cursor})


@router.post("/moderation/flags/{flag_id}/review")
async def review_moderation_flag(
    flag_id: str,
    body: ReviewRequest,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Review a moderation flag (FR-26.18)."""
    recorder = getattr(request.app.state, "moderation_recorder", None)
    if recorder is None:
        raise AppError(
            ErrorCategory.SERVICE_UNAVAILABLE,
            "MODERATION_NOT_CONFIGURED",
            "Moderation system is not configured.",
        )

    verdict_map = {
        "dismiss": "pass",
        "warn": "flag",
        "suspend_player": "block",
    }
    new_verdict = verdict_map[body.action]
    updated = await recorder.update_verdict(flag_id, new_verdict)
    if not updated:
        raise AppError(
            ErrorCategory.NOT_FOUND,
            "FLAG_NOT_FOUND",
            f"Moderation flag {flag_id} not found.",
        )

    await _audit(
        request,
        admin,
        action=f"moderation_review_{body.action}",
        target_type="moderation_flag",
        target_id=flag_id,
        reason=body.reason,
    )

    return JSONResponse(
        content={
            "flag_id": flag_id,
            "action": body.action,
            "new_verdict": new_verdict,
        }
    )


# ==================================================================
# §3.6  Rate-limit management
# ==================================================================


@router.get("/rate-limits/player/{player_id}")
async def get_player_rate_limits(
    player_id: UUID,
    request: Request,
    _admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Current rate-limit/cooldown state for a player (FR-26.20)."""
    result: dict[str, object] = {"player_id": str(player_id)}

    detector = getattr(request.app.state, "abuse_detector", None)
    if detector is not None:
        cd = await detector.check_cooldown(str(player_id))
        result["cooldown"] = {
            "active": cd.active,
            "remaining_seconds": cd.remaining_seconds,
            "pattern": cd.pattern,
            "violation_count": cd.violation_count,
        }
    else:
        result["cooldown"] = None

    return JSONResponse(content=result)


@router.post("/rate-limits/player/{player_id}/reset")
async def reset_player_rate_limits(
    player_id: UUID,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Clear rate limits + cooldowns for a player (FR-26.21)."""
    detector = getattr(request.app.state, "abuse_detector", None)
    if detector is not None:
        await detector.clear_cooldown(str(player_id))

    await _audit(
        request,
        admin,
        action="reset_player_rate_limits",
        target_type="player",
        target_id=str(player_id),
    )

    return JSONResponse(
        content={
            "player_id": str(player_id),
            "status": "rate_limits_cleared",
        }
    )


@router.get("/rate-limits/ip/{ip_address}")
async def get_ip_rate_limits(
    ip_address: str,
    request: Request,
    _admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Current rate-limit state for an IP (FR-26.22)."""
    result: dict[str, object] = {"ip": ip_address}

    detector = getattr(request.app.state, "abuse_detector", None)
    if detector is not None:
        cd = await detector.check_cooldown(ip_address)
        result["cooldown"] = {
            "active": cd.active,
            "remaining_seconds": cd.remaining_seconds,
            "pattern": cd.pattern,
            "violation_count": cd.violation_count,
        }
    else:
        result["cooldown"] = None

    return JSONResponse(content=result)


@router.post("/rate-limits/ip/{ip_address}/unblock")
async def unblock_ip(
    ip_address: str,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Remove IP blocks / rate limits (FR-26.23)."""
    detector = getattr(request.app.state, "abuse_detector", None)
    if detector is not None:
        await detector.clear_cooldown(ip_address)

    rl = request.app.state.rate_limiter
    # Clear known IP rate-limit groups
    for group in ("default", "burst", "turn"):
        await rl.clear_key(f"rl:ip:{ip_address}:{group}")

    await _audit(
        request,
        admin,
        action="unblock_ip",
        target_type="ip",
        target_id=ip_address,
    )

    return JSONResponse(content={"ip": ip_address, "status": "unblocked"})


# ==================================================================
# §3.7  Audit log
# ==================================================================


@router.get("/audit-log")
async def query_audit_log(
    request: Request,
    admin_id: str | None = Query(None),
    action: str | None = Query(None),
    target_type: str | None = Query(None),
    target_id: str | None = Query(None),
    cursor: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    _admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Paginated, filterable audit log (FR-26.25)."""
    repo = request.app.state.audit_repo
    entries = await repo.query(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        cursor=cursor,
        limit=limit,
    )

    items = [
        {
            "id": str(e.id),
            "admin_id": e.admin_id,
            "action": e.action,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "reason": e.reason,
            "source_ip": e.source_ip,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in entries
    ]
    next_cursor = str(entries[-1].id) if entries else None
    return JSONResponse(content={"entries": items, "next_cursor": next_cursor})
