"""Step definitions for turn_flow.feature.

Tests full turn submission flow: 202 + stream URL, ended game conflict,
empty input rejection.  Shared given/then steps live in tests/bdd/conftest.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenario, then, when

from tests.bdd.conftest import (
    _GAME_ID,
    _game_row,
    _make_result,
)

FEATURE = "../features/turns/turn_flow.feature"


@scenario(FEATURE, "Submit a turn and receive a stream URL")
def test_submit_turn_receives_stream_url():
    pass


@scenario(FEATURE, "Submitting turn on an ended game returns conflict")
def test_turn_on_ended_game():
    pass


@scenario(FEATURE, "Submitting empty input returns validation error")
def test_empty_input_rejected():
    pass


# ---- GIVEN ----


@given("the player has an ended game", target_fixture="ctx")
def ended_game(ctx: dict, pg: AsyncMock) -> dict:
    pg.execute = AsyncMock(
        side_effect=[
            _make_result(rows=[_game_row(status="ended")]),  # _get_owned_game
        ]
    )
    ctx["game_id"] = _GAME_ID
    return ctx


# ---- WHEN ----


def _setup_turn_pg(pg: AsyncMock) -> None:
    """Wire mock pg for a standard turn submission flow (6 calls)."""
    pg.execute = AsyncMock(
        side_effect=[
            _make_result(rows=[_game_row()]),  # _get_owned_game
            _make_result(),  # advisory lock
            _make_result(),  # in-flight check (none)
            _make_result(scalar=0),  # _get_max_turn_number
            _make_result(),  # INSERT turn
            _make_result(),  # UPDATE last_played_at
        ]
    )
    pg.commit = AsyncMock()


@when(
    parsers.parse('the player submits turn text "{text}"'),
    target_fixture="ctx",
)
def submit_turn(ctx: dict, client: TestClient, pg: AsyncMock, text: str) -> dict:
    if pg.execute.side_effect is None:
        # happy-path — no prior given step configured the mock
        _setup_turn_pg(pg)
    # else: side_effect already configured (e.g. ended-game given step)
    ctx["response"] = client.post(
        f"/api/v1/games/{_GAME_ID}/turns",
        json={"input": text},
    )
    return ctx


@when("the player submits empty turn text", target_fixture="ctx")
def submit_empty_turn(ctx: dict, client: TestClient) -> dict:
    # Send request without the required `input` field — Pydantic rejects 422
    # before the route body runs, so no DB mock is needed.
    ctx["response"] = client.post(
        f"/api/v1/games/{_GAME_ID}/turns",
        json={},
    )
    return ctx


# ---- THEN ----


@then("the response body contains a stream URL")
def response_has_stream_url(ctx: dict) -> None:
    body = ctx["response"].json()
    assert "data" in body
    assert "stream_url" in body["data"]
    stream_url = body["data"]["stream_url"]
    assert stream_url.startswith("/api/v1/games/")
    assert stream_url.endswith("/stream")
