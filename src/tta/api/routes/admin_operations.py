"""Admin operations routes — audit log, consistency check, config, jobs.

Extracted from admin.py (§3.7 + §3.8).
"""

from __future__ import annotations

import json
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from tta.admin.auth import AdminIdentity, require_admin
from tta.api.errors import AppError
from tta.api.routes._admin_helpers import audit
from tta.errors import ErrorCategory
from tta.models.admin import UniverseConfigPatchRequest

router = APIRouter(tags=["admin"])
log = structlog.get_logger(__name__)


# ── §3.7 Audit log ──────────────────────────────────────────────────


@router.get("/audit-log")
async def query_audit_log(
    request: Request,
    admin_id: str | None = Query(None),
    action: str | None = Query(None),
    target_type: str | None = Query(None),
    target_id: str | None = Query(None),
    since: str | None = Query(None, description="ISO 8601 start timestamp"),
    until: str | None = Query(None, description="ISO 8601 end timestamp"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    _admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Paginated, filterable audit log (FR-26.25)."""
    from datetime import datetime

    repo = request.app.state.audit_repo

    from_ts = datetime.fromisoformat(since) if since else None
    to_ts = datetime.fromisoformat(until) if until else None

    entries = await repo.query(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        from_ts=from_ts,
        to_ts=to_ts,
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
    next_cursor = (
        repo.encode_cursor(entries[-1].timestamp, entries[-1].id) if entries else None
    )
    return JSONResponse(content={"entries": items, "next_cursor": next_cursor})


@router.post("/consistency-check")
async def run_consistency_check(
    request: Request,
    sample_limit: int = Query(100, ge=1, le=1000),
    _admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Audit Redis/SQL cache consistency (AC-12.04, EC-12.01)."""
    redis: Redis = request.app.state.redis  # type: ignore[attr-defined]
    sf = request.app.state.pipeline_deps.db_session_factory

    from tta.persistence.consistency import audit_cache_consistency

    async with sf() as pg:
        result = await audit_cache_consistency(redis, pg, sample_limit=sample_limit)

    return JSONResponse(content=result)


# ── §3.8 Universe configuration (S39) ──────────────────────────────


@router.patch("/universes/{universe_id}")
async def patch_universe_config(
    universe_id: UUID,
    body: UniverseConfigPatchRequest,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Merge a partial config patch into a universe (FR-39.09)."""
    from tta.universe.exceptions import (
        CompositionValidationError,
        SeedImmutabilityError,
        UniverseNotFoundError,
    )
    from tta.universe.service import UniverseService

    svc = UniverseService()

    async with request.app.state.pg() as pg:
        try:
            universe = await svc.patch_config(universe_id, body.config, pg)
        except UniverseNotFoundError as exc:
            raise AppError(
                ErrorCategory.NOT_FOUND,
                "universe_not_found",
                str(exc),
            ) from exc
        except SeedImmutabilityError as exc:
            raise AppError(
                ErrorCategory.CONFLICT,
                "seed_immutable",
                str(exc),
            ) from exc
        except CompositionValidationError as exc:
            raise AppError(
                ErrorCategory.SCHEMA_INVALID,
                "composition_invalid",
                exc.message,
            ) from exc

    await audit(
        request,
        admin,
        action="patch_universe_config",
        target_type="universe",
        target_id=str(universe_id),
        reason="config patch applied",
    )

    return JSONResponse(
        content={
            "universe_id": str(universe.id),
            "status": universe.status,
            "config": universe.config,
        }
    )


# ── §3.8 Async job management (S48 — FR-48.05–FR-48.07) ───────────


@router.get("/jobs/dead")
async def list_dead_letter_jobs(
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=200),
) -> JSONResponse:
    """Return up to ``limit`` entries from the dead-letter queue (FR-48.06)."""
    redis: Redis = request.app.state.redis
    raw = await redis.lrange("tta:jobs:dead", 0, limit - 1)  # type: ignore[misc]

    entries = [json.loads(item) for item in raw]
    return JSONResponse(content={"dead_letters": entries, "count": len(entries)})


@router.get("/jobs/{job_id}/status")
async def get_job_status(
    job_id: str,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Return the current status of a job (FR-48.05)."""
    queue = request.app.state.job_queue
    status = await queue.job_status(job_id)
    if status is None:
        raise AppError(
            ErrorCategory.NOT_FOUND,
            "JOB_NOT_FOUND",
            f"Job {job_id!r} not found",
        )
    return JSONResponse(content={"job_id": job_id, "status": str(status)})


@router.post("/jobs/{job_fn_name}/enqueue", status_code=201)
async def enqueue_job(
    job_fn_name: str,
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
) -> JSONResponse:
    """Manually enqueue a job by function name (FR-48.07)."""
    allowed_functions = {
        "gdpr_delete_player",
        "retention_sweep",
        "session_cleanup",
        "game_backfill",
    }
    if job_fn_name not in allowed_functions:
        raise AppError(
            ErrorCategory.INPUT_INVALID,
            "JOB_FUNCTION_NOT_ALLOWED",
            f"Unknown job function {job_fn_name!r}. "
            f"Allowed: {sorted(allowed_functions)}",
        )

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    args = body.get("args", [])
    kwargs = body.get("kwargs", {})

    queue = request.app.state.job_queue
    job_id = await queue.enqueue(job_fn_name, *args, **kwargs)

    await audit(
        request,
        admin,
        action="manual_job_enqueue",
        target_type="job",
        target_id=job_id,
        reason=f"job_fn={job_fn_name}",
    )

    log.info(
        "admin_job_enqueued", job_fn=job_fn_name, job_id=job_id, admin=admin.admin_id
    )
    return JSONResponse(
        status_code=201,
        content={"job_id": job_id, "job_fn": job_fn_name},
    )
