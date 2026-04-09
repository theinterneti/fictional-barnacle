"""Health-check endpoints for liveness and readiness probes.

Implements FR-23.23/24/25 — tri-state health with per-service checks.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from tta import __version__

router = APIRouter(prefix="/health", tags=["health"])
log = structlog.get_logger()

# Services whose failure makes the system "unhealthy" (503).
CRITICAL_SERVICES: frozenset[str] = frozenset({"postgres"})


async def _check_postgres(request: Request) -> str:
    """Check PostgreSQL connectivity."""
    async with request.app.state.pg() as session:
        await session.execute(text("SELECT 1"))
    return "ok"


async def _check_neo4j(request: Request) -> str:
    """Check Neo4j connectivity."""
    driver = getattr(request.app.state, "neo4j_driver", None)
    if driver is None:
        return "not_configured"
    await driver.verify_connectivity()
    return "ok"


async def _check_redis(request: Request) -> str:
    """Check Redis connectivity."""
    result = await request.app.state.redis.ping()
    if not result:
        msg = "Redis ping failed"
        raise ConnectionError(msg)
    return "ok"


async def _run_checks(
    request: Request,
) -> dict[str, str]:
    """Run all subsystem checks and return per-service status."""
    checks: dict[str, str] = {}
    for name, check_fn in [
        ("postgres", _check_postgres),
        ("neo4j", _check_neo4j),
        ("redis", _check_redis),
    ]:
        try:
            checks[name] = await check_fn(request)
        except Exception:
            checks[name] = "unavailable"
            log.warning("health_check_failed", service=name, exc_info=True)
    return checks


def _derive_status(checks: dict[str, str]) -> str:
    """Derive aggregate status from per-service checks (FR-23.24).

    - "unhealthy" if any critical service (Postgres) is unavailable
    - "degraded" if any non-critical service is unavailable
    - "healthy" otherwise

    TODO: incorporate circuit-breaker states — a tripped LLM breaker
    should surface as "degraded" even if the LLM health-check hasn't
    failed yet.
    """
    for svc, status in checks.items():
        if status == "unavailable" and svc in CRITICAL_SERVICES:
            return "unhealthy"
    for _svc, status in checks.items():
        if status == "unavailable":
            return "degraded"
    return "healthy"


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get("")
async def health(request: Request) -> JSONResponse:
    """Health endpoint — tri-state status with per-service checks.

    FR-23.23: Returns status, checks, and version.
    FR-23.24: healthy / degraded / unhealthy logic.
    """
    checks = await _run_checks(request)
    status = _derive_status(checks)

    body: dict[str, Any] = {
        "status": status,
        "checks": checks,
        "version": __version__,
    }

    status_code = 503 if status == "unhealthy" else 200
    return JSONResponse(status_code=status_code, content=body)


@router.get("/ready")
async def readiness(request: Request) -> JSONResponse:
    """Readiness probe — 200 only when ALL required services connected.

    FR-23.25: Orchestrators use this for traffic routing.
    """
    checks = await _run_checks(request)

    # "not_configured" is acceptable — service is opt-in.
    all_ok = all(v in ("ok", "not_configured") for v in checks.values())

    status = "ready" if all_ok else "not_ready"
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": status, "checks": checks},
    )
