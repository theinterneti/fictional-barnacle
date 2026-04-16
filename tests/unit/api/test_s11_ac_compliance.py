"""S11 Player Identity & Sessions — Acceptance Criteria compliance tests.

Covers AC-11.01, AC-11.02, AC-11.04, AC-11.10, AC-11.12.

v2 ACs (deferred):
  AC-11.03 — Multi-device login (login endpoint deferred per S11 §14)
  AC-11.05 — Paused game resumable at 29 days (background task + time)
  AC-11.06 — Game expired after 31 days (background task + time)
  AC-11.07 — Expired game resume with welcome back (background task)
  AC-11.08 — Abandoned after 25 hours (background task + time)
  AC-11.09 — Login lockout (login endpoint deferred per S11 §14)
  AC-11.11 — Deleted player cannot login (login endpoint deferred per S11 §14)
  AC-11.13 — Data not retrievable within 72h (async deletion job)
  AC-11.14 — Deleted player_id not reassignable (DB constraint only)
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import (
    get_current_player,
    get_pg,
    get_redis,
    require_anonymous_game_limit,
    require_consent,
)
from tta.config import Settings
from tta.models.player import Player

if TYPE_CHECKING:
    from fastapi import FastAPI

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_ANON_PLAYER = Player(
    id=_PLAYER_ID, handle="anon-test", is_anonymous=True, created_at=_NOW
)
_GAME_ID = uuid4()
_JWT_SECRET = "test-secret-key-minimum-32-bytes-long!!"


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        neo4j_uri="",
        jwt_secret=_JWT_SECRET,
    )


def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Patch all get_settings call sites for auth routes and JWT helpers."""
    settings = _settings()
    monkeypatch.setattr("tta.api.routes.auth.get_settings", lambda: settings)
    monkeypatch.setattr("tta.auth.jwt.get_settings", lambda: settings)
    monkeypatch.setattr("tta.auth.passwords.get_settings", lambda: settings)
    monkeypatch.setattr("tta.api.errors.get_settings", lambda: settings)
    return settings


def _make_result(
    rows: list[dict[str, Any]] | None = None,
    *,
    scalar: Any = None,
) -> MagicMock:
    result = MagicMock()
    if rows is not None:
        objs = [SimpleNamespace(**r) for r in rows]
        result.one_or_none.return_value = objs[0] if objs else None
        result.all.return_value = objs
    else:
        result.one_or_none.return_value = None
        result.all.return_value = []
    if scalar is not None:
        result.scalar_one.return_value = scalar
    return result


def _game_row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": _GAME_ID,
        "player_id": _PLAYER_ID,
        "status": "created",
        "world_seed": "{}",
        "title": None,
        "summary": None,
        "turn_count": 0,
        "needs_recovery": False,
        "summary_generated_at": None,
        "total_cost_usd": 0,
        "cost_warning_sent": False,
        "created_at": _NOW,
        "updated_at": _NOW,
        "last_played_at": None,
        "deleted_at": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def pg() -> AsyncMock:
    conn = AsyncMock()
    conn.begin = MagicMock(return_value=AsyncMock())
    conn.commit = AsyncMock()
    conn.rollback = AsyncMock()
    return conn


