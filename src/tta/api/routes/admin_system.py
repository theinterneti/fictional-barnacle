"""Admin system health, metrics, log level, and data purge routes (§3.4).

Extracted from admin.py.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from tta.admin.auth import AdminIdentity, require_admin
from tta.api.routes._admin_helpers import audit
from tta.models.admin import LogLevelBody
from tta.observability.metrics import REGISTRY, generate_latest

router = APIRouter(tags=["admin"])
log = structlog.get_logger(__name__)


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


@router.post("/log-level")
async def set_log_level(
    body: LogLevelBody,
    request: Request,
    _admin: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    """Change runtime log level (S15 FR-15.4)."""
    root = logging.getLogger()
    previous = logging.getLevelName(root.level)
    root.setLevel(body.level)
    log.info(
        "log_level_changed",
        previous=previous,
        new=body.level,
    )
    await audit(
        request,
        _admin,
        action="log_level_changed",
        target_type="system",
        target_id="root_logger",
        reason=f"{previous} → {body.level}",
    )
    return {"data": {"previous": previous, "current": body.level}}


@router.post("/purge")
async def trigger_purge(
    request: Request,
    _admin: AdminIdentity = Depends(require_admin),
    dry_run: bool = Query(False, description="Preview without deleting"),
) -> dict[str, Any]:
    """Manual data purge trigger (S17 FR-17.15)."""
    from tta.privacy.purge import run_purge

    result = await run_purge(
        request.app.state.pg,
        dry_run=dry_run,
    )
    await audit(
        request,
        _admin,
        action="purge_triggered",
        target_type="system",
        target_id="data_purge",
        reason=(
            f"dry_run={dry_run} "
            f"sessions_purged={result.get('sessions_purged', 0)} "
            f"turns_purged={result.get('turns_purged', 0)}"
        ),
    )
    return {"data": result}
