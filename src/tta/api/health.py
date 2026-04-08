"""Health-check endpoints for liveness and readiness probes."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from tta import __version__

router = APIRouter(prefix="/health", tags=["health"])


async def _check_postgres(request: Request) -> str:
    """Check PostgreSQL connectivity."""
    async with request.app.state.pg() as session:
        from sqlalchemy import text

        await session.execute(text("SELECT 1"))
    return "ok"


async def _check_neo4j(request: Request) -> str:
    """Check Neo4j connectivity (stub until Neo4j wired)."""
    return "ok"


async def _check_redis(request: Request) -> str:
    """Check Redis connectivity."""
    result = await request.app.state.redis.ping()
    if not result:
        msg = "Redis ping failed"
        raise ConnectionError(msg)
    return "ok"


@router.get("")
async def liveness() -> dict[str, str]:
    """Liveness probe — confirms the process is running."""
    return {"status": "ok", "version": __version__}


@router.get("/ready")
async def readiness(request: Request) -> JSONResponse:
    """Readiness probe — checks downstream dependencies."""
    checks: dict[str, str] = {}
    all_ok = True

    for name, check_fn in [
        ("postgres", _check_postgres),
        ("neo4j", _check_neo4j),
        ("redis", _check_redis),
    ]:
        try:
            checks[name] = await check_fn(request)
        except Exception:
            checks[name] = "unavailable"
            all_ok = False

    status = "ready" if all_ok else "not_ready"
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": status, "checks": checks},
    )
