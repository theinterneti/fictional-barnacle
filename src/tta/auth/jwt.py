"""JWT token creation, validation, and deny-list (S11 FR-11.14-19).

Tokens include a ``typ`` claim ("access" or "refresh") to prevent
confusion attacks where a refresh token is used as an access token.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import structlog
from redis.asyncio import Redis

from tta.config import Environment, get_settings

log = structlog.get_logger()

_DENY_PREFIX = "tta:deny:"


class TokenError(Exception):
    """Raised when a token is invalid, expired, or denied."""


# ── Token creation ──────────────────────────────────────────────


def create_access_token(
    player_id: UUID,
    *,
    role: str = "player",
    is_anonymous: bool = True,
    session_family_id: UUID | None = None,
) -> str:
    """Create a signed JWT access token (typ=access)."""
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = settings.anon_access_token_ttl if is_anonymous else settings.access_token_ttl
    claims = {
        "sub": str(player_id),
        "role": role,
        "anon": is_anonymous,
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": secrets.token_hex(16),
    }
    if session_family_id:
        claims["sfid"] = str(session_family_id)
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    player_id: UUID,
    *,
    session_family_id: UUID,
    is_anonymous: bool = True,
) -> tuple[str, str]:
    """Create a signed JWT refresh token (typ=refresh).

    Returns (encoded_token, jti) so the caller can persist the jti.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = (
        settings.anon_refresh_token_ttl if is_anonymous else settings.refresh_token_ttl
    )
    jti = secrets.token_hex(16)
    claims = {
        "sub": str(player_id),
        "typ": "refresh",
        "jti": jti,
        "sfid": str(session_family_id),
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti


# ── Token validation ────────────────────────────────────────────


def decode_token(
    token: str,
    *,
    expected_type: str = "access",
) -> dict:
    """Decode and validate a JWT token.

    Raises ``TokenError`` on invalid/expired/wrong-type tokens.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "typ", "exp", "iat", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError(f"Invalid token: {exc}") from exc

    if claims.get("typ") != expected_type:
        raise TokenError(
            f"Expected token type '{expected_type}', got '{claims.get('typ')}'"
        )

    return claims


# ── Deny-list (Redis-backed) ───────────────────────────────────


async def deny_token(
    redis: Redis | None,
    jti: str,
    expires_at: datetime,
) -> None:
    """Add a token JTI to the deny-list with auto-expiry."""
    remaining = int((expires_at - datetime.now(UTC)).total_seconds())
    if remaining <= 0:
        return  # already expired, no need to deny

    settings = get_settings()
    if redis is None:
        if settings.environment == Environment.PRODUCTION:
            raise RuntimeError("Redis is required for auth deny-list in production")
        log.warning("deny_token_no_redis", jti=jti)
        return

    key = f"{_DENY_PREFIX}{jti}"
    await redis.setex(key, remaining, "1")
    log.info("token_denied", jti=jti, ttl=remaining)


async def is_token_denied(
    redis: Redis | None,
    jti: str,
) -> bool:
    """Check whether a token JTI is on the deny-list."""
    settings = get_settings()
    if redis is None:
        if settings.environment == Environment.PRODUCTION:
            raise RuntimeError("Redis is required for auth deny-list in production")
        return False

    key = f"{_DENY_PREFIX}{jti}"
    return bool(await redis.exists(key))
