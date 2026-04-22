"""Universe-domain Pydantic models (S29, S30, S31, S33)."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Universe(BaseModel):
    """A persistent simulation container owned by a player (S29)."""

    id: UUID = Field(default_factory=uuid4)
    owner_id: UUID
    name: str
    description: str = ""
    status: Literal["dormant", "created", "active", "paused", "archived"] = "dormant"
    config: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Actor(BaseModel):
    """A player's persistent identity within TTA (S31).

    actor_id is distinct from player_id — one player may have many actors,
    but each actor has exactly one owning player.
    """

    id: UUID = Field(default_factory=uuid4)
    player_id: UUID
    display_name: str
    avatar_config: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CharacterState(BaseModel):
    """Per-(actor, universe) mutable character data (S31 AC-31.01–31.05).

    Created lazily on first access within a universe; UNIQUE(actor_id, universe_id).
    """

    id: UUID = Field(default_factory=uuid4)
    actor_id: UUID
    universe_id: UUID
    traits: list = Field(default_factory=list)
    inventory: list = Field(default_factory=list)
    conditions: list = Field(default_factory=list)
    reputation: dict = Field(default_factory=dict)
    relationships: dict = Field(default_factory=dict)
    custom: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UniverseSnapshot(BaseModel):
    """Point-in-time snapshot of universe state (S29, S33)."""

    id: UUID = Field(default_factory=uuid4)
    universe_id: UUID
    session_id: UUID | None = None
    turn_count: int = 0
    snapshot: dict = Field(default_factory=dict)
    snapshot_type: Literal["session_end", "manual", "admin"] = "session_end"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
