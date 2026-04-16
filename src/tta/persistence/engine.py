"""Async SQLAlchemy engine and session factory.

Provides the connection machinery for PostgreSQL via asyncpg.
Usage:
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
"""

from __future__ import annotations

import time

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.observability.metrics import DB_QUERY_DURATION

_TIMING_KEY = "_tta_query_start"
_OP_PREFIXES = ("SELECT", "INSERT", "UPDATE", "DELETE")


def _classify_operation(statement: str) -> str:
    """Extract SQL operation from statement prefix."""
    upper = statement.lstrip().upper()
    for prefix in _OP_PREFIXES:
        if upper.startswith(prefix):
            return prefix.lower()
    return "other"


def _before_cursor_execute(
    conn,
    cursor,
    statement,
    parameters,
    context,
    executemany,
) -> None:
    conn.info[_TIMING_KEY] = time.perf_counter()


def _after_cursor_execute(
    conn,
    cursor,
    statement,
    parameters,
    context,
    executemany,
) -> None:
    start = conn.info.pop(_TIMING_KEY, None)
    if start is not None:
        duration = time.perf_counter() - start
        op = _classify_operation(statement)
        DB_QUERY_DURATION.labels(database="postgresql", operation=op).observe(duration)


def _handle_error(exception_context) -> None:
    """Observe duration for failed queries so the timing stack stays clean."""
    conn = exception_context.connection
    if conn is not None:
        start = conn.info.pop(_TIMING_KEY, None)
        if start is not None:
            duration = time.perf_counter() - start
            stmt = exception_context.statement or ""
            op = _classify_operation(stmt)
            DB_QUERY_DURATION.labels(database="postgresql", operation=op).observe(
                duration
            )


def _ensure_async_url(database_url: str) -> str:
    """Convert ``postgresql://`` to ``postgresql+asyncpg://``."""
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    msg = "database_url must start with postgresql:// or postgresql+asyncpg://"
    raise ValueError(msg)


def build_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 5,
    pool_recycle: int = 300,
    pool_pre_ping: bool = True,
) -> AsyncEngine:
    """Create an async SQLAlchemy engine for PostgreSQL.

    Parameters
    ----------
    pool_timeout:
        Seconds to wait for a connection from the pool (FR-28.07).
    pool_recycle:
        Seconds before idle connections are recycled (FR-28.07).
    pool_pre_ping:
        Issue a lightweight SELECT 1 before handing out a connection.
    """
    url = _ensure_async_url(database_url)
    engine = create_async_engine(
        url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=pool_pre_ping,
    )
    # Auto-instrument all queries — fires even for async sessions
    event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine.sync_engine, "after_cursor_execute", _after_cursor_execute)
    event.listen(engine.sync_engine, "handle_error", _handle_error)
    return engine


def build_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to *engine*."""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
