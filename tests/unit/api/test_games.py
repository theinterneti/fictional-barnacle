"""Tests for game session routes."""

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


def _row(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def _make_result(
    rows: list[dict[str, Any]] | None = None,
    *,
    scalar: Any = None,
) -> MagicMock:
    """Build a mock CursorResult (sync methods)."""
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


def _game_row(
    *,
    game_id=None,
    player_id=None,
    status: str = "active",
) -> dict[str, Any]:
    """A typical game_sessions row."""
    return {
        "id": game_id or _GAME_ID,
        "player_id": player_id or _PLAYER_ID,
        "status": status,
        "world_seed": "{}",
        "created_at": _NOW,
        "updated_at": _NOW,
    }


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


# ------------------------------------------------------------------
# POST /api/v1/games — Create game
# ------------------------------------------------------------------


class TestCreateGame:
    def test_creates_game_and_returns_201(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),  # count active games
                _make_result(),  # INSERT
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/games", json={})

        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["player_id"] == str(_PLAYER_ID)
        assert body["status"] == "created"
        assert body["turn_count"] == 0

    def test_rejects_when_max_games_reached(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            return_value=_make_result(scalar=5)  # already at limit
        )

        resp = client.post("/api/v1/games", json={})

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "MAX_GAMES_REACHED"


# ------------------------------------------------------------------
# GET /api/v1/games — List games
# ------------------------------------------------------------------


class TestListGames:
    def test_returns_games_list(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # SELECT games
                _make_result(scalar=3),  # turn count for game
            ]
        )

        resp = client.get("/api/v1/games")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["status"] == "active"
        assert data["meta"]["has_more"] is False

    def test_empty_list(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(return_value=_make_result([]))

        resp = client.get("/api/v1/games")

        assert resp.status_code == 200
        assert resp.json()["data"] == []


# ------------------------------------------------------------------
# GET /api/v1/games/{id} — Game state
# ------------------------------------------------------------------


class TestGetGameState:
    def test_returns_game_state(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(scalar=5),  # turn count
                _make_result([]),  # recent turns
                _make_result(),  # processing turn check
            ]
        )

        resp = client.get(f"/api/v1/games/{_GAME_ID}")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["game_id"] == str(_GAME_ID)
        assert body["turn_count"] == 5
        assert body["processing_turn"] is None

    def test_returns_404_for_missing_game(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            return_value=_make_result()  # no row
        )

        resp = client.get(f"/api/v1/games/{uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "GAME_NOT_FOUND"

    def test_returns_404_for_other_players_game(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        other_player = uuid4()
        pg.execute = AsyncMock(
            return_value=_make_result([_game_row(player_id=other_player)])
        )

        resp = client.get(f"/api/v1/games/{_GAME_ID}")

        assert resp.status_code == 404


# ------------------------------------------------------------------
# POST /api/v1/games/{id}/turns — Submit turn
# ------------------------------------------------------------------


class TestSubmitTurn:
    def test_accepts_turn_and_returns_202(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # in-flight check (none)
                _make_result(scalar=0),  # max turn number
                _make_result(),  # INSERT turn
                _make_result(),  # UPDATE status created→active
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "look around"},
        )

        assert resp.status_code == 202
        body = resp.json()["data"]
        assert "turn_id" in body
        assert body["turn_number"] == 1
        assert "stream_url" in body

    def test_rejects_turn_for_paused_game(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(return_value=_make_result([_game_row(status="paused")]))

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "test"},
        )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"

    def test_rejects_concurrent_turn(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result([{"id": uuid4()}]),  # in-flight turn exists
            ]
        )

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "test"},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "TURN_IN_PROGRESS"

    def test_rejects_blank_input(self, client: TestClient) -> None:
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "   "},
        )
        assert resp.status_code == 422

    def test_idempotency_returns_existing_turn(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        existing_turn_id = uuid4()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # in-flight check (none)
                _make_result(
                    [
                        {  # idempotency hit
                            "id": existing_turn_id,
                            "turn_number": 3,
                        }
                    ]
                ),
            ]
        )

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "test", "idempotency_key": "abc123"},
        )

        assert resp.status_code == 202
        body = resp.json()["data"]
        assert body["turn_id"] == str(existing_turn_id)
        assert body["turn_number"] == 3


# ------------------------------------------------------------------
# POST /api/v1/games/{id}/save — Save game
# ------------------------------------------------------------------


class TestSaveGame:
    def test_saves_game(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # UPDATE
                _make_result(scalar=5),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(f"/api/v1/games/{_GAME_ID}/save")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["game_id"] == str(_GAME_ID)
        assert body["turn_count"] == 5


# ------------------------------------------------------------------
# POST /api/v1/games/{id}/resume — Resume game
# ------------------------------------------------------------------


class TestResumeGame:
    def test_resumes_paused_game(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="paused")]),
                _make_result(),  # UPDATE
                _make_result(scalar=3),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "active"

    def test_noop_for_already_active_game(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active")]),
                _make_result(scalar=2),  # turn count
            ]
        )

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "active"

    def test_rejects_ended_game_resume(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(return_value=_make_result([_game_row(status="ended")]))

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "GAME_NOT_RESUMABLE"


# ------------------------------------------------------------------
# PATCH /api/v1/games/{id} — Update game (pause)
# ------------------------------------------------------------------


class TestUpdateGame:
    def test_pauses_active_game(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active")]),
                _make_result(),  # UPDATE
                _make_result(scalar=4),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.patch(
            f"/api/v1/games/{_GAME_ID}",
            json={"status": "paused"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "paused"

    def test_rejects_invalid_transition(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(return_value=_make_result([_game_row(status="ended")]))

        resp = client.patch(
            f"/api/v1/games/{_GAME_ID}",
            json={"status": "active"},
        )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


# ------------------------------------------------------------------
# DELETE /api/v1/games/{id} — End game
# ------------------------------------------------------------------


class TestEndGame:
    def test_ends_active_game(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active")]),
                _make_result(),  # UPDATE
                _make_result(scalar=7),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.delete(f"/api/v1/games/{_GAME_ID}")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "ended"
        assert body["turn_count"] == 7

    def test_rejects_already_ended(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(return_value=_make_result([_game_row(status="ended")]))

        resp = client.delete(f"/api/v1/games/{_GAME_ID}")

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
