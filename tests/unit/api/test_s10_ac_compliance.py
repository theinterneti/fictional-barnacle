"""S10 API & Streaming — Acceptance Criteria compliance tests.

Covers AC-10.01, AC-10.03, AC-10.07, AC-10.09, AC-10.10, AC-10.11, AC-10.12.

v2 ACs (deferred, require integration infra):
  AC-10.02 — OpenAPI spec validation (openapi-spec-validator tooling)
  AC-10.04 — SSE chunk delivery within 2 s (real-time timing, integration only)
  AC-10.05 — Reconnect / missed events within 30 s (Redis pub/sub)
  AC-10.06 — Keepalive heartbeats every 15 s (SSE middleware, integration only)
  AC-10.08 — Rate-limit headers on every authenticated response (middleware)
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import (
    get_current_player,
    get_pg,
    get_redis,
    require_anonymous_game_limit,
    require_consent,
)
from tta.api.errors import AppError, app_error_handler, unhandled_error_handler
from tta.config import Environment, Settings
from tta.errors import ErrorCategory
from tta.models.player import Player

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_OTHER_PLAYER_ID = uuid4()
_PLAYER = Player(id=_PLAYER_ID, handle="ACTester", created_at=_NOW)
_GAME_ID = uuid4()


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        neo4j_uri="",
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
        "status": "active",
        "world_seed": "{}",
        "title": None,
        "summary": None,
        "turn_count": 1,
        "needs_recovery": False,
        "summary_generated_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "last_played_at": _NOW,
        "deleted_at": None,
        "template_id": "enchanted-forest",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def pg() -> AsyncMock:
    conn = AsyncMock()
    conn.begin = MagicMock(return_value=AsyncMock())
    conn.commit = AsyncMock()
    conn.rollback = AsyncMock()
    return conn


@pytest.fixture()
def app(pg: AsyncMock) -> FastAPI:
    settings = _settings()
    a = create_app(settings)
    a.dependency_overrides[get_pg] = lambda: pg
    a.dependency_overrides[get_current_player] = lambda: _PLAYER
    a.dependency_overrides[require_consent] = lambda: _PLAYER
    a.dependency_overrides[require_anonymous_game_limit] = lambda: _PLAYER
    return a


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Minimal error-handler app for low-level error shape tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def err_app() -> FastAPI:
    """Minimal FastAPI with error handlers for AC-10.09/AC-10.10 checks."""
    a = FastAPI()
    a.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    a.add_exception_handler(Exception, unhandled_error_handler)  # type: ignore[arg-type]

    @a.get("/conflict")
    async def conflict_endpoint(request: Request) -> None:
        request.state.request_id = "req-s10-test"
        raise AppError(ErrorCategory.CONFLICT, "HANDLE_TAKEN", "Handle already taken.")

    @a.get("/boom")
    async def boom_endpoint(request: Request) -> None:
        request.state.request_id = "req-s10-test"
        msg = "internal detail: /home/deploy/secret.py line 42"
        raise RuntimeError(msg)

    @a.get("/rate-limit")
    async def rate_limit_endpoint(request: Request) -> None:
        request.state.request_id = "req-s10-test"
        raise AppError(
            ErrorCategory.RATE_LIMITED,
            "RATE_LIMITED",
            "Slow down.",
            retry_after_seconds=30,
        )

    return a


@pytest.fixture()
def err_client(err_app: FastAPI) -> TestClient:
    return TestClient(err_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# AC-10.01: Full game flow uses only documented API endpoints
# ---------------------------------------------------------------------------


class TestAC1001GameplayFlow:
    """AC-10.01: Player can create account, start game, submit turn via API."""

    def test_full_flow_create_and_submit_turn(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-10.01: create game → submit turn → returns stream URL.

        This is the documented happy-path flow using only public API endpoints:
          POST /api/v1/games  →  201 with game_id
          POST /api/v1/games/{id}/turns  →  202 with stream_url
        """
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),  # count active games
                _make_result(),  # INSERT game
                _make_result([_game_row()]),  # _get_owned_game (for turn)
                _make_result(),  # advisory lock
                _make_result(),  # in-flight check
                _make_result(scalar=0),  # max turn number
                _make_result(),  # INSERT turn
                _make_result(),  # UPDATE last_played_at
            ]
        )
        pg.commit = AsyncMock()

        # Step 1: create game
        create_resp = client.post("/api/v1/games", json={})
        assert create_resp.status_code == 201
        game_id = create_resp.json()["data"]["game_id"]
        assert game_id is not None

        # Step 2: submit a narrative turn
        turn_resp = client.post(
            f"/api/v1/games/{game_id}/turns",
            json={"input": "look around"},
        )
        assert turn_resp.status_code == 202
        data = turn_resp.json()["data"]
        assert "turn_id" in data
        assert "stream_url" in data


