"""Redis session-cache — async function signatures.

Provides ephemeral caching of active game state so the
hot-path avoids a Postgres round-trip on every turn.

All functions raise ``NotImplementedError`` until Wave 1.
"""

from uuid import UUID

from tta.models.game import GameState


async def get_active_session(
    session_id: UUID,
) -> GameState | None:
    """Retrieve cached game state for an active session."""
    raise NotImplementedError


async def set_active_session(
    session_id: UUID,
    state: GameState,
    ttl: int = 3600,
) -> None:
    """Cache game state with a TTL (seconds)."""
    raise NotImplementedError


async def delete_active_session(
    session_id: UUID,
) -> None:
    """Evict cached game state for a session."""
    raise NotImplementedError
