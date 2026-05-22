"""Auth route helpers — token management, password validation, cookies.

Extracted from auth.py during code health decomposition.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
import structlog
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.errors import AppError
from tta.api.routes.auth_models import (
    _PASSWORD_MAX,
    _PASSWORD_MIN,
    _PASSWORD_RE,
)
from tta.auth.jwt import (
    create_access_token,
    create_refresh_token,
)
from tta.config import get_settings
from tta.errors import ErrorCategory

log = structlog.get_logger(__name__)


def _validate_password(password: str) -> None:
    """Validate password against FR-11.16 rules."""
    errors: list[str] = []
    if len(password) < _PASSWORD_MIN:
        errors.append(f"Password must be at least {_PASSWORD_MIN} characters.")
    if len(password) > _PASSWORD_MAX:
        errors.append(f"Password must be at most {_PASSWORD_MAX} characters.")
    if not _PASSWORD_RE.search(password):
        errors.append("Password must contain at least one letter and one number.")
    if errors:
        raise AppError(
            ErrorCategory.INPUT_INVALID,
            "PASSWORD_INVALID",
            "Password does not meet requirements.",
            details={"rules": errors},
        )


async def _issue_token_pair(
    pg: AsyncSession,
    player_id: UUID,
    *,
    is_anonymous: bool,
    role: str = "player",
    redis: Redis,
) -> tuple[str, str, int, UUID]:
    """Create auth session + JWT pair.

    Returns (access, refresh, expires_in, session_id).
    """
    settings = get_settings()
    now = datetime.now(UTC)
    session_id = uuid4()

    # Session family TTL matches refresh token
    refresh_ttl = (
        settings.anon_refresh_token_ttl if is_anonymous else settings.refresh_token_ttl
    )
    session_expires = now + timedelta(seconds=refresh_ttl)

    await pg.execute(
        sa.text(
            "INSERT INTO auth_sessions "
            "(id, player_id, is_anonymous, expires_at, last_used_at, created_at) "
            "VALUES (:id, :pid, :anon, :exp, :now, :now)"
        ),
        {
            "id": session_id,
            "pid": player_id,
            "anon": is_anonymous,
            "exp": session_expires,
            "now": now,
        },
    )

    access = create_access_token(
        player_id,
        role=role,
        is_anonymous=is_anonymous,
        session_family_id=session_id,
    )

    refresh, jti = create_refresh_token(
        player_id,
        session_family_id=session_id,
        is_anonymous=is_anonymous,
    )

    # Persist refresh token for rotation tracking (FR-11.20)
    await pg.execute(
        sa.text(
            "INSERT INTO refresh_tokens "
            "(id, session_id, player_id, token_jti, used, expires_at, created_at) "
            "VALUES (:id, :sid, :pid, :jti, false, :exp, :now)"
        ),
        {
            "id": uuid4(),
            "sid": session_id,
            "pid": player_id,
            "jti": jti,
            "exp": now + timedelta(seconds=refresh_ttl),
            "now": now,
        },
    )
    await redis.zadd(
        f"tta:auth:player:{player_id}",
        {str(session_id): session_expires.timestamp()},
    )

    expires_in = (
        settings.anon_access_token_ttl if is_anonymous else settings.access_token_ttl
    )
    return access, refresh, expires_in, session_id


def _set_auth_cookie(response: JSONResponse, access_token: str, ttl: int) -> None:
    """Set the tta_session cookie with the access token."""
    settings = get_settings()
    response.set_cookie(
        key="tta_session",
        value=access_token,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        path="/",
        max_age=ttl,
    )


async def _record_failed_login(redis: Redis, key: str, ttl: int) -> None:
    """Increment the failed-login counter and set expiry (AC-11.09)."""
    await redis.incr(key)
    await redis.expire(key, ttl)
