"""Step definitions for player_identity.feature.

Tests player registration, duplicate handle, and profile retrieval.
Shared given/then steps live in tests/bdd/conftest.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenario, then, when

from tests.bdd.conftest import (
    _PLAYER_ID,
    _make_result,
)

FEATURE = "../features/player_identity.feature"


@scenario(FEATURE, "Register a new player")
def test_register_player():
    pass


@scenario(FEATURE, "Reject duplicate handle")
def test_duplicate_handle():
    pass


@scenario(FEATURE, "Retrieve player profile")
def test_get_profile():
    pass


# ---- GIVEN ----


@given(
    parsers.parse('a handle "{handle}" that is not taken'),
    target_fixture="ctx",
)
def handle_available(ctx: dict, handle: str) -> dict:
    ctx["handle"] = handle
    return ctx


@given(
    parsers.parse('a handle "{handle}" that is already registered'),
    target_fixture="ctx",
)
def handle_taken(ctx: dict, handle: str) -> dict:
    ctx["handle"] = handle
    ctx["taken"] = True
    return ctx


# ---- WHEN ----


@when("the visitor registers with that handle", target_fixture="ctx")
def register(ctx: dict, client: TestClient, pg: AsyncMock) -> dict:
    if ctx.get("taken"):
        pg.execute = AsyncMock(
            return_value=_make_result(rows=[{"id": _PLAYER_ID}]),
        )
    else:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),  # SELECT handle → None (available)
                _make_result(),  # INSERT player
                _make_result(),  # INSERT session
            ]
        )
    pg.commit = AsyncMock()
    ctx["response"] = client.post(
        "/api/v1/players",
        json={"handle": ctx["handle"]},
    )
    return ctx


@when("the player requests their profile", target_fixture="ctx")
def get_profile(ctx: dict, client: TestClient) -> dict:
    ctx["response"] = client.get("/api/v1/players/me")
    return ctx


# ---- THEN ----


@then("a session token is returned")
def has_token(ctx: dict) -> None:
    data = ctx["response"].json()["data"]
    assert data.get("session_token")


@then(parsers.parse('the response handle is "{handle}"'))
def response_handle(ctx: dict, handle: str) -> None:
    data = ctx["response"].json()["data"]
    assert data["handle"] == handle
