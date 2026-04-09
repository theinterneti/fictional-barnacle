"""Step definitions for game_session.feature.

Tests game session lifecycle: create, list, get, end, auth.
Shared given/then steps live in tests/bdd/conftest.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest_bdd import parsers, scenario, then, when

from tests.bdd.conftest import (
    _GAME_ID,
    _game_row,
    _make_result,
)

FEATURE = "../features/game_session.feature"


@scenario(FEATURE, "Create a new game session")
def test_create_game():
    pass


@scenario(FEATURE, "List games returns the player's sessions")
def test_list_games():
    pass


@scenario(FEATURE, "Get a specific game by ID")
def test_get_game_by_id():
    pass


@scenario(FEATURE, "End a game session")
def test_end_game():
    pass


@scenario(FEATURE, "Cannot create game without authentication")
def test_no_auth():
    pass


# ---- WHEN ----


@when("the player creates a new game", target_fixture="ctx")
def create_game(ctx: dict, client: TestClient, pg: AsyncMock) -> dict:
    pg.execute = AsyncMock(
        side_effect=[
            _make_result(scalar=0),  # count active games
            _make_result(),  # INSERT
        ]
    )
    pg.commit = AsyncMock()
    ctx["response"] = client.post("/api/v1/games", json={})
    return ctx


@when("the player lists their games", target_fixture="ctx")
def list_games(ctx: dict, client: TestClient, pg: AsyncMock) -> dict:
    pg.execute = AsyncMock(return_value=_make_result(rows=[_game_row()]))
    ctx["response"] = client.get("/api/v1/games")
    return ctx


@when("the player requests that game by ID", target_fixture="ctx")
def get_game(ctx: dict, client: TestClient, pg: AsyncMock) -> dict:
    pg.execute = AsyncMock(
        side_effect=[
            _make_result(rows=[_game_row()]),  # _get_owned_game
            _make_result(scalar=0),  # _get_turn_count
            _make_result(rows=[]),  # recent turns (.all())
            _make_result(),  # processing turn (.one_or_none())
        ]
    )
    ctx["response"] = client.get(f"/api/v1/games/{_GAME_ID}")
    return ctx


@when("the player ends that game", target_fixture="ctx")
def end_game(ctx: dict, client: TestClient, pg: AsyncMock) -> dict:
    pg.execute = AsyncMock(
        side_effect=[
            _make_result(rows=[_game_row()]),  # _get_owned_game
            _make_result(),  # UPDATE status → abandoned, deleted_at
            _make_result(scalar=5),  # _get_turn_count
        ]
    )
    pg.commit = AsyncMock()
    ctx["response"] = client.request(
        "DELETE",
        f"/api/v1/games/{_GAME_ID}",
        json={"confirm": True},
    )
    return ctx


@when("an unauthenticated player creates a game", target_fixture="ctx")
def unauth_create(ctx: dict, unauth_client: TestClient, pg: AsyncMock) -> dict:
    ctx["response"] = unauth_client.post("/api/v1/games", json={})
    return ctx


# ---- THEN ----


@then("the response contains a game ID")
def has_game_id(ctx: dict) -> None:
    data = ctx["response"].json()["data"]
    assert "game_id" in data
    assert data["game_id"]


@then(parsers.parse('the game status is "{status}"'))
def check_game_status(ctx: dict, status: str) -> None:
    data = ctx["response"].json()["data"]
    assert data["status"] == status


@then(parsers.parse("the response contains at least {n:d} game"))
def has_games(ctx: dict, n: int) -> None:
    body = ctx["response"].json()
    assert len(body["data"]) >= n
