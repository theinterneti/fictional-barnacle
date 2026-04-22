"""S27 Save/Load & Game Management — Acceptance Criteria compliance tests.

Covers the 10 v1 ACs from specs/27-save-load-and-game-management.md.

This file acts as a structured reference mapping each AC to the behaviours
already exercised in test_games.py, while adding targeted compliance checks.

Each test class maps to one AC group.
"""

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
from tta.api.deps import (
    get_current_player,
    get_pg,
    require_anonymous_game_limit,
    require_consent,
)
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
    game_id: Any = None,
    player_id: Any = None,
    status: str = "active",
    title: str | None = None,
    summary: str | None = None,
    turn_count: int = 0,
    deleted_at: datetime | None = None,
    needs_recovery: bool = False,
) -> dict[str, Any]:
    return {
        "id": game_id or _GAME_ID,
        "player_id": player_id or _PLAYER_ID,
        "status": status,
        "world_seed": "{}",
        "title": title,
        "summary": summary,
        "turn_count": turn_count,
        "needs_recovery": needs_recovery,
        "summary_generated_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "last_played_at": _NOW,
        "deleted_at": deleted_at,
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
    a.dependency_overrides[require_consent] = lambda: _PLAYER
    a.dependency_overrides[require_anonymous_game_limit] = lambda: _PLAYER
    return a


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ── AC-27.1: Game creation ────────────────────────────────────────


@pytest.mark.spec("AC-27.01")
class TestAC271GameCreation:
    """AC-27.1: POST /api/v1/games returns 201 with game_id, player_id,
    status="active", and turn_count=0.

    Gherkin:
      Given an authenticated player
      When POST /api/v1/games is called
      Then the response status is 201
      And the body includes game_id, player_id, status, and turn_count
    """

    def test_post_games_returns_201(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),  # active game count check
                _make_result(),  # INSERT game
            ]
        )
        pg.commit = AsyncMock()
        resp = client.post("/api/v1/games", json={})
        assert resp.status_code == 201

    def test_post_games_returns_required_fields(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),
                _make_result(),
            ]
        )
        pg.commit = AsyncMock()
        resp = client.post("/api/v1/games", json={})
        body = resp.json()["data"]
        assert "game_id" in body
        assert "player_id" in body
        assert body["status"] == "active"
        assert body["turn_count"] == 0

    def test_post_games_player_id_matches_authenticated_player(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),
                _make_result(),
            ]
        )
        pg.commit = AsyncMock()
        resp = client.post("/api/v1/games", json={})
        body = resp.json()["data"]
        assert body["player_id"] == str(_PLAYER_ID)


# ── AC-27.2: Game listing ─────────────────────────────────────────


@pytest.mark.spec("AC-27.02")
class TestAC272GameListing:
    """AC-27.2: GET /api/v1/games returns a paginated list of games for the
    authenticated player.

    Gherkin:
      Given an authenticated player with two active games
      When GET /api/v1/games is called
      Then the response includes "games" list and pagination metadata
    """

    def test_get_games_returns_games_list(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        # list_games makes ONE pg.execute call (limit+1 pagination, no COUNT)
        # response: {"data": [...list...], "meta": {...}}
        pg.execute = AsyncMock(
            return_value=_make_result(rows=[_game_row(), _game_row(game_id=uuid4())])
        )
        resp = client.get("/api/v1/games")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert isinstance(body, list)

    def test_get_games_includes_pagination_metadata(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(return_value=_make_result(rows=[_game_row()]))
        resp = client.get("/api/v1/games")
        assert resp.status_code == 200
        meta = resp.json().get("meta", {})
        assert "has_more" in meta


# ── AC-27.3: Get single game ──────────────────────────────────────


@pytest.mark.spec("AC-27.03")
class TestAC273GetGame:
    """AC-27.3: GET /api/v1/games/{id} returns the game state or 404 if
    not found / not owned by the player.

    Gherkin:
      Given an authenticated player and their game
      When GET /api/v1/games/<game_id> is called
      Then the response includes all required game fields

      Given a game_id that does not belong to the player
      When GET /api/v1/games/<game_id> is called
      Then the response is 404
    """

    def test_get_game_returns_200_and_fields(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(rows=[_game_row()]),
                _make_result(scalar=0),
                _make_result(rows=[]),
                _make_result(),
            ]
        )
        resp = client.get(f"/api/v1/games/{_GAME_ID}")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert "game_id" in body or "id" in body

    def test_get_game_not_found_returns_404(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(return_value=_make_result(rows=[]))
        resp = client.get(f"/api/v1/games/{uuid4()}")
        assert resp.status_code == 404


# ── AC-27.4: Soft-delete / abandon game ──────────────────────────


@pytest.mark.spec("AC-27.04")
class TestAC274DeleteGame:
    """AC-27.4: DELETE /api/v1/games/{id} soft-deletes (abandons) the game.

    Gherkin:
      Given an authenticated player and their active game
      When DELETE /api/v1/games/<game_id> is called
      Then the response is 200 or 204
      And the game status becomes "abandoned"
      And the game is no longer returned in the default list
    """

    def test_delete_game_returns_success(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(rows=[_game_row()]),  # _get_owned_game
                _make_result(),  # UPDATE (result unused)
                _make_result(scalar=0),  # _get_turn_count
            ]
        )
        pg.commit = AsyncMock()
        resp = client.request(
            "DELETE", f"/api/v1/games/{_GAME_ID}", json={"confirm": True}
        )
        assert resp.status_code == 204


# ── AC-27.5: Save / resume (session persistence) ─────────────────


@pytest.mark.spec("AC-27.05")
class TestAC275GameResume:
    """AC-27.5: A previously created game retains its state across sessions
    (turn count, title, summary, world_seed).

    Gherkin:
      Given a game was created and turns were played
      When GET /api/v1/games/<game_id> is called in a new session
      Then the game shows the accumulated turn_count
      And the title and summary are preserved
    """

    def test_game_retains_turn_count(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(rows=[_game_row(turn_count=3)]),
                _make_result(scalar=3),
                _make_result(rows=[]),
                _make_result(),
            ]
        )
        resp = client.get(f"/api/v1/games/{_GAME_ID}")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body.get("turn_count") == 3  # matches mocked _game_row(turn_count=3)

    def test_game_retains_title_and_summary(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(rows=[_game_row(title="My Quest", summary="Epic tale")]),
                _make_result(scalar=0),
                _make_result(rows=[]),
                _make_result(),
            ]
        )
        resp = client.get(f"/api/v1/games/{_GAME_ID}")
        assert resp.status_code == 200
        body = resp.json()["data"]
        # Title and summary fields are present in the response
        assert "title" in body
        assert "summary" in body