# ---------------------------------------------------------------------------
# AC-10.03: Every endpoint returns documented error shape
# ---------------------------------------------------------------------------


class TestAC1003ErrorShape:
    """AC-10.03: Error responses follow the standard envelope."""

    def test_app_error_returns_standard_envelope(self, err_client: TestClient) -> None:
        """AC-10.03: AppError → {error: {code, message, correlation_id}}."""
        resp = err_client.get("/conflict")
        assert resp.status_code == 409
        body = resp.json()
        assert "error" in body
        err = body["error"]
        assert "code" in err
        assert "message" in err
        assert "correlation_id" in err
        assert err["code"] == "HANDLE_TAKEN"

    def test_unhandled_error_returns_standard_envelope(
        self, err_client: TestClient
    ) -> None:
        """AC-10.03: Unhandled exceptions still produce standard envelope."""
        mock_settings = type("S", (), {"environment": Environment.PRODUCTION})()
        with patch("tta.api.errors.get_settings", return_value=mock_settings):
            resp = err_client.get("/boom")
        assert resp.status_code == 500
        body = resp.json()
        assert "error" in body
        err = body["error"]
        assert err["code"] == "INTERNAL_ERROR"
        assert "message" in err
        assert "correlation_id" in err

    def test_404_game_not_found_returns_standard_envelope(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-10.03: 404 from game lookup follows error envelope."""
        pg.execute = AsyncMock(return_value=_make_result())  # no row
        resp = client.get(f"/api/v1/games/{uuid4()}")
        assert resp.status_code == 404
        body = resp.json()
        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]


# ---------------------------------------------------------------------------
# AC-10.07: Rate limit → 429 + Retry-After
# ---------------------------------------------------------------------------


class TestAC1007RateLimit:
    """AC-10.07: Exceeding rate limit returns 429 with Retry-After header."""

    def test_429_with_retry_after_header(self, err_client: TestClient) -> None:
        """AC-10.07: RATE_LIMITED error → HTTP 429 + Retry-After header."""
        resp = err_client.get("/rate-limit")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) == 30

    def test_429_body_contains_retry_after_seconds(
        self, err_client: TestClient
    ) -> None:
        """AC-10.07: 429 body includes retry_after_seconds field."""
        resp = err_client.get("/rate-limit")
        body = resp.json()
        assert body["error"]["retry_after_seconds"] == 30

    def test_rate_limited_error_code(self, err_client: TestClient) -> None:
        """AC-10.07: 429 body includes RATE_LIMITED error code."""
        resp = err_client.get("/rate-limit")
        assert resp.json()["error"]["code"] == "RATE_LIMITED"


# ---------------------------------------------------------------------------
# AC-10.09: No stack traces, file paths, or internal details in responses
# ---------------------------------------------------------------------------


class TestAC1009NoInternalDetails:
    """AC-10.09: API responses never expose stack traces or file paths."""

    def test_unhandled_error_hides_details_in_production(
        self, err_client: TestClient
    ) -> None:
        """AC-10.09: Production 500 does not leak file paths or stack traces."""
        mock_settings = type("S", (), {"environment": Environment.PRODUCTION})()
        with patch("tta.api.errors.get_settings", return_value=mock_settings):
            resp = err_client.get("/boom")
        assert resp.status_code == 500
        body = resp.json()
        # No details field in production
        assert body["error"]["details"] is None
        # Response body must not contain internal paths or traceback strings
        body_text = resp.text
        assert "Traceback" not in body_text
        assert "/home/deploy" not in body_text
        assert "secret.py" not in body_text
        assert "internal detail" not in body_text

    def test_app_error_details_are_structured_not_tracebacks(
        self, err_client: TestClient
    ) -> None:
        """AC-10.09: AppError details are structured data, never raw tracebacks."""
        resp = err_client.get("/conflict")
        assert resp.status_code == 409
        body_text = resp.text
        assert "Traceback" not in body_text
        assert "File " not in body_text
        assert ".py" not in body_text


# ---------------------------------------------------------------------------
# AC-10.10: Every error response includes a request_id / correlation_id
# ---------------------------------------------------------------------------


class TestAC1010RequestId:
    """AC-10.10: Every error response includes a correlation_id (request_id)."""

    def test_app_error_includes_correlation_id(self, err_client: TestClient) -> None:
        """AC-10.10: AppError response includes correlation_id in error envelope."""
        resp = err_client.get("/conflict")
        assert resp.status_code == 409
        err = resp.json()["error"]
        assert "correlation_id" in err
        assert err["correlation_id"] is not None

    def test_unhandled_error_includes_correlation_id(
        self, err_client: TestClient
    ) -> None:
        """AC-10.10: Unhandled 500 response includes correlation_id."""
        mock_settings = type("S", (), {"environment": Environment.PRODUCTION})()
        with patch("tta.api.errors.get_settings", return_value=mock_settings):
            resp = err_client.get("/boom")
        assert resp.status_code == 500
        err = resp.json()["error"]
        assert "correlation_id" in err
        assert err["correlation_id"] is not None

    def test_404_includes_correlation_id(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-10.10: 404 from game endpoint includes correlation_id."""
        pg.execute = AsyncMock(return_value=_make_result())
        resp = client.get(f"/api/v1/games/{uuid4()}")
        assert resp.status_code == 404
        err = resp.json()["error"]
        assert "correlation_id" in err


# ---------------------------------------------------------------------------
# AC-10.11: Unauthenticated requests to protected endpoints return 401
# ---------------------------------------------------------------------------


class TestAC1011UnauthenticatedReturns401:
    """AC-10.11: No auth token on protected endpoints → 401, not 403 or 404."""

    def _make_unauthenticated_client(self) -> TestClient:
        """App with real auth dep but mocked DB/Redis so the 401 can surface.

        get_current_player raises 401 before touching the DB when no token is
        present, but FastAPI resolves all dependencies in the signature so we
        still need pg/redis to not blow up at resolution time.
        """
        settings = _settings()
        a = create_app(settings)
        # Provide stub pg/redis so deps resolve — real get_current_player runs
        pg_mock = AsyncMock()
        redis_mock = AsyncMock()
        a.dependency_overrides[get_pg] = lambda: pg_mock
        a.dependency_overrides[get_redis] = lambda: redis_mock
        return TestClient(a, raise_server_exceptions=False)

    def test_games_list_without_token_returns_401(self) -> None:
        """AC-10.11: GET /api/v1/games without auth → 401."""
        c = self._make_unauthenticated_client()
        resp = c.get("/api/v1/games")
        assert resp.status_code == 401, (
            f"Expected 401 for unauthenticated request, got {resp.status_code}"
        )

    def test_game_detail_without_token_returns_401(self) -> None:
        """AC-10.11: GET /api/v1/games/{id} without auth → 401."""
        c = self._make_unauthenticated_client()
        resp = c.get(f"/api/v1/games/{uuid4()}")
        assert resp.status_code == 401, (
            f"Expected 401, got {resp.status_code}: {resp.text}"
        )

    def test_turn_submission_without_token_returns_401(self) -> None:
        """AC-10.11: POST /api/v1/games/{id}/turns without auth → 401."""
        c = self._make_unauthenticated_client()
        resp = c.post(
            f"/api/v1/games/{uuid4()}/turns",
            json={"input": "look around"},
        )
        assert resp.status_code == 401, (
            f"Expected 401, got {resp.status_code}: {resp.text}"
        )

    def test_401_response_follows_error_envelope(self) -> None:
        """AC-10.11 + AC-10.03: The 401 response follows the standard envelope."""
        c = self._make_unauthenticated_client()
        resp = c.get("/api/v1/games")
        assert resp.status_code == 401
        body = resp.json()
        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]