@pytest.fixture
def redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def app(pg: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """App with authenticated player (for upgrade, games endpoints)."""
    settings = _patch_settings(monkeypatch)
    a = create_app(settings)
    a.dependency_overrides[get_pg] = lambda: pg
    a.dependency_overrides[get_current_player] = lambda: _ANON_PLAYER
    a.dependency_overrides[require_consent] = lambda: _ANON_PLAYER
    a.dependency_overrides[require_anonymous_game_limit] = lambda: _ANON_PLAYER
    a.dependency_overrides[get_redis] = AsyncMock
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def anon_app(
    pg: AsyncMock, redis: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> FastAPI:
    """App without get_current_player override — anonymous endpoint needs no auth."""
    settings = _patch_settings(monkeypatch)
    a = create_app(settings)
    a.dependency_overrides[get_pg] = lambda: pg
    a.dependency_overrides[get_redis] = lambda: redis
    return a


@pytest.fixture
def anon_client(anon_app: FastAPI) -> TestClient:
    return TestClient(anon_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# AC-11.01: Anonymous auth returns 201 with player_id, access_token, is_anonymous=true
# ---------------------------------------------------------------------------


class TestAC1101AnonymousAuth:
    """AC-11.01: POST /api/v1/auth/anonymous returns 201 with required fields."""

    def test_anonymous_returns_201(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.01: POST /api/v1/auth/anonymous → 201 status code."""
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()
        resp = anon_client.post("/api/v1/auth/anonymous")
        assert resp.status_code == 201, (
            f"AC-11.01: expected 201, got {resp.status_code}: {resp.text}"
        )

    def test_anonymous_response_contains_player_id(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.01: Anonymous response body contains player_id field."""
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()
        resp = anon_client.post("/api/v1/auth/anonymous")
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "player_id" in data, "AC-11.01: player_id missing from response"
        assert data["player_id"] is not None

    def test_anonymous_response_contains_access_token(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.01: Anonymous response body contains access_token field."""
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()
        resp = anon_client.post("/api/v1/auth/anonymous")
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "access_token" in data, "AC-11.01: access_token missing from response"
        assert data["access_token"]

    def test_anonymous_response_is_anonymous_true(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.01: Anonymous response body has is_anonymous=true."""
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()
        resp = anon_client.post("/api/v1/auth/anonymous")
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "is_anonymous" in data, "AC-11.01: is_anonymous missing from response"
        assert data["is_anonymous"] is True, (
            f"AC-11.01: expected is_anonymous=true, got {data['is_anonymous']}"
        )


# ---------------------------------------------------------------------------
# AC-11.02: Upgrade preserves anonymous player_id in token response
# ---------------------------------------------------------------------------


class TestAC1102UpgradePreservesPlayerId:
    """AC-11.02: POST /api/v1/auth/upgrade returns the same player_id."""

    def test_upgrade_preserves_player_id(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.02: Token response player_id matches original anonymous player_id."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),  # SELECT email uniqueness → no existing player
                _make_result(),  # UPDATE players SET email, pw_hash, is_anonymous=false
                _make_result(),  # INSERT auth_sessions (from _issue_token_pair)
                _make_result(),  # INSERT refresh_tokens (from _issue_token_pair)
            ]
        )
        pg.commit = AsyncMock()

        from tta.config import CURRENT_CONSENT_VERSION, REQUIRED_CONSENT_CATEGORIES

        consent_cats = dict.fromkeys(REQUIRED_CONSENT_CATEGORIES, True)
        resp = client.post(
            "/api/v1/auth/upgrade",
            json={
                "email": "tester@example.com",
                "password": "ValidPass1",
                "age_13_plus_confirmed": True,
                "consent_version": CURRENT_CONSENT_VERSION,
                "consent_categories": consent_cats,
            },
        )
        assert resp.status_code == 200, (
            f"AC-11.02: upgrade expected 200, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()["data"]
        assert "player_id" in data, "AC-11.02: player_id missing from upgrade response"
        assert data["player_id"] == str(_PLAYER_ID), (
            f"AC-11.02: player_id changed after upgrade. "
            f"Expected {_PLAYER_ID}, got {data['player_id']}"
        )


# ---------------------------------------------------------------------------
# AC-11.04: First turn submission transitions game created→active
# ---------------------------------------------------------------------------


class TestAC1104CreatedToActiveTransition:
    """AC-11.04: First turn on a 'created' game triggers status→active UPDATE."""

    def test_submit_turn_on_created_game_updates_status_to_active(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.04: 'created' game → submit_turn issues UPDATE status='active'."""
        execute_calls: list[Any] = []

        async def track_execute(stmt: Any, params: Any = None) -> MagicMock:
            sql_str = str(stmt) if hasattr(stmt, "__str__") else ""
            execute_calls.append((sql_str, params))
            call_idx = len(execute_calls) - 1
            if call_idx == 0:
                # _get_owned_game: game in 'created' status
                return _make_result([_game_row(status="created")])
            if call_idx == 1:
                # advisory lock
                return _make_result()
            if call_idx == 2:
                # in-flight check: no processing turns
                return _make_result()
            if call_idx == 3:
                # _get_max_turn_number: 0 turns so far
                return _make_result(scalar=0)
            if call_idx == 4:
                # INSERT turn
                return _make_result()
            # created → active UPDATE or last_played_at UPDATE
            return _make_result()

        pg.execute = track_execute
        pg.commit = AsyncMock()

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "look around"},
        )
        assert resp.status_code == 202, (
            f"AC-11.04: expected 202, got {resp.status_code}: {resp.text}"
        )

        # Find the SQL call that sets status = 'active'
        status_update_calls = [
            (sql, params)
            for sql, params in execute_calls
            if "status = 'active'" in sql or "status='active'" in sql
        ]
        assert status_update_calls, (
            "AC-11.04: No UPDATE with status='active' found in pg.execute calls. "
            f"Calls were: {[sql for sql, _ in execute_calls]}"
        )

    def test_submit_turn_on_active_game_does_not_repeat_status_update(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.04 (negative): Active game does not get a redundant status UPDATE."""
        execute_calls: list[Any] = []

        async def track_execute(stmt: Any, _params: Any = None) -> MagicMock:
            sql_str = str(stmt) if hasattr(stmt, "__str__") else ""
            execute_calls.append(sql_str)
            call_idx = len(execute_calls) - 1
            if call_idx == 0:
                return _make_result([_game_row(status="active", turn_count=3)])
            if call_idx == 1:
                return _make_result()  # advisory lock
            if call_idx == 2:
                return _make_result()  # in-flight check
            if call_idx == 3:
                return _make_result(scalar=3)  # _get_max_turn_number
            if call_idx == 4:
                return _make_result()  # INSERT turn
            return _make_result()

        pg.execute = track_execute
        pg.commit = AsyncMock()

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "look around"},
        )
        assert resp.status_code == 202

        # For an active game, must NOT run the created→active UPDATE
        created_to_active = [
            sql for sql in execute_calls if "status = 'active'" in sql and "SET" in sql
        ]
        assert not created_to_active, (
            "AC-11.04: 'active' game should not trigger a second status UPDATE"
        )


# ---------------------------------------------------------------------------
# AC-11.10: Reused refresh token invalidates entire session family
# ---------------------------------------------------------------------------


class TestAC1110RefreshTokenReuseDetection:
    """AC-11.10: Reusing a refresh token → 401 + session family revocation."""

    def test_reused_refresh_token_returns_401(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.10: POST /api/v1/auth/refresh with used token → 401."""
        jti = str(uuid4())
        player_id = uuid4()
        session_id = uuid4()

        fake_claims = {
            "sub": str(player_id),
            "jti": jti,
            "sfid": str(session_id),
            "type": "refresh",
            "exp": 9999999999,
        }
        token_row = {"id": uuid4(), "used": True}

        with (
            patch("tta.api.routes.auth.decode_token", return_value=fake_claims),
            patch(
                "tta.api.routes.auth.is_token_denied", new=AsyncMock(return_value=False)
            ),
        ):
            pg.execute = AsyncMock(
                side_effect=[
                    _make_result([token_row]),  # SELECT from refresh_tokens
                    _make_result(),  # UPDATE auth_sessions SET revoked_at
                ]
            )
            pg.commit = AsyncMock()

            resp = anon_client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "fake.refresh.token"},
            )

        assert resp.status_code == 401, (
            f"AC-11.10: expected 401 for reused refresh token, "
            f"got {resp.status_code}: {resp.text}"
        )

    def test_reused_refresh_token_issues_revocation_update(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.10: Reuse detection calls UPDATE auth_sessions with revoked_at."""
        jti = str(uuid4())
        player_id = uuid4()
        session_id = uuid4()

        fake_claims = {
            "sub": str(player_id),
            "jti": jti,
            "sfid": str(session_id),
            "type": "refresh",
            "exp": 9999999999,
        }
        token_row = {"id": uuid4(), "used": True}
        executed_sqls: list[str] = []

        async def recording_execute(stmt: Any, _params: Any = None) -> MagicMock:
            sql_str = str(stmt) if hasattr(stmt, "__str__") else ""
            executed_sqls.append(sql_str)
            if len(executed_sqls) == 1:
                return _make_result([token_row])
            return _make_result()

        with (
            patch("tta.api.routes.auth.decode_token", return_value=fake_claims),
            patch(
                "tta.api.routes.auth.is_token_denied", new=AsyncMock(return_value=False)
            ),
        ):
            pg.execute = recording_execute
            pg.commit = AsyncMock()

            anon_client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "fake.refresh.token"},
            )

        # Verify revocation UPDATE was issued
        revocation_calls = [sql for sql in executed_sqls if "revoked_at" in sql]
        assert revocation_calls, (
            "AC-11.10: No UPDATE with 'revoked_at' found. "
            f"SQL calls were: {executed_sqls}"
        )

    def test_reused_refresh_token_error_body_follows_envelope(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.10: 401 response follows standard error envelope."""
        jti = str(uuid4())
        player_id = uuid4()
        session_id = uuid4()

        fake_claims = {
            "sub": str(player_id),
            "jti": jti,
            "sfid": str(session_id),
            "type": "refresh",
            "exp": 9999999999,
        }
        token_row = {"id": uuid4(), "used": True}

        with (
            patch("tta.api.routes.auth.decode_token", return_value=fake_claims),
            patch(
                "tta.api.routes.auth.is_token_denied", new=AsyncMock(return_value=False)
            ),
        ):
            pg.execute = AsyncMock(
                side_effect=[
                    _make_result([token_row]),
                    _make_result(),
                ]
            )
            pg.commit = AsyncMock()

            resp = anon_client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "fake.refresh.token"},
            )

        assert resp.status_code == 401
        body = resp.json()
        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]


# ---------------------------------------------------------------------------
# AC-11.12: No API response ever contains password or password_hash
# ---------------------------------------------------------------------------


class TestAC1112NoPasswordInResponses:
    """AC-11.12: Auth responses never expose password or password_hash fields."""

    _FORBIDDEN_FIELDS = {"password", "password_hash", "passwd", "pw", "pw_hash"}

    def _assert_no_password_fields(self, body: Any, endpoint: str) -> None:
        """Recursively check that no password-like field exists in the response."""
        if isinstance(body, dict):
            for key, value in body.items():
                assert key.lower() not in self._FORBIDDEN_FIELDS, (
                    f"AC-11.12: {endpoint} response contains forbidden field '{key}'"
                )
                self._assert_no_password_fields(value, endpoint)
        elif isinstance(body, (list, tuple)):
            for item in body:
                self._assert_no_password_fields(item, endpoint)

    def test_anonymous_response_has_no_password_fields(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.12: POST /api/v1/auth/anonymous response has no password fields."""
        pg.execute = AsyncMock(return_value=_make_result())
        pg.commit = AsyncMock()
        resp = anon_client.post("/api/v1/auth/anonymous")
        assert resp.status_code == 201
        self._assert_no_password_fields(resp.json(), "/api/v1/auth/anonymous")

    def test_upgrade_response_has_no_password_fields(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.12: POST /api/v1/auth/upgrade response has no password fields."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),  # SELECT email uniqueness check
                _make_result(),  # UPDATE players SET email, pw_hash, is_anonymous=false
                _make_result(),  # INSERT auth_sessions (from _issue_token_pair)
                _make_result(),  # INSERT refresh_tokens (from _issue_token_pair)
            ]
        )
        pg.commit = AsyncMock()

        from tta.config import CURRENT_CONSENT_VERSION, REQUIRED_CONSENT_CATEGORIES

        consent_cats = dict.fromkeys(REQUIRED_CONSENT_CATEGORIES, True)
        resp = client.post(
            "/api/v1/auth/upgrade",
            json={
                "email": "nopw@example.com",
                "password": "ValidPass1",
                "age_13_plus_confirmed": True,
                "consent_version": CURRENT_CONSENT_VERSION,
                "consent_categories": consent_cats,
            },
        )
        assert resp.status_code == 200, f"Upgrade failed: {resp.text}"
        self._assert_no_password_fields(resp.json(), "/api/v1/auth/upgrade")

    def test_refresh_response_has_no_password_fields(
        self, anon_client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-11.12: Successful refresh response contains no password fields."""
        jti = str(uuid4())
        player_id = uuid4()
        session_id = uuid4()

        fake_claims = {
            "sub": str(player_id),
            "jti": jti,
            "sfid": str(session_id),
            "type": "refresh",
            "exp": 9999999999,
        }
        token_row = {"id": uuid4(), "used": False}
        session_row = {"is_anonymous": True, "revoked_at": None}
        player_db_row = {"role": "player", "is_anonymous": True}

        mark_result = MagicMock()
        mark_result.rowcount = 1

        with (
            patch("tta.api.routes.auth.decode_token", return_value=fake_claims),
            patch(
                "tta.api.routes.auth.is_token_denied", new=AsyncMock(return_value=False)
            ),
            patch(
                "tta.api.routes.auth.create_access_token",
                return_value="new.access.token",
            ),
            patch(
                "tta.api.routes.auth.create_refresh_token",
                return_value=("new.refresh.token", str(uuid4())),
            ),
        ):
            pg.execute = AsyncMock(
                side_effect=[
                    _make_result([token_row]),  # SELECT refresh_tokens
                    _make_result([session_row]),  # SELECT auth_sessions
                    _make_result([player_db_row]),  # SELECT players
                    mark_result,  # UPDATE refresh_tokens SET used=true
                    _make_result(),  # INSERT new refresh_token
                    _make_result(),  # UPDATE auth_sessions last_used_at
                ]
            )
            pg.commit = AsyncMock()

            resp = anon_client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "valid.refresh.token"},
            )

        assert resp.status_code == 200, (
            f"AC-11.12: refresh expected 200, got {resp.status_code}: {resp.text}"
        )
        self._assert_no_password_fields(resp.json(), "/api/v1/auth/refresh")
