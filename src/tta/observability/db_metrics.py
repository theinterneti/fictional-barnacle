"""Database and Redis observability helpers.

Context managers that record query duration and operation counts
to the Prometheus metrics defined in ``metrics.py``.

Usage::

    async with observe_db_query("postgresql", "get_turn"):
        result = await session.execute(stmt)

    with count_redis_op("get"):
        value = await redis.get(key)
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from tta.observability.metrics import (
    DB_QUERY_DURATION,
    NEO4J_OPERATION_DURATION,
    REDIS_CACHE_READ_DURATION,
    REDIS_CACHE_WRITE_DURATION,
    REDIS_OPERATIONS,
)


@asynccontextmanager
async def observe_db_query(database: str, operation: str) -> AsyncIterator[None]:
    """Time an async DB operation and record to histogram."""
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        DB_QUERY_DURATION.labels(database=database, operation=operation).observe(
            elapsed
        )


@contextmanager
def count_redis_op(operation: str) -> Iterator[None]:
    """Increment the Redis operations counter on exit."""
    try:
        yield
    finally:
        REDIS_OPERATIONS.labels(operation=operation).inc()


@contextmanager
def observe_redis_read(operation: str) -> Iterator[None]:
    """Time a Redis read and record to histogram (AC-12.05)."""
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        REDIS_OPERATIONS.labels(operation=operation).inc()
        REDIS_CACHE_READ_DURATION.labels(operation=operation).observe(elapsed)


@contextmanager
def observe_redis_write(operation: str) -> Iterator[None]:
    """Time a Redis write and record to histogram (AC-12.05)."""
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        REDIS_OPERATIONS.labels(operation=operation).inc()
        REDIS_CACHE_WRITE_DURATION.labels(operation=operation).observe(elapsed)


@asynccontextmanager
async def observe_neo4j_op(operation: str) -> AsyncIterator[None]:
    """Time an async Neo4j operation and record latency (AC-12.08).

    Labels ``status`` as ``"success"`` or ``"error"``::

        async with observe_neo4j_op("apply_world_changes"):
            await neo4j_session.run(...)
    """
    start = time.monotonic()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        elapsed = time.monotonic() - start
        NEO4J_OPERATION_DURATION.labels(operation=operation, status=status).observe(
            elapsed
        )
