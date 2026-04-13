"""Authentication routes for S11 Player Identity & Sessions.

v1 endpoints: anonymous, refresh, logout, upgrade.
Register and login are deferred per S11 §14 Out of Scope.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.deps import get_current_player, get_pg, get_redis
from tta.api.errors import AppError
from tta.auth.jwt import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    deny_token,
    is_token_denied,
)
from tta.auth.passwords import hash_password
from tta.config import get_settings
from tta.errors import ErrorCategory
from tta.models.player import Player

log = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

# FR-11.16: password rules returned in error details
_PASSWORD_MIN = 8
_PASSWORD_MAX = 128
_PASSWORD_RE = re.compile(r"(?=.*[a-zA-Z])(?=.*\d)")


# ── Request / Response schemas ──────────────────────────────────


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


# ── Helpers ─────────────────────────────────────────────────────


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


# ── POST /auth/anonymous (FR-11.10-12) ─────────────────────────


@router.post("/anonymous", status_code=201)
async def create_anonymous(
    pg: AsyncSession = Depends(get_pg),
) -> JSONResponse:
    """Create an anonymous player and issue JWT token pair."""
    player_id = uuid4()
    now = datetime.now(UTC)
    handle = f"anon-{player_id.hex[:8]}"

    # FR-11.10: each call creates a new anonymous player
    await pg.execute(
        sa.text(
            "INSERT INTO players (id, handle, is_anonymous, display_name, created_at) "
            "VALUES (:id, :handle, true, 'Adventurer', :now)"
        ),
        {"id": player_id, "handle": handle, "now": now},
    )

    access, refresh, expires_in, _ = await _issue_token_pair(
        pg, player_id, is_anonymous=True
    )
    await pg.commit()

    body = TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=expires_in,
        player_id=str(player_id),
        is_anonymous=True,
    )
    response = JSONResponse(status_code=201, content={"data": body.model_dump()})
    _set_auth_cookie(response, access, expires_in)
    log.info("anonymous_player_created", player_id=str(player_id))
    return response


# ── POST /auth/refresh (FR-11.20-22) ───────────────────────────


@router.post("/refresh")
async def refresh_tokens(
    body: RefreshRequest,
    pg: AsyncSession = Depends(get_pg),
    redis: Redis = Depends(get_redis),
) -> JSONResponse:
    """Exchange a refresh token for a new token pair (rotation)."""
    # Decode refresh token
    try:
        claims = decode_token(body.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "REFRESH_TOKEN_INVALID",
            str(exc),
        ) from exc

    jti = claims["jti"]
    player_id = UUID(claims["sub"])
    session_family_id = UUID(claims["sfid"])

    # Check deny-list
    if await is_token_denied(redis, jti):
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "REFRESH_TOKEN_INVALID",
            "Token has been revoked.",
        )

    # FR-11.20: single-use check
    row = await pg.execute(
        sa.text(
            "SELECT id, used FROM refresh_tokens "
            "WHERE token_jti = :jti AND session_id = :sid"
        ),
        {"jti": jti, "sid": session_family_id},
    )
    token_record = row.one_or_none()

    if token_record is None:
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "REFRESH_TOKEN_INVALID",
            "Refresh token not found.",
        )

    # FR-11.22: reuse detection — if already used, invalidate entire family
    if token_record.used:
        log.warning(
            "refresh_token_reuse_detected",
            jti=jti,
            session_id=str(session_family_id),
            player_id=str(player_id),
        )
        await pg.execute(
            sa.text(
                "UPDATE auth_sessions SET revoked_at = :now "
                "WHERE id = :sid AND revoked_at IS NULL"
            ),
            {"now": datetime.now(UTC), "sid": session_family_id},
        )
        await pg.commit()
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "SESSION_REVOKED",
            "Suspicious token reuse detected. All sessions revoked.",
        )

    # Check session family is still active
    sess_row = await pg.execute(
        sa.text("SELECT is_anonymous, revoked_at FROM auth_sessions WHERE id = :sid"),
        {"sid": session_family_id},
    )
    sess = sess_row.one_or_none()
    if sess is None or sess.revoked_at is not None:
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "SESSION_REVOKED",
            "Session has been revoked.",
        )

    # Load player for role
    player_row = await pg.execute(
        sa.text("SELECT role, is_anonymous FROM players WHERE id = :id"),
        {"id": player_id},
    )
    player = player_row.one_or_none()
    if player is None:
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "REFRESH_TOKEN_INVALID",
            "Player not found.",
        )

    is_anon = player.is_anonymous

    # FR-11.20: atomically mark old token as used (prevents race)
    mark_result = await pg.execute(
        sa.text(
            "UPDATE refresh_tokens SET used = true WHERE id = :id AND used = false"
        ),
        {"id": token_record.id},
    )
    if mark_result.rowcount == 0:  # type: ignore[union-attr]
        # Another concurrent request already consumed this token —
        # possible replay / theft. Invalidate the whole session family.
        await pg.execute(
            sa.text(
                "UPDATE refresh_tokens SET used = true "
                "WHERE session_family_id = :sfid AND used = false"
            ),
            {"sfid": str(session_family_id)},
        )
        await pg.commit()
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "REFRESH_TOKEN_REUSED",
            "Refresh token already consumed. All tokens in this "
            "session family have been revoked for security.",
        )

    # Issue new pair (FR-11.21: rotation returns new refresh)
    access = create_access_token(
        player_id,
        role=player.role,
        is_anonymous=is_anon,
        session_family_id=session_family_id,
    )
    new_refresh, new_jti = create_refresh_token(
        player_id,
        session_family_id=session_family_id,
        is_anonymous=is_anon,
    )

    settings = get_settings()
    refresh_ttl = (
        settings.anon_refresh_token_ttl if is_anon else settings.refresh_token_ttl
    )
    now = datetime.now(UTC)

    await pg.execute(
        sa.text(
            "INSERT INTO refresh_tokens "
            "(id, session_id, player_id, token_jti, used, expires_at, created_at) "
            "VALUES (:id, :sid, :pid, :jti, false, :exp, :now)"
        ),
        {
            "id": uuid4(),
            "sid": session_family_id,
            "pid": player_id,
            "jti": new_jti,
            "exp": now + timedelta(seconds=refresh_ttl),
            "now": now,
        },
    )

    # Update session last_used_at
    await pg.execute(
        sa.text("UPDATE auth_sessions SET last_used_at = :now WHERE id = :sid"),
        {"now": now, "sid": session_family_id},
    )

    await pg.commit()

    expires_in = (
        settings.anon_access_token_ttl if is_anon else settings.access_token_ttl
    )

    resp_body = TokenResponse(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=expires_in,
        player_id=str(player_id),
        is_anonymous=is_anon,
    )
    response = JSONResponse(content={"data": resp_body.model_dump()})
    _set_auth_cookie(response, access, expires_in)
    return response


# ── POST /auth/logout (FR-11.23) ───────────────────────────────


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    pg: AsyncSession = Depends(get_pg),
    redis: Redis = Depends(get_redis),
) -> Response:
    """Invalidate the current access token and associated session."""
    # Extract and decode access token
    token = request.cookies.get("tta_session")
    auth_header = request.headers.get("Authorization", "")
    if not token and auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if not token:
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "AUTH_TOKEN_MISSING",
            "No token provided.",
        )

    try:
        claims = decode_token(token, expected_type="access")
    except TokenError as exc:
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "AUTH_TOKEN_INVALID",
            str(exc),
        ) from exc

    # FR-11.23: deny the access token
    exp = datetime.fromtimestamp(claims["exp"], tz=UTC)
    await deny_token(redis, claims["jti"], exp)

    # Revoke the session family if present
    sfid = claims.get("sfid")
    if sfid:
        await pg.execute(
            sa.text(
                "UPDATE auth_sessions SET revoked_at = :now "
                "WHERE id = :sid AND revoked_at IS NULL"
            ),
            {"now": datetime.now(UTC), "sid": UUID(sfid)},
        )
        await pg.commit()

    response = Response(status_code=204)
    response.delete_cookie(key="tta_session", path="/")
    log.info("player_logged_out", player_id=claims["sub"])
    return response


# ── POST /auth/upgrade (FR-11.24-28) ───────────────────────────


@router.post("/upgrade")
async def upgrade_anonymous(
    body: UpgradeRequest,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
    redis: Redis = Depends(get_redis),
) -> JSONResponse:
    """Convert an anonymous player to a registered account."""
    # Must be anonymous to upgrade
    if not player.is_anonymous:
        raise AppError(
            ErrorCategory.INPUT_INVALID,
            "ALREADY_REGISTERED",
            "This account is already registered.",
        )

    # FR-11.16: validate password
    _validate_password(body.password)

    # FR-11.28: check email uniqueness
    existing = await pg.execute(
        sa.text("SELECT id FROM players WHERE email = :email"),
        {"email": body.email.lower()},
    )
    if existing.one_or_none() is not None:
        raise AppError(
            ErrorCategory.CONFLICT,
            "EMAIL_ALREADY_REGISTERED",
            "This email is already registered.",
        )

    now = datetime.now(UTC)
    display = body.display_name or player.display_name

    # FR-11.14: bcrypt hash, FR-11.15: no raw password in logs/responses
    pw_hash = hash_password(body.password)

    # FR-11.24: preserve player_id, FR-11.26: set is_anonymous=false
    await pg.execute(
        sa.text(
            "UPDATE players SET "
            "email = :email, password_hash = :pw, is_anonymous = false, "
            "display_name = :dn, last_login_at = :now "
            "WHERE id = :id"
        ),
        {
            "email": body.email.lower(),
            "pw": pw_hash,
            "dn": display,
            "now": now,
            "id": player.id,
        },
    )

    # FR-11.27: issue new token set reflecting upgraded identity
    access, refresh, expires_in, _ = await _issue_token_pair(
        pg, player.id, is_anonymous=False, role=player.role
    )
    await pg.commit()

    resp_body = TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=expires_in,
        player_id=str(player.id),
        is_anonymous=False,
    )
    response = JSONResponse(content={"data": resp_body.model_dump()})
    _set_auth_cookie(response, access, expires_in)
    log.info("anonymous_player_upgraded", player_id=str(player.id))
    return response
