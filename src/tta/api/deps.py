"""FastAPI dependency injection (plan §1.3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.errors import AppError
from tta.config import CURRENT_CONSENT_VERSION
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
) -> Player:
    """Validate session token and return the authenticated Player.

    Token lookup: cookie first, then Authorization: Bearer header.
    Raises 401 if missing/invalid/expired.
    """
    token = _extract_token(request)
    if token is None:
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "AUTH_TOKEN_MISSING",
            "No session token provided.",
        )

    result = await pg.execute(
        sa.text(
            "SELECT player_id, token, expires_at, created_at "
            "FROM player_sessions WHERE token = :token"
        ),
        {"token": token},
    )
    row = result.one_or_none()
    if row is None or row.expires_at < datetime.now(UTC):
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "AUTH_TOKEN_INVALID",
            "Session token is invalid or expired.",
        )

    player_result = await pg.execute(
        sa.text(
            "SELECT id, handle, status, suspended_reason, created_at, "
            "consent_version, consent_accepted_at, consent_categories, "
            "age_confirmed_at, consent_ip_hash "
            "FROM players WHERE id = :id"
        ),
        {"id": row.player_id},
    )
    player_row = player_result.one_or_none()
    if player_row is None:
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "AUTH_TOKEN_INVALID",
            "Session token is invalid or expired.",
        )

    return Player(
        id=player_row.id,
        handle=player_row.handle,
        status=player_row.status,
        suspended_reason=player_row.suspended_reason,
        created_at=player_row.created_at,
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

    Raises 403 CONSENT_REQUIRED if consent is missing or stale.
    """
    if (
        player.consent_version is None
        or player.consent_version != CURRENT_CONSENT_VERSION
    ):
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
