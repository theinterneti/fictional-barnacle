"""Unit tests for POST /auth/login (AC-11.03, AC-11.09, AC-11.11)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import get_pg, get_redis
from tta.config import Settings

_TEST_SECRET = "test-secret-key-minimum-32-bytes-long!!"
_PID = uuid4()


def _settings():
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        jwt_secret=_TEST_SECRET,
    )


def _make_pg(
    email="player@test.com",
    password_hash="ignored",
    is_anonymous=False,
    role="player",
    deleted_at=None,
):
    pg = AsyncMock()
    pg.execute.return_value = pg

    class MockRow:
        def __init__(self):
            self.id = _PID
            self.email = email
            self.password_hash = password_hash
            self.is_anonymous = is_anonymous
            self.role = role
            self.deleted_at = deleted_at

    row = MockRow()
    pg.one_or_none = MagicMock(return_value=row)
    return pg


def _make_redis(lockout_count=None):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=str(lockout_count) if lockout_count else None)
    redis.ttl = AsyncMock(return_value=900)
    redis.incr = AsyncMock()
    redis.expire = AsyncMock()
    redis.delete = AsyncMock()
    return redis


@pytest.fixture
def client():
    """TestClient with mocked pg/redis and password verification."""
    app = create_app(_settings())
    pg_mock = _make_pg()
    redis_mock = _make_redis()

    app.dependency_overrides[get_pg] = lambda: pg_mock
    app.dependency_overrides[get_redis] = lambda: redis_mock
    app.state._mock_pg = pg_mock
    app.state._mock_redis = redis_mock

    # Mock verify_password globally for all tests in this fixture.
    # Tests that need a different behavior can override.
    with patch("tta.auth.passwords.verify_password", return_value=True):
        yield TestClient(app)


def _login(client, email="player@test.com", password="password123"):
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


# ── success ──────────────────────────────────────────────────────


@pytest.mark.spec("AC-11.03")
def test_login_returns_token_pair(client):
    """AC-11.03: successful login returns access + refresh tokens."""
    response = _login(client)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "Bearer"
    assert data["is_anonymous"] is False


@pytest.mark.spec("AC-11.03")
def test_login_sets_session_cookie(client):
    """AC-11.03: login sets the tta_session cookie."""
    response = _login(client)
    assert response.status_code == 200
    assert "tta_session" in response.cookies


# ── failure cases ────────────────────────────────────────────────


@pytest.mark.spec("AC-11.11")
def test_login_rejects_deleted_player(client):
    """AC-11.11: deleted player cannot log in."""
    app = client.app
    del_pg = _make_pg(deleted_at=datetime(2025, 1, 1, tzinfo=UTC))
    app.dependency_overrides[get_pg] = lambda: del_pg
    response = _login(client)
    assert response.status_code == 403
    assert "ACCOUNT_DELETED" in response.text


@pytest.mark.spec("AC-11.09")
def test_login_lockout_after_5_failures(client):
    """AC-11.09: after 5 failed attempts, subsequent attempts return 429."""
    app = client.app

    # Override verify_password to always fail
    with patch("tta.auth.passwords.verify_password", return_value=False):
        bad_pg = _make_pg()
        app.dependency_overrides[get_pg] = lambda: bad_pg

        for i in range(5):
            response = _login(client, password="wrong")
            assert response.status_code == 401, f"Attempt {i + 1}: expected 401"

    # 6th attempt should be locked
    lock_redis = _make_redis(lockout_count=5)
    app.dependency_overrides[get_redis] = lambda: lock_redis
    response = _login(client)
    assert response.status_code == 429
    assert "LOGIN_LOCKED" in response.text


def test_login_wrong_password_returns_401(client):
    """Wrong password returns 401 with generic message."""
    with patch("tta.auth.passwords.verify_password", return_value=False):
        response = _login(client, password="wrong_password")
    assert response.status_code == 401
    assert "Invalid email" in response.text


def test_login_invalid_email_returns_422(client):
    """Invalid email format returns 422."""
    response = _login(client, email="not-an-email")
    assert response.status_code == 422


def test_login_nonexistent_email_returns_401(client):
    """Nonexistent email returns 401 (no user enumeration)."""
    app = client.app
    no_pg = _make_pg()
    no_pg.one_or_none = MagicMock(return_value=None)
    app.dependency_overrides[get_pg] = lambda: no_pg
    response = _login(client)
    assert response.status_code == 401
    assert "Invalid email" in response.text
