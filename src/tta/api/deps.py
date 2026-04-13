"""FastAPI dependency injection (plan §1.3, S11 JWT auth)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.errors import AppError
from tta.auth.jwt import TokenError, decode_token, is_token_denied
from tta.config import CURRENT_CONSENT_VERSION, REQUIRED_CONSENT_CATEGORIES
from tta.errors import ErrorCategory
from tta.models.player import Player

if TYPE_CHECKING:
    from redis.asyncio import Redis


async def get_pg(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session from the app-level pool."""
    async with request.app.state.pg() as session:
        yield session


async def get_redis(request: Request) -> Redis:
    """Return the app-level Redis connection."""
    return request.app.state.redis


async def get_current_player(
    request: Request,
    pg: AsyncSession = Depends(get_pg),
    redis: Redis = Depends(get_redis),
) -> Player:
    """Decode JWT access token and return the authenticated Player.

    Token lookup: cookie first, then Authorization: Bearer header.
    Validates token signature, expiry, type, and deny-list.
    Raises 401 if missing/invalid/expired/denied.
    """
    token = _extract_token(request)
    if token is None:
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "AUTH_TOKEN_MISSING",
            "No session token provided.",
        )

    try:
        claims = decode_token(token, expected_type="access")
    except TokenError:
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "AUTH_TOKEN_INVALID",
            "Session token is invalid or expired.",
        ) from None

    jti = claims.get("jti", "")
    if await is_token_denied(redis, jti):
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "AUTH_TOKEN_INVALID",
            "Session token has been revoked.",
        )

    player_id = UUID(claims["sub"])
    player_result = await pg.execute(
        sa.text(
            "SELECT id, handle, status, suspended_reason, created_at, "
            "email, is_anonymous, display_name, role, last_login_at, "
            "consent_version, consent_accepted_at, consent_categories, "
            "age_confirmed_at, consent_ip_hash "
            "FROM players WHERE id = :id"
        ),
        {"id": player_id},
    )
    player_row = player_result.one_or_none()
    if player_row is None:
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "AUTH_TOKEN_INVALID",
            "Player not found.",
        )

    return Player(
        id=player_row.id,
        handle=player_row.handle,
        status=player_row.status,
        suspended_reason=player_row.suspended_reason,
        created_at=player_row.created_at,
        email=player_row.email,
        is_anonymous=player_row.is_anonymous,
        display_name=player_row.display_name,
        role=player_row.role,
        last_login_at=player_row.last_login_at,
        consent_version=player_row.consent_version,
        consent_accepted_at=player_row.consent_accepted_at,
        consent_categories=player_row.consent_categories,
        age_confirmed_at=player_row.age_confirmed_at,
        consent_ip_hash=player_row.consent_ip_hash,
    )


async def require_active_player(
    player: Player = Depends(get_current_player),
) -> Player:
    """Ensure the authenticated player has ``active`` status.

    Raises 403 if the player is suspended (FR-26.07).
    """
    if player.status != "active":
        raise AppError(
            ErrorCategory.FORBIDDEN,
            "PLAYER_SUSPENDED",
            "Your account is suspended.",
            details={"reason": player.suspended_reason},
        )
    return player


async def require_consent(
    player: Player = Depends(require_active_player),
) -> Player:
    """Ensure the player has valid, current consent (S17 FR-17.22).

    Checks consent version, accepted timestamp, required categories,
    and age confirmation. Raises 403 CONSENT_REQUIRED if any fail.
    """
    if (
        player.consent_version is None
        or player.consent_version != CURRENT_CONSENT_VERSION
        or player.consent_accepted_at is None
        or player.age_confirmed_at is None
    ):
        raise AppError(
            ErrorCategory.FORBIDDEN,
            "CONSENT_REQUIRED",
            "You must accept the current consent agreement before playing.",
        )

    # Verify all required categories are accepted
    cats = player.consent_categories
    if not isinstance(cats, dict):
        raise AppError(
            ErrorCategory.FORBIDDEN,
            "CONSENT_REQUIRED",
            "You must accept the current consent agreement before playing.",
        )
    for cat in REQUIRED_CONSENT_CATEGORIES:
        if not cats.get(cat):
            raise AppError(
                ErrorCategory.FORBIDDEN,
                "CONSENT_REQUIRED",
                "You must accept the current consent agreement before playing.",
            )

    return player


def _extract_token(request: Request) -> str | None:
    """Cookie-first, then Authorization: Bearer header."""
    cookie = request.cookies.get("tta_session")
    if cookie:
        return cookie
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None
