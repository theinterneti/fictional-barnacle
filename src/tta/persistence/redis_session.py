"""Redis session-cache — ephemeral game state cache.

Provides ephemeral caching of active game state so the
hot-path avoids a Postgres round-trip on every turn.
"""

from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis

from tta.models.game import GameState

_KEY_PREFIX = "tta:session:"


def _key(session_id: UUID) -> str:
    return f"{_KEY_PREFIX}{session_id}"


async def get_active_session(
    redis: Redis,
    session_id: UUID,
) -> GameState | None:
    """Retrieve cached game state for an active session."""
    raw = await redis.get(_key(session_id))
    if raw is None:
        return None
    return GameState.model_validate_json(raw)


async def set_active_session(
    redis: Redis,
    session_id: UUID,
    state: GameState,
    ttl: int = 3600,
) -> None:
    """Cache game state with a TTL (seconds)."""
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
    await redis.delete(_key(session_id))
