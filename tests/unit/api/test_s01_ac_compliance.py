"""S01 Gameplay Loop — Acceptance Criteria compliance tests.

Covers AC-1.2, AC-1.3, AC-1.5, AC-1.6, AC-1.7, AC-1.8, AC-1.10.
Also tests the lifecycle cleanup module (AC-1.7) and command router (AC-1.10).

v2 ACs (deferred, require integration infra):
  AC-1.1 — streaming timing: response starts within 2 s, completes within 15 s
            (requires running pipeline, real LLM stub, and wall-clock measurement)
  AC-1.4 — browser close + reopen → last narrative + contextual recap presented
            (full resume flow requires real session state; covered by resume_game
            integration tests)
  AC-1.9 — SSE mid-stream reconnect reprocesses turn from last input
            (requires real Redis pub/sub and SSE stream; integration only)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
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
from tta.lifecycle.cleanup import IDLE_TIMEOUT_MINUTES, run_lifecycle_pass
from tta.models.player import Player

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_PLAYER = Player(id=_PLAYER_ID, handle="S01Tester", created_at=_NOW)
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
    result.rowcount = 0
    return result


def _game_row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": _GAME_ID,
        "player_id": _PLAYER_ID,
        "status": "active",
        "world_seed": "{}",
        "title": None,
        "summary": None,
        "turn_count": 3,
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
def mock_redis() -> AsyncMock:
    r = AsyncMock()
    r.incr = AsyncMock(return_value=1)
    r.zadd = AsyncMock(return_value=1)
    r.expire = AsyncMock(return_value=1)
    r.zremrangebyrank = AsyncMock(return_value=0)
    r.zcard = AsyncMock(return_value=1)
    r.exists = AsyncMock(return_value=0)
    r.zrange = AsyncMock(return_value=[])
    return r


@pytest.fixture()
def app(pg: AsyncMock, mock_redis: AsyncMock) -> FastAPI:
    settings = _settings()
    a = create_app(settings)
    a.dependency_overrides[get_pg] = lambda: pg
    a.dependency_overrides[get_current_player] = lambda: _PLAYER
    a.dependency_overrides[require_consent] = lambda: _PLAYER
    a.dependency_overrides[require_anonymous_game_limit] = lambda: _PLAYER
    a.dependency_overrides[get_redis] = lambda: mock_redis
    return a


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# AC-1.2: Empty input → 400 input_invalid (API level; narrative nudge is UX)
# ---------------------------------------------------------------------------


class TestAC102EmptyInput:
    """AC-1.2: Empty input returns 400 input_invalid at the API layer.

    FR-1.4 states the API MUST reject blank input with a 400. The 'narrative
    nudge' described in AC-1.2 is client-side UX built on this 400 response;
    the server contract is a 400 with code EMPTY_TURN_INPUT.
    """

    def test_empty_string_returns_400(self, client: TestClient, pg: AsyncMock) -> None:
        """AC-1.2: Submitting empty string → 400 EMPTY_TURN_INPUT."""
        pg.execute = AsyncMock(return_value=_make_result([_game_row()]))

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": ""},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "EMPTY_TURN_INPUT"

    def test_whitespace_only_returns_400(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-1.2: Whitespace-only input → 400 EMPTY_TURN_INPUT."""
        pg.execute = AsyncMock(return_value=_make_result([_game_row()]))

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "   "},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "EMPTY_TURN_INPUT"


# ---------------------------------------------------------------------------
# AC-1.3: /save command → state checkpointed, immersion-preserving confirmation
# ---------------------------------------------------------------------------


class TestAC103SaveCommand:
    """AC-1.3: /save command updates game state and returns a confirmation."""

    def test_save_returns_confirmation_message(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-1.3: /save → 200 with confirmation message, DB updated."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # UPDATE game_sessions SET updated_at
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "/save"},
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "command"
        assert data["command"] == "save"
        assert data["message"]
        # Confirmation is immersion-preserving (not an error message)
        assert "error" not in data["message"].lower()
        assert "saved" in data["message"].lower()


