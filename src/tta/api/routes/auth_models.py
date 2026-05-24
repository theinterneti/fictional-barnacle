"""Auth route models — request/response schemas.

Extracted from auth.py during code health decomposition.
"""

import re

from pydantic import BaseModel, Field

# FR-11.16: password rules returned in error details
_PASSWORD_MIN = 8
_PASSWORD_MAX = 128
_PASSWORD_RE = re.compile(r"(?=.*[a-zA-Z])(?=.*\d)")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    player_id: str
    is_anonymous: bool


class RefreshRequest(BaseModel):
    refresh_token: str


class UpgradeRequest(BaseModel):
    email: str = Field(
        ..., min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    password: str = Field(..., min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)
    display_name: str | None = Field(None, max_length=50)
    age_13_plus_confirmed: bool = Field(
        ...,
        description="Player confirms they are 13 years or older.",
    )
    consent_version: str = Field(
        ...,
        description="Version of the consent agreement being accepted.",
    )
    consent_categories: dict[str, bool] = Field(
        ...,
        description="Consent categories and acceptance status.",
    )


class LoginRequest(BaseModel):
    email: str = Field(
        ..., min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    password: str = Field(..., min_length=1, max_length=_PASSWORD_MAX)
