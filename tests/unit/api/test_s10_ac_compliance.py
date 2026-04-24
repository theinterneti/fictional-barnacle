"""S10 API & Streaming — Acceptance Criteria compliance tests.

Covers AC-10.01, AC-10.02, AC-10.03, AC-10.06, AC-10.07, AC-10.08, AC-10.09,
AC-10.10, AC-10.11, AC-10.12, AC-10.13.
Also covers S10 §6.2/§6.4/§6.5 canonical event taxonomy:
  FR-10.34 — narrative events with 0-indexed sequence per chunk
  FR-10.35 — narrative_end.total_chunks == number of narrative events
  FR-10.36 — error event on failure includes turn_id; stream continues (returns)
  FR-10.38 — heartbeat event (not keepalive) used for idle connections

Unit-only ACs (require integration infra for full validation):
  AC-10.04 — SSE chunk delivery within 2 s (real-time timing, integration only)
  AC-10.05 — Reconnect / missed events within 30 s (Redis pub/sub, integration only)
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
from tta.models.events import (
    HeartbeatEvent,
)
from tta.models.player import Player
from tta.models.turn import TurnState, TurnStatus

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


@pytest.mark.spec("AC-10.01")
class TestAC1001GameplayFlow:
    """AC-10.01: Player can create account, start game, submit turn via API."""

    def test_full_flow_create_and_submit_turn(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-10.01: create game → submit turn → returns stream URL.

        This is the documented happy-path flow using only public API endpoints:
          POST /api/v1/games  →  201 with game_id
          POST /api/v1/games/{id}/turns  →  202 with stream_url

        uuid4 is patched so the game_id returned by POST /games matches the
        id in the _get_owned_game mock row — preventing a false pass where the
        turn query would return a row with a different id than what was created.
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

        # Patch uuid4 so the created game_id is deterministic and matches _GAME_ID
        # (the id used in _game_row()), ensuring the mock DB row is consistent with
        # the actual game_id that the turn request is targeting.
        with patch("tta.api.routes.games.uuid4", return_value=_GAME_ID):
            create_resp = client.post("/api/v1/games", json={})
        assert create_resp.status_code == 201
        game_id = create_resp.json()["data"]["game_id"]
        assert game_id == str(_GAME_ID)

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


@pytest.mark.spec("AC-10.03")
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


@pytest.mark.spec("AC-10.07")
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


@pytest.mark.spec("AC-10.09")
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


@pytest.mark.spec("AC-10.10")
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


@pytest.mark.spec("AC-10.11")
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


@pytest.mark.spec("AC-10.12")
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


# ---------------------------------------------------------------------------
# Helpers shared by SSE taxonomy tests
# ---------------------------------------------------------------------------


def _make_stream_app(turn_state: TurnState, pg_mock: AsyncMock) -> FastAPI:
    """Build a test app wired to a deterministic turn result store."""

    class _FakeStore:
        def __init__(self, state: TurnState) -> None:
            self._state = state

        async def wait_for_result(
            self, turn_id: str, timeout: float = 30.0
        ) -> TurnState:
            return self._state

        async def publish(self, turn_id: str, result: object) -> None:
            pass

    application = create_app(_settings())
    application.dependency_overrides[get_current_player] = lambda: _PLAYER
    application.dependency_overrides[get_pg] = lambda: pg_mock
    application.state.turn_result_store = _FakeStore(turn_state)
    # Redis mock for SSE replay buffer (all ops used by SseEventBuffer).
    _counter = 0

    async def _incr(_key: str) -> int:
        nonlocal _counter
        _counter += 1
        return _counter

    _redis = AsyncMock()
    _redis.incr = AsyncMock(side_effect=_incr)
    _redis.zadd = AsyncMock(return_value=0)
    _redis.expire = AsyncMock(return_value=True)
    _redis.zremrangebyrank = AsyncMock(return_value=0)
    _redis.zcard = AsyncMock(return_value=0)
    _redis.zrangebyscore = AsyncMock(return_value=[])
    _redis.zrange = AsyncMock(return_value=[])
    application.state.redis = _redis
    return application


def _game_row_stream(**overrides: Any) -> dict[str, Any]:
    """Minimal game row for stream-endpoint mocks."""
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


# ---------------------------------------------------------------------------
# S10 §6.2 / FR-10.34 — narrative event uses type "narrative" (not "narrative_block")
# ---------------------------------------------------------------------------


class TestS10Section62NarrativeEventType:
    """S10 §6.2: Stream emits 'narrative' events, not legacy 'narrative_block'."""

    def test_stream_emits_narrative_not_narrative_block(self) -> None:
        """FR-10.34: event type is 'narrative', not the legacy 'narrative_block'."""
        turn_id = uuid4()
        state = TurnState(
            session_id=_GAME_ID,
            turn_id=turn_id,
            turn_number=1,
            player_input="look around",
            game_state={},
            status=TurnStatus.complete,
            narrative_output="You see a forest.",
        )

        pg = AsyncMock()
        pg.commit = AsyncMock()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row_stream()]),
                _make_result([{"id": turn_id, "turn_number": 1}]),
            ]
        )

        app = _make_stream_app(state, pg)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")
        assert resp.status_code == 200
        body = resp.text
        assert "event: narrative\n" in body
        assert "event: narrative_block" not in body

    def test_stream_emits_narrative_end_after_chunks(self) -> None:
        """S10 §6.2: 'narrative_end' event follows all narrative chunks."""
        turn_id = uuid4()
        state = TurnState(
            session_id=_GAME_ID,
            turn_id=turn_id,
            turn_number=1,
            player_input="look around",
            game_state={},
            status=TurnStatus.complete,
            narrative_output="You see a forest.",
        )

        pg = AsyncMock()
        pg.commit = AsyncMock()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row_stream()]),
                _make_result([{"id": turn_id, "turn_number": 1}]),
            ]
        )

        app = _make_stream_app(state, pg)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")
        body = resp.text
        narr_pos = body.index("event: narrative\n")
        end_pos = body.index("event: narrative_end\n")
        assert narr_pos < end_pos, "narrative_end must follow narrative chunks"

    def test_state_update_appears_after_narrative_end(self) -> None:
        """DIV-04 / S10 §6.4: state_update event is emitted after narrative_end.

        The spec mandates ordering: narrative chunks → narrative_end → state_update.
        """
        turn_id = uuid4()
        state = TurnState(
            session_id=_GAME_ID,
            turn_id=turn_id,
            turn_number=1,
            player_input="go north",
            game_state={},
            status=TurnStatus.complete,
            narrative_output="You move north through the trees.",
            world_state_updates=[
                {
                    "entity": "player",
                    "attribute": "location",
                    "old_value": "clearing",
                    "new_value": "forest_path",
                    "reason": "Player moved north",
                }
            ],
        )

        pg = AsyncMock()
        pg.commit = AsyncMock()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row_stream()]),
                _make_result([{"id": turn_id, "turn_number": 1}]),
            ]
        )

        app = _make_stream_app(state, pg)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")
        assert resp.status_code == 200
        body = resp.text

        assert "event: state_update\n" in body, (
            "state_update event not found in stream for turn with world_state_updates"
        )
        end_pos = body.index("event: narrative_end\n")
        state_update_pos = body.index("event: state_update\n")
        assert end_pos < state_update_pos, (
            "state_update must appear after narrative_end "
            f"(narrative_end at {end_pos}, state_update at {state_update_pos})"
        )


# ---------------------------------------------------------------------------
# S10 §6.4 / FR-10.34 — sequence starts at 0 and increments per chunk
# ---------------------------------------------------------------------------


class TestS10FR1034SequenceNumbering:
    """FR-10.34: sequence field starts at 0 and increments by 1 per chunk."""

    def test_multi_chunk_sequence_starts_at_zero(self) -> None:
        """Three sentence narrative → sequence values 0, 1, 2."""
        turn_id = uuid4()
        state = TurnState(
            session_id=_GAME_ID,
            turn_id=turn_id,
            turn_number=1,
            player_input="look around",
            game_state={},
            status=TurnStatus.complete,
            narrative_output="First sentence. Second sentence. Third sentence.",
        )

        pg = AsyncMock()
        pg.commit = AsyncMock()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row_stream()]),
                _make_result([{"id": turn_id, "turn_number": 1}]),
            ]
        )

        app = _make_stream_app(state, pg)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")
        assert resp.status_code == 200
        body = resp.text

        import json as _json

        sequences = []
        for block in body.split("\n\n"):
            if "event: narrative\n" in block:
                for line in block.split("\n"):
                    if line.startswith("data:"):
                        payload = _json.loads(line[len("data: ") :])
                        sequences.append(payload["sequence"])

        assert sequences == [0, 1, 2], f"Expected sequences [0, 1, 2], got {sequences}"

        # DIV-01: narrative events must also carry `text` and `turn_id`
        for block in body.split("\n\n"):
            if "event: narrative\n" in block:
                for line in block.split("\n"):
                    if line.startswith("data:"):
                        payload = _json.loads(line[len("data: ") :])
                        assert "text" in payload, (
                            "narrative event payload missing 'text' field"
                        )
                        assert "turn_id" in payload, (
                            "narrative event payload missing 'turn_id' field"
                        )


# ---------------------------------------------------------------------------
# S10 §6.4 / FR-10.35 — total_chunks in narrative_end == narrative event count
# ---------------------------------------------------------------------------


class TestS10FR1035TotalChunks:
    """FR-10.35: narrative_end.total_chunks matches the number of narrative events."""

    def test_total_chunks_matches_narrative_count(self) -> None:
        """narrative_end.total_chunks == count of 'narrative' events in stream."""
        turn_id = uuid4()
        state = TurnState(
            session_id=_GAME_ID,
            turn_id=turn_id,
            turn_number=1,
            player_input="look around",
            game_state={},
            status=TurnStatus.complete,
            narrative_output="First sentence. Second sentence. Third sentence.",
        )

        pg = AsyncMock()
        pg.commit = AsyncMock()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row_stream()]),
                _make_result([{"id": turn_id, "turn_number": 1}]),
            ]
        )

        app = _make_stream_app(state, pg)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")
        body = resp.text

        import json as _json

        narrative_count = body.count("event: narrative\n")
        total_chunks: int | None = None
        for block in body.split("\n\n"):
            if "event: narrative_end\n" in block:
                for line in block.split("\n"):
                    if line.startswith("data:"):
                        payload = _json.loads(line[len("data: ") :])
                        total_chunks = payload["total_chunks"]

        assert total_chunks is not None, "narrative_end event not found in stream"
        assert total_chunks == narrative_count, (
            f"total_chunks={total_chunks} != narrative event count={narrative_count}"
        )

        # DIV-02: narrative_end payload must include turn_id
        narrative_end_payload: dict | None = None
        for block in body.split("\n\n"):
            if "event: narrative_end\n" in block:
                for line in block.split("\n"):
                    if line.startswith("data:"):
                        narrative_end_payload = _json.loads(line[len("data: ") :])
        assert narrative_end_payload is not None, (
            "narrative_end event not found for turn_id check"
        )
        assert "turn_id" in narrative_end_payload, (
            "narrative_end payload missing 'turn_id' field"
        )


# ---------------------------------------------------------------------------
# S10 §6.4 / FR-10.36 — error event on failure includes turn_id
# ---------------------------------------------------------------------------


class TestS10FR1036ErrorEventTurnId:
    """FR-10.36: error event on pipeline failure includes turn_id field."""

    def test_failed_turn_error_event_has_turn_id(self) -> None:
        """When result.status == failed, ErrorEvent in stream has turn_id set."""
        turn_id = uuid4()
        state = TurnState(
            session_id=_GAME_ID,
            turn_id=turn_id,
            turn_number=1,
            player_input="look around",
            game_state={},
            status=TurnStatus.failed,
        )

        pg = AsyncMock()
        pg.commit = AsyncMock()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row_stream()]),
                _make_result([{"id": turn_id, "turn_number": 1}]),
            ]
        )

        app = _make_stream_app(state, pg)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")
        assert resp.status_code == 200
        body = resp.text

        assert "event: error\n" in body

        import json as _json

        turn_id_in_event: str | None = None
        for block in body.split("\n\n"):
            if "event: error\n" in block:
                for line in block.split("\n"):
                    if line.startswith("data:"):
                        payload = _json.loads(line[len("data: ") :])
                        turn_id_in_event = payload.get("turn_id")

        assert turn_id_in_event is not None, (
            "ErrorEvent.turn_id must be set on pipeline failure"
        )
        assert turn_id_in_event == str(turn_id)

        # DIV-07: error event payload must also include `code` and `message`
        for block in body.split("\n\n"):
            if "event: error\n" in block:
                for line in block.split("\n"):
                    if line.startswith("data:"):
                        err_payload = _json.loads(line[len("data: ") :])
                        assert "code" in err_payload, (
                            "error event payload missing 'code' field"
                        )
                        assert "message" in err_payload, (
                            "error event payload missing 'message' field"
                        )


# ---------------------------------------------------------------------------
# S10 §6.5 / FR-10.38 — heartbeat event (not keepalive) on idle connections
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-10.06")
class TestS10FR1038HeartbeatEvent:
    """FR-10.38: SSE stream uses 'heartbeat' event type (not legacy 'keepalive').

    Covers the unit-testable portion of AC-10.06 (heartbeat format and emission).
    The 15-second timing SLA requires integration tests and is deferred.
    """

    def test_heartbeat_event_model_type(self) -> None:
        """HeartbeatEvent serialises with event_type 'heartbeat'."""
        evt = HeartbeatEvent()
        assert evt.event_type == "heartbeat"

    def test_heartbeat_sse_wire_format(self) -> None:
        """HeartbeatEvent.format_sse() produces 'event: heartbeat' line."""
        import json as _json

        evt = HeartbeatEvent()
        sse = evt.format_sse(event_id=1)
        assert "event: heartbeat\n" in sse
        assert "event: keepalive" not in sse

        # DIV-06: heartbeat payload must include `timestamp`
        for line in sse.split("\n"):
            if line.startswith("data:"):
                payload = _json.loads(line[len("data: ") :])
                assert "timestamp" in payload, (
                    "heartbeat event payload missing 'timestamp' field"
                )

    def test_heartbeat_not_keepalive_in_stream_on_timeout(self) -> None:
        """Stream emits 'heartbeat' (not 'keepalive') when pipeline result is delayed.

        We simulate a wait timeout by returning None from wait_for_result on the
        first call, then the real result on the second, triggering one heartbeat.
        """
        turn_id = uuid4()
        result_state = TurnState(
            session_id=_GAME_ID,
            turn_id=turn_id,
            turn_number=1,
            player_input="look around",
            game_state={},
            status=TurnStatus.complete,
            narrative_output="You see a forest.",
        )

        call_count = 0

        class _DelayedStore:
            async def wait_for_result(
                self, _turn_id: str, timeout: float = 30.0
            ) -> TurnState | None:
                nonlocal call_count
                call_count += 1
                # First call: return None to trigger a heartbeat
                if call_count == 1:
                    return None
                return result_state

            async def publish(self, turn_id: str, result: object) -> None:
                pass

        pg = AsyncMock()
        pg.commit = AsyncMock()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row_stream()]),
                _make_result([{"id": turn_id, "turn_number": 1}]),
            ]
        )

        application = create_app(_settings())
        application.dependency_overrides[get_current_player] = lambda: _PLAYER
        application.dependency_overrides[get_pg] = lambda: pg
        application.state.turn_result_store = _DelayedStore()

        _counter2 = 0

        async def _incr2(_key: str) -> int:
            nonlocal _counter2
            _counter2 += 1
            return _counter2

        _redis2 = AsyncMock()
        _redis2.incr = AsyncMock(side_effect=_incr2)
        _redis2.zadd = AsyncMock(return_value=0)
        _redis2.expire = AsyncMock(return_value=True)
        _redis2.zremrangebyrank = AsyncMock(return_value=0)
        _redis2.zcard = AsyncMock(return_value=0)
        _redis2.zrangebyscore = AsyncMock(return_value=[])
        _redis2.zrange = AsyncMock(return_value=[])
        application.state.redis = _redis2

        client = TestClient(application, raise_server_exceptions=False)
        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")
        body = resp.text

        assert "event: heartbeat\n" in body
        assert "event: keepalive" not in body


# ---------------------------------------------------------------------------
# AC-10.13: Empty / whitespace-only turn input → 400 input_invalid
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-10.13")
class TestAC1013EmptyTurnInput:
    """AC-10.13: Submitting empty or whitespace-only input returns 400 input_invalid."""

    @pytest.mark.parametrize("bad_input", ["", "   ", "\t", "\n"])
    def test_empty_or_whitespace_returns_400(
        self, bad_input: str, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-10.13: Empty or whitespace-only input → 400 with EMPTY_TURN_INPUT code."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # advisory lock
                _make_result(),  # in-flight check
            ]
        )
        pg.commit = AsyncMock()
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": bad_input},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "EMPTY_TURN_INPUT"


@pytest.mark.spec("AC-10.02")
class TestAC1002OpenAPIValidity:
    """AC-10.02: The app's OpenAPI spec validates against the OpenAPI 3.x schema."""

    def test_openapi_spec_is_valid(self) -> None:
        """Fetch /openapi.json and validate with openapi-spec-validator."""
        from openapi_spec_validator import validate

        application = create_app(_settings())
        with TestClient(application) as c:
            resp = c.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        # validate() raises if the spec is invalid
        validate(spec)


# ---------------------------------------------------------------------------
# AC-10.08: Rate-limit headers present on responses
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-10.08")
class TestAC1008RateLimitHeaders:
    """AC-10.08: Server includes X-RateLimit-* headers on API responses."""

    def test_rate_limit_headers_present_on_game_get(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-10.08: GET /api/v1/games/{id} includes rate-limit headers."""
        pg.execute = AsyncMock(return_value=_make_result())
        resp = client.get(f"/api/v1/games/{uuid4()}")
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers
        assert "x-ratelimit-reset" in resp.headers

    def test_rate_limit_headers_values_are_valid(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-10.08: Rate-limit header values are valid integers."""
        pg.execute = AsyncMock(return_value=_make_result())
        resp = client.get(f"/api/v1/games/{uuid4()}")
        limit = int(resp.headers.get("x-ratelimit-limit", 0))
        remaining = int(resp.headers.get("x-ratelimit-remaining", 0))
        reset_at = int(resp.headers.get("x-ratelimit-reset", 0))

        assert limit > 0
        assert remaining >= 0
        assert reset_at > 0