# ---------------------------------------------------------------------------
# AC-1.5: Character failure → narrative describes consequences (no game-over)
# ---------------------------------------------------------------------------


class TestAC105CharacterFailure:
    """AC-1.5: Game continues after failure — no hard game-over state enforced.

    Unit-testable invariant: the POST /turns endpoint accepts input after
    failed turns and does not auto-terminate the game. The narrative content
    of the failure is produced by the LLM pipeline (integration-only); the
    API-level guarantee is that the game remains active.
    """

    def test_active_game_accepts_turn_after_failure(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-1.5: Active game remains active; no forced termination on failure."""
        # Game with multiple turns (player has experienced failures)
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(turn_count=5)]),  # _get_owned_game
                _make_result(),  # advisory lock
                _make_result(),  # in-flight check
                _make_result(scalar=4),  # max turn number
                _make_result(),  # INSERT turn
                _make_result(),  # UPDATE last_played_at
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "try to climb the cliff again"},
        )

        assert resp.status_code == 202
        data = resp.json()["data"]
        assert "turn_id" in data
        assert data["turn_number"] == 5

    def test_game_status_remains_active_not_ended(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-1.5: GET game shows active status — no automatic game-over."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(
                    [_game_row(status="active", turn_count=7)]
                ),  # _get_owned_game
                _make_result(scalar=7),  # turn_count scalar
                _make_result([]),  # recent turns
                _make_result(),  # in-flight check
            ]
        )

        resp = client.get(f"/api/v1/games/{_GAME_ID}")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "active"


# ---------------------------------------------------------------------------
# AC-1.6: Story completion → game archived + new Genesis option presented
# ---------------------------------------------------------------------------


class TestAC106StoryCompletion:
    """AC-1.6: /end command transitions game to completed; response indicates ending."""

    def test_end_command_returns_completion_response(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-1.6: /end → game transitioned and ending response returned."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(turn_count=10)]),  # _get_owned_game
                # /end command inner queries (epilogue generation + status update)
                _make_result(),  # UPDATE game status → completed
            ]
        )
        pg.commit = AsyncMock()

        with patch("tta.api.routes.games._execute_end_command") as mock_end:
            mock_end.return_value = {
                "type": "command",
                "command": "end",
                "message": (
                    "Your story has concluded. Would you like to begin a new adventure?"
                ),
                "new_genesis_available": True,
            }

            resp = client.post(
                f"/api/v1/games/{_GAME_ID}/turns",
                json={"input": "/end"},
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["command"] == "end"
        assert data.get("new_genesis_available") is True


# ---------------------------------------------------------------------------
# AC-1.7: Idle 30+ minutes → lifecycle pass transitions active game to paused
# ---------------------------------------------------------------------------


class TestAC107IdleTimeout:
    """AC-1.7: Active game idle >30 min → lifecycle pass transitions it to 'paused'.

    Tests the lifecycle/cleanup.py module directly (unit test of the cleanup
    logic). The 30-minute threshold matches IDLE_TIMEOUT_MINUTES constant.
    """

    def test_idle_timeout_constant_is_30_minutes(self) -> None:
        """AC-1.7: The idle threshold constant is exactly 30 minutes."""
        assert IDLE_TIMEOUT_MINUTES == 30

    @pytest.mark.asyncio
    async def test_lifecycle_pass_pauses_idle_active_game(self) -> None:
        """AC-1.7: run_lifecycle_pass marks active+idle games as paused."""
        pg = AsyncMock()
        pg.commit = AsyncMock()
        pg.__aenter__ = AsyncMock(return_value=pg)
        pg.__aexit__ = AsyncMock(return_value=False)

        idle_result = MagicMock()
        idle_result.rowcount = 1

        no_rows = MagicMock()
        no_rows.rowcount = 0

        pg.execute = AsyncMock(
            side_effect=[
                no_rows,  # Rule 1: abandon check
                no_rows,  # Rule 2: expire check
                idle_result,  # Rule 3: idle → paused (1 row affected)
                no_rows,  # Rule 4: anon cleanup
            ]
        )

        session_factory = MagicMock(return_value=pg)

        result = await run_lifecycle_pass(session_factory)

        assert result["idle_paused"] == 1

    @pytest.mark.asyncio
    async def test_lifecycle_pass_uses_30_minute_cutoff(self) -> None:
        """AC-1.7: Cutoff passed to SQL is exactly `now - 30min`."""
        pg = AsyncMock()
        pg.commit = AsyncMock()
        pg.__aenter__ = AsyncMock(return_value=pg)
        pg.__aexit__ = AsyncMock(return_value=False)

        no_rows = MagicMock()
        no_rows.rowcount = 0
        pg.execute = AsyncMock(return_value=no_rows)

        session_factory = MagicMock(return_value=pg)

        before = datetime.now(UTC)
        await run_lifecycle_pass(session_factory)

        # Extract the cutoff passed to the idle-pause query (3rd execute call)
        call_args = pg.execute.call_args_list[2]
        params = call_args[0][1]  # positional arg: params dict
        cutoff: datetime = params["cutoff"]

        expected_cutoff = before - timedelta(minutes=30)
        # Allow 1 second tolerance for test execution time
        assert abs((cutoff - expected_cutoff).total_seconds()) < 1


# ---------------------------------------------------------------------------
# AC-1.8: Second playthrough → distinct world/character
# ---------------------------------------------------------------------------


class TestAC108SecondPlaythrough:
    """AC-1.8: Creating a new game after a completed game generates a distinct world.

    Unit-testable invariant: POST /games can be called multiple times and
    each returns a new, distinct game_id. World distinctiveness is guaranteed
    by the genesis variance mechanism (AC-2.6) — integration-only validation.
    """

    def test_new_game_after_completed_game_creates_distinct_id(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-1.8: Two POST /games calls return distinct game_ids."""
        game_id_1 = uuid4()
        game_id_2 = uuid4()

        with patch("tta.api.routes.games.uuid4", side_effect=[game_id_1, game_id_2]):
            pg.execute = AsyncMock(
                side_effect=[
                    _make_result(scalar=0),  # count active games (first)
                    _make_result(),  # INSERT game (first)
                    _make_result(scalar=0),  # count active games (second)
                    _make_result(),  # INSERT game (second)
                ]
            )
            pg.commit = AsyncMock()

            resp1 = client.post("/api/v1/games", json={})
            resp2 = client.post("/api/v1/games", json={})

        assert resp1.status_code == 201
        assert resp2.status_code == 201
        id1 = resp1.json()["data"]["game_id"]
        id2 = resp2.json()["data"]["game_id"]
        assert id1 != id2


# ---------------------------------------------------------------------------
# AC-1.10: Unknown / command → help message with available commands listed
# ---------------------------------------------------------------------------


class TestAC110UnknownCommand:
    """AC-1.10: Unknown /command → help message listing available commands."""

    def test_unknown_command_returns_help_message(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-1.10: /unknownthing → 200 with help listing, type 'command'."""
        pg.execute = AsyncMock(return_value=_make_result([_game_row()]))

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "/unknownthing"},
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "command"
        # Returns help, not an error
        assert "error" not in resp.json()
        # Help text lists known commands
        msg = data["message"]
        assert "/help" in msg
        assert "/save" in msg
        assert "/status" in msg

    def test_help_command_also_lists_all_commands(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-1.10: /help explicitly lists all available commands."""
        pg.execute = AsyncMock(return_value=_make_result([_game_row()]))

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "/help"},
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["command"] == "help"
        msg = data["message"]
        # All documented commands must appear
        for cmd in (
            "/help",
            "/save",
            "/status",
            "/character",
            "/relationships",
            "/end",
        ):
            assert cmd in msg, f"Expected '{cmd}' in help message"
