"""Async SQLAlchemy engine and session factory.

Provides the connection machinery for PostgreSQL via asyncpg.
Usage:
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel.ext.asyncio.session import AsyncSession


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
    return create_async_engine(
        url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=pool_pre_ping,
    )


def build_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to *engine*."""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
