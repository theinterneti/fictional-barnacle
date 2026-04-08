"""FastAPI dependency injection (plan §1.3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.errors import AppError
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
        raise AppError(401, "AUTH_TOKEN_MISSING", "No session token provided.")

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
            401, "AUTH_TOKEN_INVALID", "Session token is invalid or expired."
        )

    player_result = await pg.execute(
        sa.text("SELECT id, handle, created_at FROM players WHERE id = :id"),
        {"id": row.player_id},
    )
    player_row = player_result.one_or_none()
    if player_row is None:
        raise AppError(
            401, "AUTH_TOKEN_INVALID", "Session token is invalid or expired."
        )

    return Player(
        id=player_row.id,
        handle=player_row.handle,
        created_at=player_row.created_at,
    )


def _extract_token(request: Request) -> str | None:
    """Cookie-first, then Authorization: Bearer header."""
    cookie = request.cookies.get("tta_session")
    if cookie:
        return cookie
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None
