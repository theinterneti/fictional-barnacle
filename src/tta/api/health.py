"""Health-check endpoints for liveness and readiness probes."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from tta import __version__

router = APIRouter(prefix="/health", tags=["health"])


# ------------------------------------------------------------------
# Dependency-check stubs — replace with real connection pings when
# persistence layers are wired up.
# ------------------------------------------------------------------


async def _check_postgres() -> str:
    """Check PostgreSQL connectivity."""
    return "ok"


async def _check_neo4j() -> str:
    """Check Neo4j connectivity."""
    return "ok"


async def _check_redis() -> str:
    """Check Redis connectivity."""
    return "ok"


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get("")
async def liveness() -> dict[str, str]:
    """Liveness probe — confirms the process is running."""
    return {"status": "ok", "version": __version__}


@router.get("/ready")
async def readiness() -> JSONResponse:
    """Readiness probe — checks downstream dependencies."""
    checks: dict[str, str] = {}
    all_ok = True

    for name, check_fn in [
        ("postgres", _check_postgres),
        ("neo4j", _check_neo4j),
        ("redis", _check_redis),
    ]:
        try:
            checks[name] = await check_fn()
        except Exception:
            checks[name] = "unavailable"
            all_ok = False

    status = "ready" if all_ok else "not_ready"
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": status, "checks": checks},
    )