# ---------------------------------------------------------------------------
# AC-10.12: Player cannot access another player's game — API returns 404
# ---------------------------------------------------------------------------


class TestAC1012PlayerIsolation:
    """AC-10.12: Cross-player game access returns 404, not 403."""

    def test_get_other_players_game_returns_404(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-10.12: Player A cannot read Player B's game — returns 404."""
        pg.execute = AsyncMock(
            return_value=_make_result([_game_row(player_id=_OTHER_PLAYER_ID)])
        )
        resp = client.get(f"/api/v1/games/{_GAME_ID}")
        assert resp.status_code == 404, (
            f"AC-10.12: expected 404 for cross-player access, got {resp.status_code}"
        )

    def test_submit_turn_to_other_players_game_returns_404(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-10.12: Player A cannot submit turns to Player B's game — 404."""
        pg.execute = AsyncMock(
            return_value=_make_result([_game_row(player_id=_OTHER_PLAYER_ID)])
        )
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "do something"},
        )
        assert resp.status_code == 404, (
            f"AC-10.12: expected 404 for cross-player turn, got {resp.status_code}"
        )

    def test_isolation_returns_404_not_403(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-10.12: Cross-player isolation must use 404 (not 403) to avoid
        information leakage about game existence."""
        pg.execute = AsyncMock(
            return_value=_make_result([_game_row(player_id=_OTHER_PLAYER_ID)])
        )
        resp = client.get(f"/api/v1/games/{_GAME_ID}")
        # Must be 404, explicitly not 403
        assert resp.status_code != 403, (
            "AC-10.12: 403 leaks that the game exists; must be 404"
        )
        assert resp.status_code == 404
