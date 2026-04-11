"""E2E gameplay smoke test — validates the full game flow end-to-end.

Sequence: register → create game (genesis) → submit turn (202) →
nudge (200) → command (200) → get history.

Uses FastAPI TestClient with mocked DB/LLM — no real services needed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import get_current_player, get_pg, require_consent
from tta.config import Settings
from tta.models.player import Player

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_PLAYER = Player(id=_PLAYER_ID, handle="SmokeTester", created_at=_NOW)
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
        "turn_count": 0,
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
def client(pg: AsyncMock) -> TestClient:
    settings = _settings()
    app = create_app(settings)
    app.dependency_overrides[get_pg] = lambda: pg
    app.dependency_overrides[get_current_player] = lambda: _PLAYER
    app.dependency_overrides[require_consent] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


class TestGameplayFlow:
    """Full gameplay flow smoke test — each test validates one step."""

    def test_step1_create_game(self, client: TestClient, pg: AsyncMock) -> None:
        """Create a new game — genesis degrades gracefully without
        template_registry, game still created successfully."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),  # count active games
                _make_result(),  # INSERT game
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/games", json={})

        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "game_id" in data
        assert data["status"] == "active"

    def test_step2_submit_narrative_turn(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Submit a normal narrative turn — returns 202 with stream URL."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(turn_count=1)]),  # _get_owned_game
                _make_result(),  # advisory lock
                _make_result(),  # in-flight check (none)
                _make_result(scalar=0),  # max turn number
                _make_result(),  # INSERT turn
                _make_result(),  # UPDATE last_played_at
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "look around the forest"},
        )

        assert resp.status_code == 202
        data = resp.json()["data"]
        assert "turn_id" in data
        assert data["turn_number"] == 1
        assert "stream_url" in data
        assert f"/games/{_GAME_ID}/stream" in data["stream_url"]

    def test_step3_empty_input_returns_nudge(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Blank input returns a 200 nudge — no DB write, no pipeline."""
        pg.execute = AsyncMock(return_value=_make_result([_game_row(turn_count=2)]))

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": ""},
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "nudge"
        assert len(data["message"]) > 0

    def test_step4_help_command(self, client: TestClient, pg: AsyncMock) -> None:
        """/help returns command listing — no pipeline, no DB turn."""
        pg.execute = AsyncMock(return_value=_make_result([_game_row(turn_count=2)]))

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "/help"},
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "command"
        assert data["command"] == "help"
        assert "/help" in data["message"]
        assert "/save" in data["message"]
        assert "/status" in data["message"]

    def test_step5_status_command(self, client: TestClient, pg: AsyncMock) -> None:
        """/status returns game session info."""
        pg.execute = AsyncMock(
            return_value=_make_result(
                [_game_row(turn_count=7, template_id="dark-castle")]
            )
        )

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "/status"},
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "command"
        assert data["command"] == "status"
        assert "7" in data["message"]  # turn count
        assert "dark-castle" in data["message"]  # template

    def test_step6_save_command(self, client: TestClient, pg: AsyncMock) -> None:
        """/save confirms auto-save behavior."""
        pg.execute = AsyncMock(return_value=_make_result([_game_row()]))

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "/save"},
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "command"
        assert data["command"] == "save"

    def test_step7_get_game_details(self, client: TestClient, pg: AsyncMock) -> None:
        """GET game details returns game state."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(scalar=5),  # _get_turn_count
                _make_result([]),  # recent turns
                _make_result(),  # processing turn check
            ]
        )

        resp = client.get(f"/api/v1/games/{_GAME_ID}")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["game_id"] == str(_GAME_ID)
        assert data["status"] == "active"
        assert data["turn_count"] == 5

    def test_step8_inactive_game_rejects_turn(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Turns are rejected for non-active games."""
        pg.execute = AsyncMock(return_value=_make_result([_game_row(status="ended")]))

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "try again"},
        )

        assert resp.status_code == 409

    def test_step9_unknown_command_returns_help(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Unknown /command returns help listing."""
        pg.execute = AsyncMock(return_value=_make_result([_game_row()]))

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "/dance"},
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "command"
        assert data["command"] == "unknown"
        assert "/help" in data["message"]