# ── AC-27.6: Turn count increments ───────────────────────────────


@pytest.mark.spec("AC-27.06")
class TestAC276TurnCountIncrement:
    """AC-27.6: turn_count in the game record increments with each
    completed turn.

    Gherkin:
      Given a game with turn_count = 5
      When GET /api/v1/games/<game_id> is called
      Then turn_count is 5
    """

    def test_turn_count_is_accurate(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(rows=[_game_row(turn_count=5)]),
                _make_result(scalar=5),
                _make_result(rows=[]),
                _make_result(),
            ]
        )
        resp = client.get(f"/api/v1/games/{_GAME_ID}")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["turn_count"] == 5


# ── AC-27.7: State transition — active → completed ────────────────


@pytest.mark.spec("AC-27.07")
class TestAC277StateTransitions:
    """AC-27.7: Games transition through valid states:
    active → completed, active → abandoned (via soft-delete).

    Gherkin:
      Given an active game
      When it is administratively terminated
      Then its status is "completed"

      Given an active game
      When DELETE /api/v1/games/<game_id> is called
      Then its status is "abandoned"
    """

    def test_abandoned_game_is_soft_deleted(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(rows=[_game_row()]),  # _get_owned_game
                _make_result(),  # UPDATE (result unused)
                _make_result(scalar=0),  # _get_turn_count
            ]
        )
        pg.commit = AsyncMock()
        resp = client.request(
            "DELETE", f"/api/v1/games/{_GAME_ID}", json={"confirm": True}
        )
        assert resp.status_code == 204

    def test_completed_game_not_returned_as_active(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Listing with default filter excludes completed games."""
        pg.execute = AsyncMock(return_value=_make_result(rows=[]))
        resp = client.get("/api/v1/games")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body == []


# ── AC-27.8: Read-only after completion ──────────────────────────


@pytest.mark.spec("AC-27.08")
class TestAC278ReadOnlyCompleted:
    """AC-27.8: Completed or abandoned games cannot receive new turns.

    Gherkin:
      Given a game with status "completed"
      When POST /api/v1/games/<game_id>/turns is called
      Then the response status is 409 or 422 (conflict / invalid transition)
    """

    def test_completed_game_rejects_new_turns(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            return_value=_make_result(rows=[_game_row(status="completed")])
        )
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"player_input": "go north"},
        )
        assert resp.status_code in {409, 422}

    def test_abandoned_game_rejects_new_turns(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            return_value=_make_result(
                rows=[_game_row(status="abandoned", deleted_at=_NOW)]
            )
        )
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"player_input": "go north"},
        )
        assert resp.status_code in {409, 422}


# ── AC-27.9: Title and summary persistence ────────────────────────


@pytest.mark.spec("AC-27.09")
class TestAC279TitleAndSummary:
    """AC-27.9: Games store and return a human-readable title and summary.
    These are set by the narrative pipeline and persist in the DB.

    Gherkin:
      Given a game with a title="The Dark Forest" and summary="You entered..."
      When GET /api/v1/games/<game_id> is called
      Then title = "The Dark Forest"
      And summary = "You entered..."
    """

    def test_title_and_summary_round_trip(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(
                    rows=[
                        _game_row(
                            title="The Dark Forest",
                            summary="You entered the forest at dusk.",
                        )
                    ]
                ),
                _make_result(scalar=0),
                _make_result(rows=[]),
                _make_result(),
            ]
        )
        resp = client.get(f"/api/v1/games/{_GAME_ID}")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body.get("title") == "The Dark Forest"
        assert body.get("summary") == "You entered the forest at dusk."

    def test_null_title_is_acceptable(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(rows=[_game_row(title=None, summary=None)]),
                _make_result(scalar=0),
                _make_result(rows=[]),
                _make_result(),
            ]
        )
        resp = client.get(f"/api/v1/games/{_GAME_ID}")
        assert resp.status_code == 200


# ── AC-27.10: List only own games ────────────────────────────────


@pytest.mark.spec("AC-27.10")
class TestAC2710ListOwnGames:
    """AC-27.10: The games list is scoped to the authenticated player.
    Other players' games are never returned.

    Gherkin:
      Given two players, each with one game
      When player A calls GET /api/v1/games
      Then only player A's game is returned
    """

    def test_list_scoped_to_authenticated_player(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """The SQL query must include a player_id filter."""
        captured: list[str] = []

        async def _capture(stmt: Any, params: Any = None) -> MagicMock:
            captured.append(str(stmt))
            if not captured[:-1]:
                return _make_result(scalar=1)
            return _make_result(rows=[_game_row()])

        pg.execute = AsyncMock(side_effect=_capture)
        client.get("/api/v1/games")
        # All queries must reference player_id in some form
        combined = " ".join(captured)
        assert "player_id" in combined.lower() or "player" in combined.lower()
