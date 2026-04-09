"""Protocol definitions for persistence repositories.

These typing.Protocol classes allow dependency injection and
make it easy to swap real implementations for test doubles.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from tta.models.game import GameSession, GameState, GameStatus
from tta.models.player import Player, PlayerSession
from tta.models.world import WorldEvent


class PlayerRepository(Protocol):
    """Contract for player persistence operations."""

    async def create_player(self, handle: str) -> Player: ...

    async def get_player(self, player_id: UUID) -> Player | None: ...

    async def get_player_by_handle(self, handle: str) -> Player | None: ...


class SessionRepository(Protocol):
    """Contract for player-session persistence."""

    async def create_session(
        self,
        player_id: UUID,
        token: str,
        expires_at: datetime,
    ) -> PlayerSession: ...

    async def get_session(self, token: str) -> PlayerSession | None: ...

    async def delete_session(self, token: str) -> None: ...


class GameRepository(Protocol):
    """Contract for game-session persistence."""

    async def create_game(self, player_id: UUID, world_seed: dict) -> GameSession: ...

    async def get_game(self, game_id: UUID) -> GameSession | None: ...

    async def update_game_status(self, game_id: UUID, status: GameStatus) -> None: ...

    async def list_player_games(self, player_id: UUID) -> list[GameSession]: ...

    async def soft_delete(self, game_id: UUID) -> None: ...

    async def count_active_games(self, player_id: UUID) -> int: ...


class TurnRepository(Protocol):
    """Contract for turn persistence."""

    async def create_turn(
        self,
        session_id: UUID,
        turn_number: int,
        player_input: str,
        idempotency_key: UUID | None = None,
    ) -> dict: ...

    async def get_turn(self, turn_id: UUID) -> dict | None: ...

    async def complete_turn(
        self,
        turn_id: UUID,
        narrative_output: str,
        model_used: str,
        latency_ms: float,
        token_count: dict,
    ) -> None: ...

    async def update_status(self, turn_id: UUID, status: str) -> None: ...

    async def fail_turn(
        self,
        turn_id: UUID,
        narrative_output: str | None = None,
    ) -> None:
        """Mark a turn as failed, optionally preserving partial narrative."""
        ...

    async def get_processing_turn(self, session_id: UUID) -> dict | None: ...

    async def get_turn_by_idempotency_key(
        self, session_id: UUID, key: UUID
    ) -> dict | None: ...


class WorldEventRepository(Protocol):
    """Contract for world-event persistence."""

    async def create_world_event(
        self,
        session_id: UUID,
        turn_id: UUID,
        event_type: str,
        entity_id: str,
        payload: dict,
    ) -> WorldEvent: ...

    async def get_recent_events(
        self, session_id: UUID, limit: int = 5
    ) -> list[WorldEvent]: ...


class SessionCacheRepository(Protocol):
    """Contract for Redis session-cache operations."""

    async def get_active_session(self, session_id: UUID) -> GameState | None: ...

    async def set_active_session(
        self, session_id: UUID, state: GameState, ttl: int = 3600
    ) -> None: ...

    async def delete_active_session(self, session_id: UUID) -> None: ...
