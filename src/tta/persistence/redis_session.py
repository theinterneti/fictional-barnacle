"""Redis session-cache — ephemeral game state cache.

Provides ephemeral caching of active game state so the
hot-path avoids a Postgres round-trip on every turn.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from redis.asyncio import Redis

from tta.models.game import GameState
from tta.observability.db_metrics import observe_redis_read, observe_redis_write
from tta.observability.metrics import (
    CACHE_RECONSTRUCTION_DURATION,
    CACHE_RECONSTRUCTION_TOTAL,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession

    from tta.world.neo4j_service import Neo4jWorldService

log = structlog.get_logger()

_KEY_PREFIX = "tta:session:"
_DEFAULT_TTL = 3600

# SSE key templates — must stay in sync with src/tta/api/sse.py
_SSE_BUFFER_KEY = "tta:sse_buffer:{game_id}"
_SSE_COUNTER_KEY = "tta:sse_counter:{game_id}"


def _key(session_id: UUID) -> str:
    return f"{_KEY_PREFIX}{session_id}"


async def get_active_session(
    redis: Redis,
    session_id: UUID,
) -> GameState | None:
    """Retrieve cached game state for an active session."""
    with observe_redis_read("get"):
        raw = await redis.get(_key(session_id))
    if raw is None:
        return None
    return GameState.model_validate_json(raw)


LoadFromSQL = Callable[[UUID], Awaitable[GameState | None]]


async def get_or_reconstruct_session(
    redis: Redis,
    session_id: UUID,
    *,
    load_from_sql: LoadFromSQL | None = None,
    neo4j_service: Neo4jWorldService | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> GameState | None:
    """Get session from cache, falling back to SQL reconstruction.

    ``load_from_sql`` should be an async callable
    ``(UUID) -> GameState | None`` (typically bound from a postgres repo).
    When cache misses and ``load_from_sql`` is provided, the session is
    loaded from SQL, re-warmed into Redis, and a reconstruction counter
    is incremented.

    If ``neo4j_service`` and ``session_factory`` are both provided, the
    Neo4j world graph is also reconstructed from ``world_events`` (AC-12.06).

    Returns *None* only when the session is genuinely missing.
    """
    state = await get_active_session(redis, session_id)
    if state is not None:
        return state

    if load_from_sql is None:
        return None

    start = time.monotonic()
    state = await load_from_sql(session_id)
    elapsed = time.monotonic() - start
    CACHE_RECONSTRUCTION_DURATION.observe(elapsed)

    if state is None:
        return None

    CACHE_RECONSTRUCTION_TOTAL.inc()
    log.warning(
        "cache_reconstruction",
        session_id=str(session_id),
        source="sql",
        elapsed_s=round(elapsed, 4),
        note="degraded: SQL-only, world graph state not included",
    )

    await set_active_session(redis, session_id, state)

    if neo4j_service is not None and session_factory is not None:
        log.info("world_graph_reconstruction_attempted", session_id=str(session_id))
        try:
            await neo4j_service.reconstruct_world_graph(session_id, session_factory)
        except Exception:
            log.warning(
                "world_graph_reconstruction_failed",
                session_id=str(session_id),
                exc_info=True,
                note="degraded: Neo4j graph state not available",
            )

    return state


async def set_active_session(
    redis: Redis,
    session_id: UUID,
    state: GameState,
    ttl: int = _DEFAULT_TTL,
) -> None:
    """Cache game state with a TTL (seconds)."""
    with observe_redis_write("set"):
        await redis.set(
            _key(session_id),
            state.model_dump_json(),
            ex=ttl,
        )


async def delete_active_session(
    redis: Redis,
    session_id: UUID,
) -> None:
    """Evict cached game state for a session."""
    with observe_redis_write("delete"):
        await redis.delete(_key(session_id))


async def evict_game_state(redis: Redis, game_id: UUID) -> None:
    """Delete all Redis state for a game: session cache + SSE replay keys.

    Used when a game is forcibly terminated so cached state and active SSE
    streams are cleaned up atomically (FR-26.12).
    """
    await redis.delete(
        _key(game_id),
        _SSE_BUFFER_KEY.format(game_id=game_id),
        _SSE_COUNTER_KEY.format(game_id=game_id),
    )
