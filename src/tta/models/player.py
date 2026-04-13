"""Player identity and session models."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Player(BaseModel):
    """Player identity — anonymous or registered."""

    id: UUID = Field(default_factory=uuid4)
    handle: str
    status: str = "active"
    suspended_reason: str | None = None
    deletion_requested_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # S11 auth fields
    email: str | None = None
    password_hash: str | None = None
    is_anonymous: bool = True
    display_name: str = "Adventurer"
    role: str = "player"
    last_login_at: datetime | None = None

    # Consent & age gate (S17 FR-17.22–17.26, FR-17.36–17.39)
    consent_version: str | None = None
    consent_accepted_at: datetime | None = None
    consent_categories: dict[str, bool] | None = None
    age_confirmed_at: datetime | None = None
    consent_ip_hash: str | None = None


class PlayerSession(BaseModel):
    """Legacy opaque token session — deprecated, use JWT auth."""

    id: UUID = Field(default_factory=uuid4)
    player_id: UUID
    token: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuthSession(BaseModel):
    """JWT session family for token rotation (S11 FR-11.20-22)."""

    id: UUID = Field(default_factory=uuid4)
    player_id: UUID
    is_anonymous: bool = True
    revoked_at: datetime | None = None
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_used_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RefreshToken(BaseModel):
    """Refresh token record tied to an auth session family."""

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    player_id: UUID
    token_jti: str
    used: bool = False
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
