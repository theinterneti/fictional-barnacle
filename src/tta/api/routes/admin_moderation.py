"""Admin moderation queue routes (§3.5).

Extracted from admin.py — flag listing and review.
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
from tta.models.admin import ReviewRequest

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

    # FR-26.19: suspend_player action must actually suspend the player
    if body.action == "suspend_player":
        import sqlalchemy as sa

        # Look up the player_id from the moderation record
        flags = await recorder.query(limit=1)
        flag_record = next(
            (f for f in flags if str(f.get("moderation_id")) == flag_id), None
        )
        if flag_record and flag_record.get("player_id"):
            pid = flag_record["player_id"]
            async with request.app.state.pg() as session:
                await session.execute(
                    sa.text(
                        "UPDATE players SET status = 'suspended', "
                        "suspended_reason = :reason "
                        "WHERE id = :pid AND status != 'suspended'"
                    ),
                    {"pid": pid, "reason": body.notes},
                )
                await session.commit()
            # Audit entry for the player suspension
            await audit(
                request,
                admin,
                action="suspend_player",
                target_type="player",
                target_id=str(pid),
                reason=body.notes,
            )

    await audit(
        request,
        admin,
        action=f"moderation_review_{body.action}",
        target_type="moderation_flag",
        target_id=flag_id,
        reason=body.notes,
    )

    return JSONResponse(
        content={
            "flag_id": flag_id,
            "action": body.action,
            "new_verdict": new_verdict,
        }
    )
