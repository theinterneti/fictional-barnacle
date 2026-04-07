"""Integration-test fixtures — real service connections.

**Anti-Mock Realism Gate**: every fixture either connects to the real
service or *skips* the test.  We never silently fall back to mocks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
@pytest.fixture()
async def postgres_engine(
    settings,
) -> AsyncIterator:
    """Async SQLAlchemy engine connected to the test PostgreSQL database.

    Skips the test when PostgreSQL is unreachable.
    """
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
    except ImportError:
        pytest.skip("sqlalchemy[asyncio] not installed")

    url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)

    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL unavailable: {exc}")

    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------
@pytest.fixture()
async def neo4j_driver(
    settings,
) -> AsyncIterator:
    """Async Neo4j driver connected to the test instance.

    Skips the test when Neo4j is unreachable.
    """
    try:
        from neo4j import AsyncGraphDatabase
    except ImportError:
        pytest.skip("neo4j driver not installed")

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    try:
        await driver.verify_connectivity()
    except Exception as exc:
        await driver.close()
        pytest.skip(f"Neo4j unavailable: {exc}")

    yield driver
    await driver.close()


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
@pytest.fixture()
async def redis_client(
    settings,
) -> AsyncIterator:
    """Async Redis client connected to the test instance.

    Skips the test when Redis is unreachable.
    """
    try:
        from redis.asyncio import from_url
    except ImportError:
        pytest.skip("redis[asyncio] not installed")

    client = from_url(settings.redis_url)

    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"Redis unavailable: {exc}")

    yield client
    await client.aclose()
