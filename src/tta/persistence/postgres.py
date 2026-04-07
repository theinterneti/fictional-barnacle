"""PostgreSQL persistence — async function signatures.

All functions raise ``NotImplementedError`` until Wave 1
provides real database-backed implementations.
"""

from datetime import datetime
from uuid import UUID

from tta.models.game import GameSession, GameStatus
from tta.models.player import Player, PlayerSession
from tta.models.world import WorldEvent

# ── Player persistence ───────────────────────────────────────────


async def create_player(handle: str) -> Player:
    """Register a new player by handle."""
    raise NotImplementedError


async def get_player(player_id: UUID) -> Player | None:
    """Look up a player by primary key."""
    raise NotImplementedError


async def get_player_by_handle(handle: str) -> Player | None:
    """Look up a player by unique handle."""
    raise NotImplementedError


# ── Session persistence ──────────────────────────────────────────


async def create_session(
    player_id: UUID,
    token: str,
    expires_at: datetime,
) -> PlayerSession:
    """Create an authenticated player session."""
    raise NotImplementedError


async def get_session(token: str) -> PlayerSession | None:
    """Retrieve a session by its bearer token."""
    raise NotImplementedError


async def delete_session(token: str) -> None:
    """Revoke / delete a session token."""
    raise NotImplementedError


# ── Game persistence ─────────────────────────────────────────────


async def create_game(
    player_id: UUID,
    world_seed: dict,
) -> GameSession:
    """Start a new game for a player."""
    raise NotImplementedError


async def get_game(game_id: UUID) -> GameSession | None:
    """Fetch a game session by ID."""
    raise NotImplementedError


async def update_game_status(
    game_id: UUID,
    status: GameStatus,
) -> None:
    """Transition a game to a new lifecycle status."""
    raise NotImplementedError


async def list_player_games(
    player_id: UUID,
) -> list[GameSession]:
    """Return all game sessions belonging to a player."""
    raise NotImplementedError


# ── Turn persistence ─────────────────────────────────────────────


async def create_turn(
    session_id: UUID,
    turn_number: int,
    player_input: str,
    idempotency_key: UUID | None = None,
) -> dict:
    """Record the start of a new turn."""
    raise NotImplementedError


async def get_turn(turn_id: UUID) -> dict | None:
    """Fetch a turn record by ID."""
    raise NotImplementedError


async def complete_turn(
    turn_id: UUID,
    narrative_output: str,
    model_used: str,
    latency_ms: float,
    token_count: dict,
) -> None:
    """Mark a turn as complete with its results."""
    raise NotImplementedError


async def get_processing_turn(
    session_id: UUID,
) -> dict | None:
    """Find the currently-processing turn for a session."""
    raise NotImplementedError


async def get_turn_by_idempotency_key(
    session_id: UUID,
    key: UUID,
) -> dict | None:
    """Look up a turn by its idempotency key."""
    raise NotImplementedError


# ── World-event persistence ──────────────────────────────────────


async def create_world_event(
    session_id: UUID,
    turn_id: UUID,
    event_type: str,
    entity_id: str,
    payload: dict,
) -> WorldEvent:
    """Persist a world-state mutation event."""
    raise NotImplementedError


async def get_recent_events(
    session_id: UUID,
    limit: int = 5,
) -> list[WorldEvent]:
    """Return the most recent world events for a session."""
    raise NotImplementedError
