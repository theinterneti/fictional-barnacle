"""Player identity and session models."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Player(BaseModel):
    """Registered player identity."""

    id: UUID = Field(default_factory=uuid4)
    handle: str
    status: str = "active"
    suspended_reason: str | None = None
    deletion_requested_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Consent & age gate (S17 FR-17.22–17.26, FR-17.36–17.39)
    consent_version: str | None = None
    consent_accepted_at: datetime | None = None
    consent_categories: dict[str, bool] | None = None
    age_confirmed_at: datetime | None = None
    consent_ip_hash: str | None = None


class PlayerSession(BaseModel):
    """Authenticated player session / token record."""

    id: UUID = Field(default_factory=uuid4)
    player_id: UUID
    token: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
