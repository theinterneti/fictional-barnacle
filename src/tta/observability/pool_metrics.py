"""Periodic sampler for connection-pool Prometheus gauges.

Runs as a background ``asyncio.Task`` during the app lifespan, sampling
pool statistics every ``interval`` seconds and writing them to the
pre-declared gauges in :mod:`tta.observability.metrics`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from tta.observability.metrics import (
    NEO4J_POOL_ACTIVE,
    PG_POOL_CHECKED_OUT,
    PG_POOL_OVERFLOW,
    PG_POOL_SIZE,
    REDIS_POOL_ACTIVE,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

log = structlog.get_logger()

_DEFAULT_INTERVAL = 30  # seconds


async def _sample_once(app: FastAPI) -> None:
    """Read pool stats and set gauge values."""
    # -- PostgreSQL (SQLAlchemy AsyncEngine) --
    engine = getattr(app.state, "pg_engine", None)
    if engine is not None:
        pool = engine.pool
        PG_POOL_SIZE.set(pool.size())
        PG_POOL_CHECKED_OUT.set(pool.checkedout())
        PG_POOL_OVERFLOW.set(pool.overflow())

    # -- Redis --
    redis = getattr(app.state, "redis", None)
    if redis is not None:
        pool = getattr(redis, "connection_pool", None)
        if pool is not None:
            # redis-py ConnectionPool tracks _created_connections
            created = getattr(pool, "_created_connections", 0)
            available = getattr(pool, "_available_connections", [])
            active = created - len(available)
            REDIS_POOL_ACTIVE.set(max(active, 0))

    # -- Neo4j --
    driver = getattr(app.state, "neo4j_driver", None)
    if driver is not None:
        # neo4j Python driver exposes pool metrics via
        # get_server_info() but not direct pool counts in all versions.
        # Use _pool if available (internal), otherwise leave at 0.
        pool = getattr(driver, "_pool", None)
        if pool is not None:
            raw = getattr(pool, "in_use_connection_count", None)
            if raw is not None:
                try:
                    val = raw() if callable(raw) else raw  # type: ignore[operator]
                    NEO4J_POOL_ACTIVE.set(int(val))  # type: ignore[arg-type]
                except Exception:
                    NEO4J_POOL_ACTIVE.set(
                        0
                    )  # method signature differs in this driver version


async def _sampler_loop(app: FastAPI, interval: float) -> None:
    """Run the sampler until cancelled."""
    while True:
        try:
            await _sample_once(app)
        except Exception:
            log.warning("pool_metrics_sample_error", exc_info=True)
        await asyncio.sleep(interval)


def start_pool_metrics_sampler(
    app: FastAPI,
    interval: float = _DEFAULT_INTERVAL,
) -> asyncio.Task[None]:
    """Create and return the background sampling task."""
    task = asyncio.create_task(
        _sampler_loop(app, interval),
        name="pool-metrics-sampler",
    )
    log.info("pool_metrics_sampler_started", interval=interval)
    return task
