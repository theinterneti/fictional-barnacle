"""Integration-test fixtures — real service connections.

**Anti-Mock Realism Gate**: every fixture either connects to the real
service or *skips* the test.  We never silently fall back to mocks.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tta.config import Settings


# ---------------------------------------------------------------------------
# Integration Settings (test-services ports, LLM mock, no Neo4j)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def integration_settings(tmp_path_factory) -> Iterator[Settings]:
    """Settings wired to docker-compose.test.yml services.

    Also patches env vars + clears get_settings() cache so that
    route-internal calls to get_settings() return consistent values.
    """
    import os

    from tta.config import Environment, LogLevel, get_settings

    env_overrides = {
        "TTA_DATABASE_URL": "postgresql+asyncpg://tta_test:tta_test@localhost:5433/tta_test",
        "TTA_REDIS_URL": "redis://localhost:6380/1",
        "TTA_NEO4J_URI": "bolt://localhost:7688",
        "TTA_NEO4J_PASSWORD": "",
        "TTA_LLM_MOCK": "true",
        "TTA_ENVIRONMENT": "development",
        "TTA_LOG_LEVEL": "DEBUG",
        "TTA_LOG_FORMAT": "console",
        "TTA_CORS_ORIGINS": '["*"]',
    }
    original_env = {}
    for key, val in env_overrides.items():
        original_env[key] = os.environ.get(key)
        os.environ[key] = val

    get_settings.cache_clear()

    settings = Settings(
        database_url="postgresql+asyncpg://tta_test:tta_test@localhost:5433/tta_test",
        redis_url="redis://localhost:6380/1",
        neo4j_uri="bolt://localhost:7688",
        neo4j_password="",
        llm_mock=True,
        environment=Environment.DEVELOPMENT,
        log_level=LogLevel.DEBUG,
        log_format="console",
        cors_origins=["*"],
    )
    yield settings

    # Restore original env
    for key, orig in original_env.items():
        if orig is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = orig
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def postgres_engine(
    integration_settings: Settings,
) -> AsyncIterator[AsyncEngine]:
    """Async SQLAlchemy engine connected to the test PostgreSQL database.

    Skips the entire session when PostgreSQL is unreachable.
    """
    url = integration_settings.database_url
    engine = create_async_engine(url, echo=False)

    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL unavailable: {exc}")

    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Database migrations (session-scoped, run once)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _run_migrations(
    integration_settings: Settings,
) -> Iterator[None]:
    """Run Alembic migrations via subprocess to avoid event-loop conflicts."""
    import os
    import subprocess

    env = {**os.environ}  # TTA_DATABASE_URL already set by integration_settings
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        import pytest

        combined = (result.stdout + result.stderr).lower()
        # Specific auth-user-missing: FATAL: role "xyz" does not exist
        _auth_user_missing = (
            "fatal" in combined and "role" in combined and "does not exist" in combined
        )
        if (
            any(
                kw in combined
                for kw in (
                    "connection refused",
                    "could not connect",
                    "connect call failed",
                    "connection timed out",
                    "oserror",
                    "econnrefused",
                    "target server attribute",
                    "password authentication",
                    "authentication failed",
                    "invalid password",
                )
            )
            or _auth_user_missing
        ):
            pytest.skip(
                f"PostgreSQL unavailable (alembic exit {result.returncode}): "
                f"{result.stderr[:200]}"
            )
        raise RuntimeError(
            f"Alembic migration failed (rc={result.returncode}):\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}\n"
            f"TTA_DATABASE_URL: {env.get('TTA_DATABASE_URL', 'NOT SET')}"
        )
    yield
    # No downgrade — test DB is disposable (docker-compose.test.yml tmpfs)


# ---------------------------------------------------------------------------
# Table cleanup between tests
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
async def _clean_tables(integration_settings: Settings) -> AsyncIterator[None]:
    """Truncate all data tables between tests for isolation."""
    yield
    import asyncpg

    # Use raw asyncpg to avoid event-loop mismatch with session-scoped engine
    dsn = integration_settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "TRUNCATE turns, world_events, game_sessions, "
            "player_sessions, players CASCADE"
        )
    finally:
        await conn.close()


@pytest.fixture()
def pg_dsn(integration_settings: Settings) -> str:
    """Raw asyncpg-compatible DSN for direct DB access in tests."""
    return integration_settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )


# ---------------------------------------------------------------------------
# Neo4j (S47 — live test instance at bolt://localhost:7688, no-auth)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def neo4j_db(
    integration_settings: Settings,
) -> AsyncIterator[Any]:
    """Session-scoped async Neo4j driver.

    Connects to the test Neo4j at bolt://localhost:7688 (no-auth mode).
    Loads the world_full.cypher fixture once to establish S13 constraints
    and indexes. Skips the entire test session when Neo4j is unreachable.
    """
    import os

    from neo4j import AsyncGraphDatabase

    uri = integration_settings.neo4j_uri or "bolt://localhost:7688"
    driver = AsyncGraphDatabase.driver(
        uri,
        auth=None,
        connection_acquisition_timeout=2.0,
    )

    try:
        await driver.verify_connectivity()
    except Exception as exc:
        await driver.close()
        pytest.skip(f"Neo4j unavailable: {exc}", allow_module_level=True)

    # Load world_full.cypher once per session to create constraints/indexes
    fixture_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "fixtures",
        "neo4j",
        "world_full.cypher",
    )
    with open(fixture_path) as fh:
        cypher = fh.read()

    async with driver.session() as session:
        for stmt in cypher.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("//"):
                await session.run(stmt)

    yield driver
    await driver.close()


@pytest.fixture()
async def neo4j_session(
    neo4j_db: Any,
) -> AsyncIterator[Any]:
    """Function-scoped factory that yields a clean Neo4j session.

    Seeds from empty.cypher by default (no nodes). Tears down by deleting
    all nodes after each test.
    """
    import os

    seed_file = os.path.join(
        os.path.dirname(__file__),
        "..",
        "fixtures",
        "neo4j",
        "empty.cypher",
    )
    with open(seed_file) as fh:
        seed_cypher = fh.read()

    async with neo4j_db.session() as session:
        for stmt in seed_cypher.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("//"):
                await session.run(stmt)

        yield session

        # Teardown — clear all data
        await session.run("MATCH (n) DETACH DELETE n")


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
@pytest.fixture()
async def redis_client(
    integration_settings: Settings,
) -> AsyncIterator[Any]:
    """Async Redis client connected to the test instance.

    Skips the test when Redis is unreachable.
    """
    try:
        from redis.asyncio import from_url
    except ImportError:
        pytest.skip("redis[asyncio] not installed")

    client = from_url(integration_settings.redis_url)

    try:
        await client.ping()  # type: ignore[misc]
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"Redis unavailable: {exc}")

    yield client
    await client.aclose()


# ---------------------------------------------------------------------------
# FastAPI app + httpx AsyncClient
# ---------------------------------------------------------------------------
@pytest.fixture()
async def app(integration_settings: Settings) -> AsyncIterator[Any]:
    """Create a fresh FastAPI app with the integration settings.

    Flushes the Redis test DB first so rate-limit / anti-abuse
    state from prior runs doesn't bleed across tests.
    """
    from tta.api.app import create_app

    # Flush Redis test DB to avoid stale cooldown/rate-limit data
    if integration_settings.redis_url:
        try:
            from redis.asyncio import from_url

            _r = from_url(integration_settings.redis_url)
            await _r.flushdb()  # type: ignore[misc]
            await _r.aclose()
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Redis flushdb failed during test setup", exc_info=True
            )

    application = create_app(integration_settings)
    ctx = application.router.lifespan_context(application)
    await ctx.__aenter__()
    yield application

    # Bound the lifespan shutdown to prevent CI hangs — background tasks
    # (lifecycle_loop, etc.) can race with engine disposal on slow runners.
    try:
        await asyncio.wait_for(ctx.__aexit__(None, None, None), timeout=10.0)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "App lifespan shutdown timed out or errored — continuing"
        )

    # Force-shutdown Langfuse daemon threads to prevent teardown hangs
    try:
        from tta.observability.langfuse import shutdown_langfuse

        shutdown_langfuse()
    except Exception:
        pass


@pytest.fixture()
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    """httpx AsyncClient wired to the app via ASGI transport."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
@pytest.fixture()
async def registered_player(
    client: AsyncClient,
) -> dict[str, str]:
    """Register a player and return {player_id, handle, session_token}."""
    handle = f"test-player-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/players",
        json={
            "handle": handle,
            "age_13_plus_confirmed": True,
            "consent_version": "1.0",
            "consent_categories": {"core_gameplay": True, "llm_processing": True},
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    return {
        "player_id": data["player_id"],
        "handle": data["handle"],
        "session_token": data["session_token"],
    }


@pytest.fixture()
async def auth_headers(registered_player: dict[str, str]) -> dict[str, str]:
    """Authorization headers for the registered player."""
    return {"Authorization": f"Bearer {registered_player['session_token']}"}


@pytest.fixture()
async def auth_client(
    app: Any,
    registered_player: dict[str, str],
) -> AsyncIterator[AsyncClient]:
    """httpx AsyncClient pre-configured with auth cookie."""
    transport = ASGITransport(app=app)
    cookies = {"tta_session": registered_player["session_token"]}
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies=cookies,
    ) as ac:
        yield ac
