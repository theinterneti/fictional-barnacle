"""Game-session and game-state domain models."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class GameStatus(StrEnum):
    """Lifecycle status of a game session."""

    active = "active"
    paused = "paused"
    completed = "completed"


class GameSession(BaseModel):
    """Top-level container for a single play-through."""

    id: UUID = Field(default_factory=uuid4)
    player_id: UUID
    status: GameStatus = GameStatus.active
    world_seed: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GameState(BaseModel):
    """Snapshot of in-progress game state for a session."""

    session_id: UUID
    turn_number: int = 0
    current_location_id: str = "start"
    narrative_history: list[dict] = Field(default_factory=list)
