"""Step definitions for turn_pipeline.feature.

Tests turn submission and narrative response generation.
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

FEATURE = "../features/turn_pipeline.feature"


@scenario(FEATURE, "Submit a turn and receive acceptance")
def test_submit_turn_accepted():
    pass


@scenario(FEATURE, "Accepted turn includes a stream URL for narrative")
def test_narrative_generated():
    pass


@scenario(FEATURE, "Empty input is rejected")
def test_empty_input_is_rejected():
    pass


# ---- WHEN ----


def _setup_turn_pg(pg: AsyncMock) -> None:
    """Wire mock pg for a standard turn submission flow."""
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
    _setup_turn_pg(pg)
    ctx["response"] = client.post(
        f"/api/v1/games/{_GAME_ID}/turns",
        json={"input": text},
    )
    return ctx


@when("the player submits empty turn text", target_fixture="ctx")
def submit_empty_turn(ctx: dict, client: TestClient, pg: AsyncMock) -> dict:
    pg.execute = AsyncMock(
        side_effect=[
            _make_result(rows=[_game_row()]),  # _get_owned_game
        ]
    )
    ctx["response"] = client.post(
        f"/api/v1/games/{_GAME_ID}/turns",
        json={"input": ""},
    )
    return ctx


# ---- THEN ----


@then(parsers.parse("the turn is accepted with status {code:d}"))
def check_turn_status(ctx: dict, code: int) -> None:
    assert ctx["response"].status_code == code


@then("the response includes a stream URL")
def response_has_stream_url(ctx: dict) -> None:
    body = ctx["response"].json()
    assert "data" in body, f"Expected 'data' key in response: {body}"
    assert "stream_url" in body["data"], f"Expected 'stream_url' in data: {body}"


@then("the response is a nudge")
def response_is_nudge(ctx: dict) -> None:
    body = ctx["response"].json()
    assert "data" in body, f"Expected 'data' key in response: {body}"
    assert body["data"]["type"] == "nudge"
    assert len(body["data"]["message"]) > 0
