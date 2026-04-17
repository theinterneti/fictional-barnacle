"""Tests for SSE moderation events in the stream endpoint.

Verifies FR-24.08 (ModerationEvent emitted before NarrativeEvent chunks)
and FR-24.15 (non-moderated turns emit no ModerationEvent).
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
from tta.api.deps import get_current_player, get_pg, get_redis
from tta.config import Settings
from tta.models.player import Player
from tta.models.turn import TurnState, TurnStatus

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_PLAYER = Player(id=_PLAYER_ID, handle="Tester", created_at=_NOW)
_GAME_ID = uuid4()


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


def _make_result(
    rows: list[dict[str, Any]] | None = None,
) -> MagicMock:
    result = MagicMock()
    if rows is not None:
        objs = [SimpleNamespace(**r) for r in rows]
        result.one_or_none.return_value = objs[0] if objs else None
        result.all.return_value = objs
    else:
        result.one_or_none.return_value = None
        result.all.return_value = []
    return result


def _game_row(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "id": _GAME_ID,
        "player_id": _PLAYER_ID,
        "theme": "test-theme",
        "status": "active",
        "world_seed": "{}",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return defaults


class _FakeStore:
    """Deterministic turn result store — avoids asyncio.Event problems."""

    def __init__(self, state: TurnState) -> None:
        self._state = state

    async def wait_for_result(self, turn_id: str, timeout: float = 30.0) -> TurnState:
        return self._state

    async def publish(self, turn_id: str, result: object) -> None:
        pass


@pytest.fixture()
def pg() -> AsyncMock:
    mock = AsyncMock()
    mock.commit = AsyncMock()
    return mock


@pytest.fixture()
def mock_redis() -> AsyncMock:
    r = AsyncMock()
    r.incr = AsyncMock(return_value=1)
    r.zadd = AsyncMock(return_value=1)
    r.expire = AsyncMock(return_value=1)
    r.zremrangebyrank = AsyncMock(return_value=0)
    r.zcard = AsyncMock(return_value=1)
    r.exists = AsyncMock(return_value=0)
    r.zrange = AsyncMock(return_value=[])
    return r


@pytest.fixture()
def app(pg: AsyncMock, mock_redis: AsyncMock) -> FastAPI:
    application = create_app(_settings())
    application.dependency_overrides[get_current_player] = lambda: _PLAYER
    application.dependency_overrides[get_pg] = lambda: pg
    application.dependency_overrides[get_redis] = lambda: mock_redis
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


class TestSSEModerationEvent:
    """FR-24.08: Moderated turns emit a ModerationEvent before the
    NarrativeEvent chunks in the SSE stream (S10 §6.2)."""

    def test_moderated_turn_emits_moderation_event(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """A moderated turn result emits 'moderation' SSE event."""
        turn_id = uuid4()

        moderated_state = TurnState(
            session_id=_GAME_ID,
            turn_id=turn_id,
            turn_number=1,
            player_input="bad input",
            game_state={},
            status=TurnStatus.moderated,
            narrative_output="The story shifts direction...",
            safety_flags=["moderation:blocked"],
        )

        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),
                _make_result([{"id": turn_id, "turn_number": 1}]),
            ]
        )

        app = client.app
        app.state.turn_result_store = _FakeStore(moderated_state)  # type: ignore[union-attr]

        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")
        assert resp.status_code == 200

        body = resp.text
        assert "event: moderation" in body
        assert "event: narrative" in body

    def test_moderated_turn_has_moderation_before_narrative(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """ModerationEvent appears before NarrativeEvent chunks in stream."""
        turn_id = uuid4()

        moderated_state = TurnState(
            session_id=_GAME_ID,
            turn_id=turn_id,
            turn_number=1,
            player_input="bad input",
            game_state={},
            status=TurnStatus.moderated,
            narrative_output="The story shifts direction...",
            safety_flags=["moderation:blocked"],
        )

        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),
                _make_result([{"id": turn_id, "turn_number": 1}]),
            ]
        )

        app = client.app
        app.state.turn_result_store = _FakeStore(moderated_state)  # type: ignore[union-attr]

        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")
        body = resp.text

        mod_pos = body.index("event: moderation")
        narr_pos = body.index("event: narrative\n")
        assert mod_pos < narr_pos

    def test_normal_turn_no_moderation_event(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Non-moderated successful turn does NOT emit moderation event."""
        turn_id = uuid4()

        normal_state = TurnState(
            session_id=_GAME_ID,
            turn_id=turn_id,
            turn_number=1,
            player_input="look around",
            game_state={},
            status=TurnStatus.complete,
            narrative_output="You see a tavern.",
        )

        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),
                _make_result([{"id": turn_id, "turn_number": 1}]),
            ]
        )

        app = client.app
        app.state.turn_result_store = _FakeStore(normal_state)  # type: ignore[union-attr]

        resp = client.get(f"/api/v1/games/{_GAME_ID}/stream")
        body = resp.text

        assert "event: moderation" not in body
        assert "event: narrative\n" in body


class TestModerationEventModel:
    """ModerationEvent serialization and format_sse."""

    def test_serialization(self) -> None:
        from tta.models.events import ModerationEvent

        evt = ModerationEvent(reason="Content was redirected for your safety.")
        data = evt.model_dump()
        assert data["event_type"] == "moderation"
        assert data["reason"] == "Content was redirected for your safety."

    def test_format_sse(self) -> None:
        from tta.models.events import ModerationEvent

        evt = ModerationEvent(reason="Content was redirected for your safety.")
        sse = evt.format_sse(event_id=42)
        assert "event: moderation" in sse
        assert "id: 42" in sse
        assert "Content was redirected" in sse
