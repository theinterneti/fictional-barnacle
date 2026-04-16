"""Tests for auth routes (S11 Anonymous Auth & Session Lifecycle)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import get_current_player, get_pg, get_redis
from tta.config import Settings
from tta.models.player import Player

if TYPE_CHECKING:
    from fastapi import FastAPI

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
_PID = uuid4()
_SFID = uuid4()
_SECRET = "test-secret-key-minimum-32-bytes-long!!"

_ANON_PLAYER = Player(
    id=_PID,
    handle=f"anon-{_PID.hex[:8]}",
    created_at=_NOW,
    is_anonymous=True,
    display_name="Adventurer",
    role="player",
)

_REG_PLAYER = Player(
    id=_PID,
    handle="registered-user",
    created_at=_NOW,
    is_anonymous=False,
    display_name="Zara",
    role="player",
    email="zara@example.com",
)


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        jwt_secret=_SECRET,
    )


def _make_result(
    rows: list[dict[str, Any]] | None = None,
    *,
    scalar: Any = None,
) -> MagicMock:
    result = MagicMock()
    if rows is not None:
        objs = [SimpleNamespace(**r) for r in rows]
        result.one_or_none.return_value = objs[0] if objs else None
        result.one.return_value = objs[0] if objs else None
        result.all.return_value = objs
    else:
        result.one_or_none.return_value = None
        result.one.return_value = None
        result.all.return_value = []
    if scalar is not None:
        result.scalar_one.return_value = scalar
    return result


@pytest.fixture
def pg() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def app(pg: AsyncMock, redis: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    settings = _settings()
    monkeypatch.setattr("tta.api.routes.auth.get_settings", lambda: settings)
    monkeypatch.setattr("tta.auth.jwt.get_settings", lambda: settings)
    monkeypatch.setattr("tta.auth.passwords.get_settings", lambda: settings)
    a = create_app(settings=settings)

    async def _pg():
        yield pg

    a.dependency_overrides[get_pg] = _pg
    a.dependency_overrides[get_redis] = lambda: redis
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ── POST /auth/anonymous ───────────────────────────────────────


class TestCreateAnonymous:
    def test_creates_anon_player_and_returns_tokens(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/auth/anonymous")
        assert resp.status_code == 201

        data = resp.json()["data"]
        assert data["is_anonymous"] is True
        assert data["token_type"] == "Bearer"
        assert "access_token" in data
        assert "refresh_token" in data
        assert "player_id" in data
        assert data["expires_in"] > 0

    def test_sets_auth_cookie(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/auth/anonymous")
        assert "tta_session" in resp.cookies

    def test_commits_to_database(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()

        client.post("/api/v1/auth/anonymous")
        pg.commit.assert_awaited_once()

    def test_inserts_player_and_session(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()

        client.post("/api/v1/auth/anonymous")
        # 3 inserts: player, auth_session, refresh_token
        assert pg.execute.await_count == 3


# ── POST /auth/refresh ─────────────────────────────────────────


class TestRefreshTokens:
    def _make_valid_refresh(self) -> str:
        """Create a real refresh token for testing."""
        from tta.auth.jwt import create_refresh_token

        token, _ = create_refresh_token(
            _PID, session_family_id=_SFID, is_anonymous=True
        )
        return token

    def test_rotates_tokens_successfully(
        self, client: TestClient, pg: AsyncMock, redis: AsyncMock
    ) -> None:
        token = self._make_valid_refresh()

        # is_token_denied → False (uses redis.exists, not redis.get)
        redis.exists = AsyncMock(return_value=0)

        # Sequence: token lookup, session lookup, player lookup, mark used,
        #           insert new refresh, update session, commit
        token_record = _make_result([{"id": uuid4(), "used": False}])
        session_record = _make_result([{"is_anonymous": True, "revoked_at": None}])
        player_record = _make_result([{"role": "player", "is_anonymous": True}])
        insert_result = _make_result()

        pg.execute = AsyncMock(
            side_effect=[
                token_record,
                session_record,
                player_record,
                insert_result,  # mark used
                insert_result,  # insert new refresh
                insert_result,  # update session
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert resp.status_code == 200

        data = resp.json()["data"]
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["is_anonymous"] is True

    def test_rejects_invalid_token(self, client: TestClient) -> None:
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "garbage"})
        assert resp.status_code == 401

    def test_detects_token_reuse(
        self, client: TestClient, pg: AsyncMock, redis: AsyncMock
    ) -> None:
        """FR-11.22: reused refresh token invalidates entire session."""
        token = self._make_valid_refresh()
        redis.exists = AsyncMock(return_value=0)

        # Token found but already used
        token_record = _make_result([{"id": uuid4(), "used": True}])
        revoke_result = _make_result()

        pg.execute = AsyncMock(side_effect=[token_record, revoke_result])
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert resp.status_code == 401
        assert "SESSION_REVOKED" in resp.text

    def test_rejects_denied_token(
        self, client: TestClient, pg: AsyncMock, redis: AsyncMock
    ) -> None:
        token = self._make_valid_refresh()
        # Token is in deny-list
        redis.exists = AsyncMock(return_value=1)

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert resp.status_code == 401

    def test_rejects_revoked_session(
        self, client: TestClient, pg: AsyncMock, redis: AsyncMock
    ) -> None:
        token = self._make_valid_refresh()
        redis.exists = AsyncMock(return_value=0)

        token_record = _make_result([{"id": uuid4(), "used": False}])
        session_record = _make_result([{"is_anonymous": True, "revoked_at": _NOW}])

        pg.execute = AsyncMock(side_effect=[token_record, session_record])

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert resp.status_code == 401
        assert "SESSION_REVOKED" in resp.text


# ── POST /auth/logout ──────────────────────────────────────────


class TestLogout:
    def _make_valid_access(self) -> str:
        from tta.auth.jwt import create_access_token

        return create_access_token(
            _PID, role="player", is_anonymous=True, session_family_id=_SFID
        )

    def test_logout_succeeds_with_bearer(
        self, client: TestClient, pg: AsyncMock, redis: AsyncMock
    ) -> None:
        token = self._make_valid_access()
        redis.setex = AsyncMock()
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()

        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204

    def test_logout_denies_token_in_redis(
        self, client: TestClient, pg: AsyncMock, redis: AsyncMock
    ) -> None:
        token = self._make_valid_access()
        redis.setex = AsyncMock()
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()

        client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        redis.setex.assert_awaited_once()

    def test_logout_deletes_cookie(
        self, client: TestClient, pg: AsyncMock, redis: AsyncMock
    ) -> None:
        token = self._make_valid_access()
        redis.setex = AsyncMock()
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()

        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Cookie should be expired (deleted)
        cookie_header = resp.headers.get("set-cookie", "")
        assert "tta_session" in cookie_header

    def test_logout_no_token_returns_401(self, client: TestClient) -> None:
        resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 401

    def test_logout_invalid_token_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": "Bearer garbage-token"},
        )
        assert resp.status_code == 401


# ── POST /auth/upgrade ─────────────────────────────────────────


class TestUpgradeAnonymous:
    @pytest.fixture
    def anon_app(
        self,
        pg: AsyncMock,
        redis: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> FastAPI:
        """App where authenticated player is anonymous."""
        settings = _settings()
        monkeypatch.setattr("tta.api.routes.auth.get_settings", lambda: settings)
        monkeypatch.setattr("tta.auth.jwt.get_settings", lambda: settings)
        monkeypatch.setattr("tta.auth.passwords.get_settings", lambda: settings)
        a = create_app(settings=settings)

        async def _pg():
            yield pg

        a.dependency_overrides[get_pg] = _pg
        a.dependency_overrides[get_redis] = lambda: redis
        a.dependency_overrides[get_current_player] = lambda: _ANON_PLAYER
        return a

    @pytest.fixture
    def anon_client(self, anon_app: FastAPI) -> TestClient:
        return TestClient(anon_app)

    def test_upgrades_anonymous_to_registered(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        # email uniqueness check → no conflict
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),  # email check: no rows
                _make_result(),  # update player
                _make_result(),  # insert auth_session
                _make_result(),  # insert refresh_token
            ]
        )
        pg.commit = AsyncMock()

        resp = anon_client.post(
            "/api/v1/auth/upgrade",
            json={
                "email": "test@example.com",
                "password": "Secure1pass",
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": True,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["is_anonymous"] is False
        assert data["player_id"] == str(_PID)

    def test_rejects_duplicate_email(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(return_value=_make_result([{"id": uuid4()}]))

        resp = anon_client.post(
            "/api/v1/auth/upgrade",
            json={
                "email": "taken@example.com",
                "password": "Secure1pass",
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": True,
                },
            },
        )
        assert resp.status_code == 409
        assert "EMAIL_ALREADY_REGISTERED" in resp.text

    def test_rejects_weak_password(self, anon_client: TestClient) -> None:
        resp = anon_client.post(
            "/api/v1/auth/upgrade",
            json={"email": "a@b.com", "password": "short"},
        )
        # pydantic rejects min_length=8
        assert resp.status_code == 422

    def test_rejects_password_no_digit(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        # email check passes
        pg.execute = AsyncMock(return_value=_make_result())

        resp = anon_client.post(
            "/api/v1/auth/upgrade",
            json={
                "email": "a@b.com",
                "password": "NoDigitsHere",
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": True,
                },
            },
        )
        assert resp.status_code == 400
        assert "PASSWORD_INVALID" in resp.text

    def test_registered_player_cannot_upgrade(
        self,
        pg: AsyncMock,
        redis: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Already-registered player gets ALREADY_REGISTERED error."""
        settings = _settings()
        monkeypatch.setattr("tta.api.routes.auth.get_settings", lambda: settings)
        monkeypatch.setattr("tta.auth.jwt.get_settings", lambda: settings)
        monkeypatch.setattr("tta.auth.passwords.get_settings", lambda: settings)
        a = create_app(settings=settings)

        async def _pg_gen():
            yield pg

        a.dependency_overrides[get_pg] = _pg_gen
        a.dependency_overrides[get_redis] = lambda: redis
        a.dependency_overrides[get_current_player] = lambda: _REG_PLAYER

        c = TestClient(a)
        resp = c.post(
            "/api/v1/auth/upgrade",
            json={
                "email": "x@y.com",
                "password": "Secure1pass",
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": True,
                },
            },
        )
        assert resp.status_code == 400
        assert "ALREADY_REGISTERED" in resp.text

    # ── S17 consent rejection scenarios ────────────────────────────

    def test_rejects_upgrade_without_age_confirmation(
        self, anon_client: TestClient
    ) -> None:
        resp = anon_client.post(
            "/api/v1/auth/upgrade",
            json={
                "email": "age-gate@example.com",
                "password": "Secure1pass",
                "age_13_plus_confirmed": False,
                "consent_version": "1.0",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": True,
                },
            },
        )
        assert resp.status_code == 400
        assert "AGE_GATE_FAILED" in resp.text

    def test_rejects_upgrade_wrong_consent_version(
        self, anon_client: TestClient
    ) -> None:
        resp = anon_client.post(
            "/api/v1/auth/upgrade",
            json={
                "email": "version-mismatch@example.com",
                "password": "Secure1pass",
                "age_13_plus_confirmed": True,
                "consent_version": "0.9",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": True,
                },
            },
        )
        assert resp.status_code == 400
        assert "CONSENT_VERSION_MISMATCH" in resp.text

    def test_rejects_upgrade_missing_required_category(
        self, anon_client: TestClient
    ) -> None:
        resp = anon_client.post(
            "/api/v1/auth/upgrade",
            json={
                "email": "missing-consent@example.com",
                "password": "Secure1pass",
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": False,
                },
            },
        )
        assert resp.status_code == 400
        assert "CONSENT_REQUIRED" in resp.text
