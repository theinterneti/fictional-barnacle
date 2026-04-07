"""Player identity and session models."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Player(BaseModel):
    """Registered player identity."""

    id: UUID = Field(default_factory=uuid4)
    handle: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PlayerSession(BaseModel):
    """Authenticated player session / token record."""

    id: UUID = Field(default_factory=uuid4)
    player_id: UUID
    token: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
