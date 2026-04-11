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
from tta.api.deps import get_current_player, get_pg, require_consent
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
    world_seed: Any = "{}",
) -> dict[str, Any]:
    return {
        "id": game_id or _GAME_ID,
        "player_id": player_id or _PLAYER_ID,
        "status": status,
        "world_seed": world_seed,
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
    a.dependency_overrides[require_consent] = lambda: None
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


# --- World seed fixture for character/relationships tests ---

_WORLD_SEED_DICT: dict[str, Any] = {
    "world_id": "test-world",
    "preferences": {
        "character_name": "Elara",
        "character_concept": "A wandering herbalist seeking lost knowledge",
        "tone": "whimsical",
    },
    "genesis": {
        "world_id": "test-world",
        "player_location_id": "clearing",
        "template_key": "enchanted-forest",
        "narrative_intro": "The mist parts before you...",
    },
}


# --- /character command tests (S06-AC-6.1) ---


class TestCharacterCommand:
    def test_character_returns_details(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute.return_value = _make_result([_game_row(world_seed=_WORLD_SEED_DICT)])
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/character"}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["command"] == "character"
        assert "Elara" in data["message"]
        assert "herbalist" in data["message"]

    def test_character_includes_tone(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute.return_value = _make_result([_game_row(world_seed=_WORLD_SEED_DICT)])
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/character"}
        )
        data = resp.json()["data"]
        assert "whimsical" in data["message"].lower()

    def test_character_no_world_seed(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute.return_value = _make_result([_game_row(world_seed=None)])
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/character"}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["command"] == "character"
        assert "hasn't been created" in data["message"]

    def test_character_invalid_world_seed(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute.return_value = _make_result([_game_row(world_seed="not-json")])
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/character"}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["command"] == "character"
        assert "hasn't been created" in data["message"].lower()


# --- /relationships command tests (S06-AC-6.3) ---


class TestRelationshipsCommand:
    def _mock_npc(self, key: str, role: str, disposition: str) -> MagicMock:
        npc = MagicMock()
        npc.key = key
        npc.role = MagicMock(value=role)
        npc.disposition = disposition
        return npc

    def test_relationships_lists_npcs(
        self, client: TestClient, app: FastAPI, pg: AsyncMock
    ) -> None:
        template = MagicMock()
        template.npcs = [
            self._mock_npc("old_sage", "quest_giver", "friendly"),
            self._mock_npc("shadow_fox", "merchant", "wary"),
        ]
        registry = MagicMock()
        registry.get.return_value = template
        app.state.template_registry = registry

        pg.execute.return_value = _make_result([_game_row(world_seed=_WORLD_SEED_DICT)])
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/relationships"}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["command"] == "relationships"
        assert "Old Sage" in data["message"]
        assert "Shadow Fox" in data["message"]
        assert "friendly" in data["message"]
        assert "wary" in data["message"]

    def test_relationships_no_world_seed(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute.return_value = _make_result([_game_row(world_seed=None)])
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/relationships"}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "haven't met anyone" in data["message"]

    def test_relationships_empty_npcs(
        self, client: TestClient, app: FastAPI, pg: AsyncMock
    ) -> None:
        template = MagicMock()
        template.npcs = []
        registry = MagicMock()
        registry.get.return_value = template
        app.state.template_registry = registry

        pg.execute.return_value = _make_result([_game_row(world_seed=_WORLD_SEED_DICT)])
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/relationships"}
        )
        data = resp.json()["data"]
        assert "haven't met anyone" in data["message"]


# --- /end command tests (S01-AC-1.6) ---


class TestEndCommand:
    def test_end_transitions_to_ended(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute.side_effect = [
            _make_result([_game_row(world_seed=_WORLD_SEED_DICT)]),
            MagicMock(),  # UPDATE
            _make_result(scalar=10),  # turn count
        ]
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/end"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["command"] == "end"
        assert "Elara" in data["message"]
        assert "10 turns" in data["message"]
        assert "new game" in data["message"].lower()

    def test_end_already_ended(self, client: TestClient, pg: AsyncMock) -> None:
        """Ending an already-ended game returns 409 (status check before routing)."""
        pg.execute.return_value = _make_result(
            [_game_row(status="ended", world_seed=_WORLD_SEED_DICT)]
        )
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/end"})
        assert resp.status_code == 409

    def test_end_without_character_name(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        seed: dict[str, Any] = {
            "world_id": "test-world",
            "preferences": {"tone": "dark"},
            "genesis": {
                "world_id": "test-world",
                "player_location_id": "void",
                "template_key": "test-template",
                "narrative_intro": "...",
            },
        }
        pg.execute.side_effect = [
            _make_result([_game_row(world_seed=seed)]),
            MagicMock(),  # UPDATE
            _make_result(scalar=3),  # turn count
        ]
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/end"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "Traveler" in data["message"]
        assert "3 turns" in data["message"]

    def test_end_singular_turn(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute.side_effect = [
            _make_result([_game_row(world_seed=_WORLD_SEED_DICT)]),
            MagicMock(),  # UPDATE
            _make_result(scalar=1),  # turn count
        ]
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/end"})
        data = resp.json()["data"]
        assert "1 turn," in data["message"]
        assert "1 turns" not in data["message"]


# --- Help text includes new commands ---


class TestHelpTextUpdated:
    def test_help_includes_character(self, client: TestClient, pg: AsyncMock) -> None:
        _setup_active_game(pg)
        resp = client.post(f"/api/v1/games/{_GAME_ID}/turns", json={"input": "/help"})
        data = resp.json()["data"]
        assert "/character" in data["message"]
        assert "/relationships" in data["message"]
        assert "/end" in data["message"]
