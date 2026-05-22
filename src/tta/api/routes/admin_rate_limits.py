"""Admin rate-limit management routes (§3.6).

Extracted from admin.py — player/IP rate limit inspection, reset, unblock.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from tta.admin.auth import AdminIdentity, require_admin
from tta.api.routes._admin_helpers import audit
from tta.models.admin import ReasonRequest

router = APIRouter(tags=["admin"])
log = structlog.get_logger(__name__)


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
    body: ReasonRequest,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Clear rate limits + cooldowns for a player (FR-26.21)."""
    detector = getattr(request.app.state, "abuse_detector", None)
    if detector is not None:
        await detector.clear_cooldown(str(player_id))

    await audit(
        request,
        admin,
        action="reset_player_rate_limits",
        target_type="player",
        target_id=str(player_id),
        reason=body.reason,
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
    body: ReasonRequest,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Remove IP blocks / rate limits (FR-26.23)."""
    detector = getattr(request.app.state, "abuse_detector", None)
    if detector is not None:
        await detector.clear_cooldown(ip_address)

    rl = request.app.state.rate_limiter
    # Clear all IP rate-limit groups (must match EndpointGroup values)
    for group in ("turns", "game_mgmt", "auth", "sse", "health"):
        await rl.clear_key(f"rl:ip:{ip_address}:{group}")

    await audit(
        request,
        admin,
        action="unblock_ip",
        target_type="ip",
        target_id=ip_address,
        reason=body.reason,
    )

    return JSONResponse(content={"ip": ip_address, "status": "unblocked"})
