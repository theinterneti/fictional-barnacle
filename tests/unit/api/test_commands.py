"""Tests for command router and nudge responses (S01 AC-1.2, AC-1.10)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import get_current_player, get_pg
from tta.config import Settings
from tta.models.player import Player

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_PLAYER = Player(id=_PLAYER_ID, handle="Tester", created_at=_NOW)
_GAME_ID = uuid4()


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


def _game_row(
    *,
    game_id: Any = None,
    player_id: Any = None,
    status: str = "active",
    turn_count: int = 5,
    template_id: str = "enchanted-forest",
    last_played_at: datetime | None = _NOW,
    needs_recovery: bool = False,
) -> dict[str, Any]:
    return {
        "id": game_id or _GAME_ID,
        "player_id": player_id or _PLAYER_ID,
        "status": status,
        "world_seed": "{}",
        "title": None,
        "summary": None,
        "turn_count": turn_count,
        "needs_recovery": needs_recovery,
        "summary_generated_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "last_played_at": last_played_at,
        "deleted_at": None,
        "template_id": template_id,
    }


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


@pytest.fixture()
def pg() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def app(pg: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    settings = _settings()
    monkeypatch.setattr("tta.api.routes.games.get_settings", lambda: settings)
    a = create_app(settings=settings)

    async def _pg():
        yield pg

    a.dependency_overrides[get_pg] = _pg
    a.dependency_overrides[get_current_player] = lambda: _PLAYER
    return a


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _setup_active_game(pg: AsyncMock) -> None:
    """Configure pg mock to return an active game on first query."""
    pg.execute.return_value = _make_result([_game_row()])


# --- Nudge tests (AC-1.2: empty input → atmospheric nudge) ---


class TestNudge:
    def test_empty_input_returns_nudge(self, client: TestClient, pg: AsyncMock) -> None:
        _setup_active_game(pg)
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": ""})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "nudge"
        assert len(data["message"]) > 0

    def test_whitespace_only_returns_nudge(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        _setup_active_game(pg)
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "   "})
        assert resp.status_code == 200
        assert resp.json()["data"]["type"] == "nudge"

    def test_nudge_message_varies(self, client: TestClient, pg: AsyncMock) -> None:
        """Multiple nudge requests should produce different messages."""
        messages = set()
        for _ in range(20):
            _setup_active_game(pg)
            resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": ""})
            messages.add(resp.json()["data"]["message"])
        assert len(messages) > 1, "Nudge phrases should vary"


# --- Command tests (AC-1.10: slash commands) ---


class TestHelpCommand:
    def test_help_returns_200(self, client: TestClient, pg: AsyncMock) -> None:
        _setup_active_game(pg)
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/help"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "command"
        assert data["command"] == "help"
        assert "/help" in data["message"]
        assert "/save" in data["message"]
        assert "/status" in data["message"]

    def test_help_case_insensitive(self, client: TestClient, pg: AsyncMock) -> None:
        _setup_active_game(pg)
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/HELP"})
        assert resp.status_code == 200
        assert resp.json()["data"]["command"] == "help"

    def test_help_with_trailing_text(self, client: TestClient, pg: AsyncMock) -> None:
        _setup_active_game(pg)
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "/help me please"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["command"] == "help"


class TestSaveCommand:
    def test_save_returns_confirmation(self, client: TestClient, pg: AsyncMock) -> None:
        _setup_active_game(pg)
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/save"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "command"
        assert data["command"] == "save"
        assert "saved" in data["message"].lower()


class TestStatusCommand:
    def test_status_returns_game_info(self, client: TestClient, pg: AsyncMock) -> None:
        # First call: _get_owned_game, second call: turn count
        pg.execute.side_effect = [
            _make_result([_game_row(turn_count=5)]),
            _make_result(scalar=5),
        ]
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/status"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["command"] == "status"
        assert "Turns played: 5" in data["message"]
        assert "active" in data["message"].lower()


class TestUnknownCommand:
    def test_unknown_command_returns_help(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        _setup_active_game(pg)
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/dance"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "command"
        assert data["command"] == "unknown"
        assert "Unknown command" in data["message"]
        assert "/help" in data["message"]

    def test_unknown_command_doesnt_reflect_input(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Unknown commands should not echo user input (XSS safety)."""
        _setup_active_game(pg)
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "/xss<script>alert(1)</script>"},
        )
        data = resp.json()["data"]
        assert "<script>" not in data["message"]


class TestBareSlash:
    def test_bare_slash_passes_to_pipeline(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """A lone '/' should NOT be treated as a command."""
        # Setup: game row returned, then advisory lock, then in-flight
        # check. Since we're not mocking the full pipeline, expect it
        # to proceed past command routing (and likely error on the
        # pipeline side). We just verify it's NOT a 200 command response.
        _setup_active_game(pg)
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/"})
        # Should NOT be a command response — it proceeds to pipeline
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            assert data.get("type") not in ("command", "nudge")


class TestCommandOnInactiveGame:
    def test_commands_rejected_on_ended_game(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Commands should fail on non-active games (before routing)."""
        pg.execute.return_value = _make_result([_game_row(status="ended")])
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/help"})
        assert resp.status_code == 409
