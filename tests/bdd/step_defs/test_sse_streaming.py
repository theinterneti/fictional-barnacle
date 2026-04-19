"""Step definitions for sse_streaming.feature.

Tests SSE stream connection, reconnect/replay, and non-owned game rejection.
Shared given/then steps live in tests/bdd/conftest.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenario, then, when

from tests.bdd.conftest import (
    _GAME_ID,
    _PLAYER_ID,
    _game_row,
    _make_result,
)

FEATURE = "../features/turns/sse_streaming.feature"


@scenario(FEATURE, "SSE stream connection opens successfully")
def test_sse_stream_opens():
    pass


@scenario(FEATURE, "Reconnect with Last-Event-ID replays buffered events")
def test_sse_reconnect_replay():
    pass


@scenario(FEATURE, "SSE stream for non-owned game is rejected")
def test_sse_non_owned_game():
    pass


# ---- GIVEN ----


@given("buffered SSE events exist for the game", target_fixture="ctx")
def buffered_sse_events(
    ctx: dict,
    pg: AsyncMock,
    mock_redis: AsyncMock,
) -> dict:
    """Seed the mock turn row and Redis buffer with a fake replayed event."""
    from uuid import uuid4

    turn_id = uuid4()
    # Seed the mock so the stream route can look up the current turn.
    pg.execute = AsyncMock(
        side_effect=[
            _make_result(rows=[_game_row()]),  # _get_owned_game
            _make_result(  # latest unprocessed turn query
                rows=[{"id": turn_id, "player_id": _PLAYER_ID}]
            ),
        ]
    )
    # Return one buffered raw event string for the replay path.
    # zrange(withscores=True) returns list[tuple[str, float]] (decode_responses=True).
    _RAW_EVENT = 'id: 2\nevent: narrative_end\ndata: {"text": "You look around."}\n\n'
    mock_redis.zrange = AsyncMock(return_value=[(_RAW_EVENT, 2.0)])
    # zrangebyscore returns list[str].
    mock_redis.zrangebyscore = AsyncMock(return_value=[_RAW_EVENT])
    ctx["buffered"] = True
    ctx["turn_id"] = turn_id
    ctx["raw_event"] = _RAW_EVENT
    return ctx


# ---- WHEN ----


def _setup_stream_pg(pg: AsyncMock) -> None:
    """Wire mock pg for a standard SSE stream open (no in-flight turn)."""

    pg.execute = AsyncMock(
        side_effect=[
            _make_result(rows=[_game_row()]),  # _get_owned_game
            _make_result(rows=[]),  # latest unprocessed turn query (none)
        ]
    )


def _seed_app_state(app) -> None:
    """Seed app.state entries not set by the test fixture."""

    from tta.api.turn_results import InMemoryTurnResultStore

    if not hasattr(app.state, "turn_result_store"):
        app.state.turn_result_store = InMemoryTurnResultStore()


@when("the player opens the SSE stream for their game", target_fixture="ctx")
def open_sse_stream(ctx: dict, app, client: TestClient, pg: AsyncMock) -> dict:
    _setup_stream_pg(pg)
    _seed_app_state(app)
    ctx["response"] = client.get(f"/api/v1/games/{_GAME_ID}/stream")
    return ctx


@when(
    parsers.parse('the player reconnects with Last-Event-ID "{last_id}"'),
    target_fixture="ctx",
)
def reconnect_with_last_event_id(
    ctx: dict,
    app,
    client: TestClient,
    pg: AsyncMock,
    last_id: str,
) -> dict:
    _seed_app_state(app)
    # Pre-seed the turn result store so replay_after + wait_for_result exits
    # immediately — without this the stream hangs in the keepalive loop.
    if "turn_id" in ctx:
        from uuid import uuid4

        from tta.models.turn import TurnState, TurnStatus

        app.state.turn_result_store._results[str(ctx["turn_id"])] = TurnState(
            session_id=uuid4(),
            turn_id=ctx["turn_id"],
            turn_number=1,
            player_input="I look around",
            game_state={},
            status=TurnStatus.complete,
        )
    ctx["response"] = client.get(
        f"/api/v1/games/{_GAME_ID}/stream",
        headers={"Last-Event-ID": last_id},
    )
    return ctx


@when(
    "the player opens the SSE stream for a game they do not own", target_fixture="ctx"
)
def open_sse_stream_not_owned(
    ctx: dict, app, client: TestClient, pg: AsyncMock
) -> dict:
    from uuid import uuid4

    other_game_id = uuid4()
    _seed_app_state(app)
    pg.execute = AsyncMock(
        side_effect=[
            _make_result(rows=[]),  # _get_owned_game returns empty → 404
        ]
    )
    ctx["response"] = client.get(f"/api/v1/games/{other_game_id}/stream")
    return ctx


# ---- THEN ----


@then("the SSE stream returns status 200")
def sse_stream_status_200(ctx: dict) -> None:
    assert ctx["response"].status_code == 200


@then("the SSE response has content type text/event-stream")
def sse_content_type(ctx: dict) -> None:
    content_type = ctx["response"].headers.get("content-type", "")
    assert "text/event-stream" in content_type


@then("the replayed events are returned in the stream")
def replayed_events_present(ctx: dict) -> None:
    assert ctx["response"].status_code == 200
    body = ctx["response"].text
    assert "event: narrative_end" in body, (
        f"Expected 'event: narrative_end' in SSE body; got: {body!r}"
    )
    assert "You look around." in body, (
        f"Expected payload text 'You look around.' in SSE body; got: {body!r}"
    )
