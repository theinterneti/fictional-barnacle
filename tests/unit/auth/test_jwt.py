"""Tests for JWT token creation, validation, and deny-list."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt as pyjwt
import pytest

from tta.auth.jwt import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    deny_token,
    is_token_denied,
)
from tta.config import Settings

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _override_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide deterministic settings for JWT tests."""
    s = Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        jwt_secret="test-secret-key-minimum-32-bytes-long!!",
        jwt_algorithm="HS256",
        access_token_ttl=3600,
        anon_access_token_ttl=86400,
        refresh_token_ttl=2592000,
        anon_refresh_token_ttl=604800,
    )
    monkeypatch.setattr("tta.auth.jwt.get_settings", lambda: s)


_PID = uuid4()
_SFID = uuid4()


# ── create_access_token ─────────────────────────────────────────


class TestCreateAccessToken:
    def test_creates_valid_jwt(self) -> None:
        token = create_access_token(_PID, role="player", is_anonymous=True)
        claims = pyjwt.decode(
            token,
            "test-secret-key-minimum-32-bytes-long!!",
            algorithms=["HS256"],
        )
        assert claims["sub"] == str(_PID)
        assert claims["role"] == "player"
        assert claims["anon"] is True
        assert claims["typ"] == "access"
        assert "jti" in claims
        assert "iat" in claims
        assert "exp" in claims

    def test_anonymous_uses_longer_ttl(self) -> None:
        token = create_access_token(_PID, is_anonymous=True)
        claims = pyjwt.decode(
            token,
            "test-secret-key-minimum-32-bytes-long!!",
            algorithms=["HS256"],
        )
        ttl = claims["exp"] - claims["iat"]
        assert ttl == 86400  # anon_access_token_ttl

    def test_registered_uses_shorter_ttl(self) -> None:
        token = create_access_token(_PID, is_anonymous=False)
        claims = pyjwt.decode(
            token,
            "test-secret-key-minimum-32-bytes-long!!",
            algorithms=["HS256"],
        )
        ttl = claims["exp"] - claims["iat"]
        assert ttl == 3600  # access_token_ttl

    def test_session_family_id_included_when_set(self) -> None:
        token = create_access_token(_PID, session_family_id=_SFID)
        claims = pyjwt.decode(
            token,
            "test-secret-key-minimum-32-bytes-long!!",
            algorithms=["HS256"],
        )
        assert claims["sfid"] == str(_SFID)

    def test_session_family_id_absent_when_none(self) -> None:
        token = create_access_token(_PID)
        claims = pyjwt.decode(
            token,
            "test-secret-key-minimum-32-bytes-long!!",
            algorithms=["HS256"],
        )
        assert "sfid" not in claims


# ── create_refresh_token ────────────────────────────────────────


class TestCreateRefreshToken:
    def test_returns_token_and_jti(self) -> None:
        token, jti = create_refresh_token(_PID, session_family_id=_SFID)
        assert isinstance(token, str)
        assert isinstance(jti, str)
        assert len(jti) == 32  # token_hex(16)

    def test_refresh_token_has_correct_type(self) -> None:
        token, _ = create_refresh_token(_PID, session_family_id=_SFID)
        claims = pyjwt.decode(
            token,
            "test-secret-key-minimum-32-bytes-long!!",
            algorithms=["HS256"],
        )
        assert claims["typ"] == "refresh"

    def test_anonymous_refresh_ttl(self) -> None:
        token, _ = create_refresh_token(
            _PID, session_family_id=_SFID, is_anonymous=True
        )
        claims = pyjwt.decode(
            token,
            "test-secret-key-minimum-32-bytes-long!!",
            algorithms=["HS256"],
        )
        assert claims["exp"] - claims["iat"] == 604800

    def test_registered_refresh_ttl(self) -> None:
        token, _ = create_refresh_token(
            _PID, session_family_id=_SFID, is_anonymous=False
        )
        claims = pyjwt.decode(
            token,
            "test-secret-key-minimum-32-bytes-long!!",
            algorithms=["HS256"],
        )
        assert claims["exp"] - claims["iat"] == 2592000

    def test_jti_matches_claims(self) -> None:
        token, jti = create_refresh_token(_PID, session_family_id=_SFID)
        claims = pyjwt.decode(
            token,
            "test-secret-key-minimum-32-bytes-long!!",
            algorithms=["HS256"],
        )
        assert claims["jti"] == jti

    def test_contains_session_family_id(self) -> None:
        token, _ = create_refresh_token(_PID, session_family_id=_SFID)
        claims = pyjwt.decode(
            token,
            "test-secret-key-minimum-32-bytes-long!!",
            algorithms=["HS256"],
        )
        assert claims["sfid"] == str(_SFID)


