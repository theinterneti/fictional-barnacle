"""Game-session and game-state domain models."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class GameStatus(StrEnum):
    """Lifecycle status of a game session (plan §6.1, S27 FR-27.01)."""

    created = "created"
    active = "active"
    paused = "paused"
    completed = "completed"
    ended = "ended"
    expired = "expired"
    abandoned = "abandoned"


class GameSession(BaseModel):
    """Top-level container for a single play-through."""

    id: UUID = Field(default_factory=uuid4)
    player_id: UUID
    status: GameStatus = GameStatus.created
    world_seed: dict = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=80)
    summary: str | None = Field(default=None, max_length=200)
    turn_count: int = 0
    needs_recovery: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_played_at: datetime | None = None
    deleted_at: datetime | None = None


class GameState(BaseModel):
    """Snapshot of in-progress game state for a session."""

    session_id: UUID
    turn_number: int = 0
    current_location_id: str = "start"
    narrative_history: list[dict] = Field(default_factory=list)
