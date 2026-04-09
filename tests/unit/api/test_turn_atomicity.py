"""Tests for turn atomicity & SSE error events (Issue #64, AC-23.6/7/8)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import get_current_player, get_pg
from tta.config import Settings
from tta.models.events import ErrorEvent
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
    game_id=None,
    player_id=None,
    status="active",
    world_seed=None,
    needs_recovery=False,
) -> dict[str, Any]:
    return {
        "id": game_id or _GAME_ID,
        "player_id": player_id or _PLAYER_ID,
        "theme": "test-theme",
        "status": status,
        "world_seed": world_seed or "{}",
        "created_at": _NOW,
        "updated_at": _NOW,
        "needs_recovery": needs_recovery,
    }


# ── Fixtures ──


@pytest.fixture()
def pg() -> AsyncMock:
    mock = AsyncMock()
    mock.commit = AsyncMock()
    return mock


@pytest.fixture()
def app(pg: AsyncMock) -> FastAPI:
    application = create_app(_settings())
    application.dependency_overrides[get_current_player] = lambda: _PLAYER
    application.dependency_overrides[get_pg] = lambda: pg
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ── AC-23.6: Turn atomicity on pipeline failure ──


class TestTurnAtomicity:
    """AC-23.6: When the LLM pipeline fails mid-turn, the system must mark
    the turn as 'failed', preserve any partial narrative, and NOT advance
    the turn counter."""

    @pytest.mark.asyncio
    async def test_dispatch_pipeline_marks_turn_failed(self) -> None:
        """Pipeline exception → fail_turn called with no partial narrative."""
        from tta.api.routes.games import _dispatch_pipeline
        from tta.models.turn import TurnStatus

        turn_repo = AsyncMock()
        turn_repo.fail_turn = AsyncMock()
        store = AsyncMock()
        store.publish = AsyncMock()

        app_state = SimpleNamespace(
            pipeline_deps=SimpleNamespace(turn_repo=turn_repo),
            turn_result_store=store,
        )
        turn_id = uuid4()

        with patch(
            "tta.api.routes.games.run_pipeline",
            side_effect=RuntimeError("LLM boom"),
        ):
            await _dispatch_pipeline(
                app_state=app_state,
                game_id=uuid4(),
                turn_id=turn_id,
                turn_number=1,
                player_input="test",
                game_state={},
            )

        # fail_turn was called (not complete_turn)
        turn_repo.fail_turn.assert_awaited_once()
        call_args = turn_repo.fail_turn.call_args
        assert call_args[0][0] == turn_id
        turn_repo.complete_turn.assert_not_awaited()

        # Result published to SSE store has failed status
        store.publish.assert_awaited_once()
        published_result = store.publish.call_args[0][1]
        assert published_result.status == TurnStatus.failed

    @pytest.mark.asyncio
    async def test_dispatch_pipeline_preserves_partial_narrative(self) -> None:
        """FR-23.18: partial narrative preserved on failure."""
        from tta.api.routes.games import _dispatch_pipeline
        from tta.models.turn import TurnState, TurnStatus

        partial_text = "You step into the darkness..."

        turn_repo = AsyncMock()
        turn_repo.fail_turn = AsyncMock()
        store = AsyncMock()
        store.publish = AsyncMock()

        app_state = SimpleNamespace(
            pipeline_deps=SimpleNamespace(turn_repo=turn_repo),
            turn_result_store=store,
        )
        turn_id = uuid4()
        game_id = uuid4()

        # Pipeline returns failed state with partial narrative
        failed_state = TurnState(
            session_id=game_id,
            turn_id=turn_id,
            turn_number=1,
            player_input="test",
            game_state={},
            status=TurnStatus.failed,
            narrative_output=partial_text,
        )

        with patch(
            "tta.api.routes.games.run_pipeline",
            return_value=failed_state,
        ):
            await _dispatch_pipeline(
                app_state=app_state,
                game_id=game_id,
                turn_id=turn_id,
                turn_number=1,
                player_input="test",
                game_state={},
            )

        # fail_turn called with partial narrative
        turn_repo.fail_turn.assert_awaited_once()
        call_kwargs = turn_repo.fail_turn.call_args
        assert call_kwargs[1].get("narrative_output") == partial_text or (
            len(call_kwargs[0]) > 1 and call_kwargs[0][1] == partial_text
        )

    @pytest.mark.asyncio
    async def test_dispatch_pipeline_failsafe_on_persist_error(self) -> None:
        """If fail_turn raises, fallback to update_status('failed')."""
        from tta.api.routes.games import _dispatch_pipeline

        turn_repo = AsyncMock()
        turn_repo.fail_turn = AsyncMock(side_effect=RuntimeError("DB down"))
        turn_repo.update_status = AsyncMock()
        store = AsyncMock()
        store.publish = AsyncMock()

        app_state = SimpleNamespace(
            pipeline_deps=SimpleNamespace(turn_repo=turn_repo),
            turn_result_store=store,
        )
        turn_id = uuid4()

        with patch(
            "tta.api.routes.games.run_pipeline",
            side_effect=RuntimeError("LLM fail"),
        ):
            await _dispatch_pipeline(
                app_state=app_state,
                game_id=uuid4(),
                turn_id=turn_id,
                turn_number=1,
                player_input="test",
                game_state={},
            )

        # Failsafe: update_status called after fail_turn raised
        turn_repo.update_status.assert_awaited_once_with(turn_id, "failed")

    def test_max_turn_number_skips_failed_turns(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """FR-23.17: failed turns don't advance the counter.

        Submit a turn → verify the SQL for max turn number filters
        to status='complete' only.
        """
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # advisory lock
                _make_result(),  # in-flight check (none)
                _make_result(scalar=2),  # _get_max_turn_number → 2
                _make_result(),  # INSERT turn
                _make_result(),  # commit is separate
            ]
        )

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "look around"},
        )

        assert resp.status_code == 202
        # Verify _get_max_turn_number query filters by status='complete'
        calls = pg.execute.call_args_list
        max_turn_call = calls[3]
        sql_text = str(max_turn_call[0][0].text)
        assert "status = 'complete'" in sql_text


# ── AC-23.7: Concurrent turn rejection ──


class TestConcurrentTurnRejection:
    """AC-23.7: Submitting a second turn while one is processing returns
    409 with the standard error envelope."""

    def test_concurrent_turn_returns_409_with_envelope(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # advisory lock
                _make_result([{"id": uuid4()}]),  # in-flight turn exists
            ]
        )

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "test"},
        )

        assert resp.status_code == 409
        envelope = resp.json()["error"]
        assert envelope["code"] == "TURN_IN_PROGRESS"
        assert "message" in envelope
        assert "correlation_id" in envelope


# ── AC-23.8: SSE error event format ──


class TestSSEErrorEvents:
    """AC-23.8: SSE error events include code, message, correlation_id,
    retry_after_seconds, and stream closes cleanly after error."""

    def test_error_event_model_serialization(self) -> None:
        """ErrorEvent includes all standard envelope fields."""
        evt = ErrorEvent(
            code="PIPELINE_FAILED",
            message="Turn processing failed.",
            correlation_id="req-abc123",
            retry_after_seconds=5,
            details={"reason": "llm_timeout"},
        )
        data = evt.model_dump()
        assert data["code"] == "PIPELINE_FAILED"
        assert data["message"] == "Turn processing failed."
        assert data["correlation_id"] == "req-abc123"
        assert data["retry_after_seconds"] == 5
        assert data["details"] == {"reason": "llm_timeout"}

    def test_error_event_optional_fields_default_none(self) -> None:
        """Optional fields default to None when not provided."""
        evt = ErrorEvent(code="TEST", message="test")
        assert evt.correlation_id is None
        assert evt.retry_after_seconds is None
        assert evt.details is None

    def test_stream_no_turn_emits_error_event(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Stream with no turn found emits error SSE event."""
        from tta.api.turn_results import InMemoryTurnResultStore

        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # latest turn query → none
            ]
        )

        app = client.app
        app.state.turn_result_store = InMemoryTurnResultStore()  # type: ignore[union-attr]

        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.text
        assert "NO_TURN_FOUND" in body
        assert "event: error" in body

    def test_stream_failed_turn_emits_error_with_retry(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Failed turn result emits error event with retry_after_seconds."""
        from tta.models.turn import TurnState, TurnStatus

        turn_id = uuid4()

        # Deterministic fake store that returns the failed state immediately,
        # avoiding InMemoryTurnResultStore's asyncio.Event internals which
        # interact poorly with TestClient's thread-based execution.
        failed_state = TurnState(
            session_id=_GAME_ID,
            turn_id=turn_id,
            turn_number=1,
            player_input="test",
            game_state={},
            status=TurnStatus.failed,
        )

        class _FakeStore:
            async def wait_for_result(
                self, turn_id: str, timeout: float = 30.0
            ) -> TurnState:
                return failed_state

            async def publish(self, turn_id: str, result: object) -> None:
                pass

        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result([{"id": turn_id, "turn_number": 1}]),  # latest turn
            ]
        )

        app = client.app
        app.state.turn_result_store = _FakeStore()  # type: ignore[union-attr]

        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")

        assert resp.status_code == 200
        body = resp.text
        assert "PIPELINE_FAILED" in body
        assert "retry_after_seconds" in body or "retry" in body.lower()

    def test_error_event_format_sse_includes_all_fields(self) -> None:
        """ErrorEvent.format_sse renders code, message, retry, correlation."""
        evt = ErrorEvent(
            code="PIPELINE_TIMEOUT",
            message="Turn processing timed out.",
            correlation_id="req-xyz",
            retry_after_seconds=5,
        )
        formatted = evt.format_sse("1")
        assert "event: error" in formatted
        assert "PIPELINE_TIMEOUT" in formatted
        assert "retry_after_seconds" in formatted
        assert "req-xyz" in formatted