# ── decode_token ────────────────────────────────────────────────


class TestDecodeToken:
    def test_decodes_valid_access_token(self) -> None:
        token = create_access_token(_PID)
        claims = decode_token(token, expected_type="access")
        assert claims["sub"] == str(_PID)

    def test_decodes_valid_refresh_token(self) -> None:
        token, _ = create_refresh_token(_PID, session_family_id=_SFID)
        claims = decode_token(token, expected_type="refresh")
        assert claims["sub"] == str(_PID)

    def test_rejects_expired_token(self) -> None:
        secret = "test-secret-key-minimum-32-bytes-long!!"
        now = datetime.now(UTC) - timedelta(hours=2)
        claims = {
            "sub": str(_PID),
            "typ": "access",
            "iat": now,
            "exp": now + timedelta(seconds=1),
            "jti": "test-jti",
        }
        token = pyjwt.encode(claims, secret, algorithm="HS256")
        with pytest.raises(TokenError, match="expired"):
            decode_token(token)

    def test_rejects_wrong_token_type(self) -> None:
        token = create_access_token(_PID)
        with pytest.raises(TokenError, match="Expected token type 'refresh'"):
            decode_token(token, expected_type="refresh")

    def test_rejects_tampered_token(self) -> None:
        token = create_access_token(_PID)
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(TokenError, match="Invalid token"):
            decode_token(tampered)

    def test_rejects_token_missing_required_claims(self) -> None:
        secret = "test-secret-key-minimum-32-bytes-long!!"
        token = pyjwt.encode({"sub": str(_PID)}, secret, algorithm="HS256")
        with pytest.raises(TokenError, match="Invalid token"):
            decode_token(token)

    def test_confusion_attack_blocked(self) -> None:
        """Refresh token cannot be used where access token is expected."""
        refresh, _ = create_refresh_token(_PID, session_family_id=_SFID)
        with pytest.raises(TokenError, match="Expected token type 'access'"):
            decode_token(refresh, expected_type="access")


# ── deny_token / is_token_denied ────────────────────────────────


class TestDenyList:
    @pytest.mark.anyio
    async def test_deny_and_check(self) -> None:
        redis = AsyncMock()
        redis.exists = AsyncMock(return_value=1)
        jti = "test-jti-001"
        exp = datetime.now(UTC) + timedelta(hours=1)

        await deny_token(redis, jti, exp)
        redis.setex.assert_called_once()

        assert await is_token_denied(redis, jti) is True

    @pytest.mark.anyio
    async def test_not_denied_returns_false(self) -> None:
        redis = AsyncMock()
        redis.exists = AsyncMock(return_value=0)

        assert await is_token_denied(redis, "unknown-jti") is False

    @pytest.mark.anyio
    async def test_already_expired_skips_deny(self) -> None:
        redis = AsyncMock()
        exp = datetime.now(UTC) - timedelta(hours=1)

        await deny_token(redis, "old-jti", exp)
        redis.setex.assert_not_called()

    @pytest.mark.anyio
    async def test_no_redis_non_prod_logs_warning(self) -> None:
        """Without Redis in dev, deny_token warns but doesn't crash."""
        exp = datetime.now(UTC) + timedelta(hours=1)
        await deny_token(None, "some-jti", exp)
        # No exception = pass

    @pytest.mark.anyio
    async def test_no_redis_non_prod_not_denied(self) -> None:
        """Without Redis in dev, is_token_denied returns False."""
        assert await is_token_denied(None, "some-jti") is False
