"""Unit tests for GameSnapshotService (AC-12.04)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tta.game.snapshot import GameSnapshotService
from tta.models.game import GameState


def _make_state(turn: int = 3) -> GameState:
    return GameState(
        session_id=str(uuid4()),
        turn_number=turn,
        current_location_id="forest_clearing",
    )


def _make_row(turn: int, state: GameState) -> MagicMock:
    row = MagicMock()
    row.turn_number = turn
    row.world_state = json.loads(state.model_dump_json())
    return row


@pytest.fixture
def session_factory() -> MagicMock:
    """A mock async_sessionmaker that returns an async context manager."""
    sess = AsyncMock()
    sess.execute = AsyncMock()
    sess.commit = AsyncMock()
    sess.__aenter__ = AsyncMock(return_value=sess)
    sess.__aexit__ = AsyncMock(return_value=False)
    sf = MagicMock()
    sf.return_value = sess
    sf.return_value.__aenter__ = AsyncMock(return_value=sess)
    sf.return_value.__aexit__ = AsyncMock(return_value=False)
    return sf


class TestSaveSnapshot:
    async def test_save_executes_insert(self, session_factory: MagicMock) -> None:
        svc = GameSnapshotService(session_factory)
        gid = uuid4()
        state = _make_state(turn=5)

        await svc.save_snapshot(gid, state)

        sess = session_factory.return_value.__aenter__.return_value
        sess.execute.assert_awaited_once()
        call_args = sess.execute.call_args
        sql_text = str(call_args.args[0])
        assert "game_snapshots" in sql_text
        assert "INSERT" in sql_text

    async def test_save_passes_correct_turn_number(
        self, session_factory: MagicMock
    ) -> None:
        svc = GameSnapshotService(session_factory)
        gid = uuid4()
        state = _make_state(turn=7)

        await svc.save_snapshot(gid, state)

        sess = session_factory.return_value.__aenter__.return_value
        params = sess.execute.call_args.args[1]
        assert params["turn"] == 7
        assert params["gid"] == gid

    async def test_save_commits(self, session_factory: MagicMock) -> None:
        svc = GameSnapshotService(session_factory)
        await svc.save_snapshot(uuid4(), _make_state())
        sess = session_factory.return_value.__aenter__.return_value
        sess.commit.assert_awaited_once()

    async def test_payload_is_valid_json(self, session_factory: MagicMock) -> None:
        svc = GameSnapshotService(session_factory)
        state = _make_state(turn=2)
        await svc.save_snapshot(uuid4(), state)

        sess = session_factory.return_value.__aenter__.return_value
        params = sess.execute.call_args.args[1]
        # payload param must be a JSON-serialisable string
        parsed = json.loads(params["payload"])
        assert parsed["turn_number"] == 2


class TestGetLatestSnapshot:
    async def test_returns_none_when_no_rows(
        self, session_factory: MagicMock
    ) -> None:
        svc = GameSnapshotService(session_factory)
        sess = session_factory.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.one_or_none = MagicMock(return_value=None)
        sess.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_latest_snapshot(uuid4())

        assert result is None

    async def test_returns_turn_number_and_state(
        self, session_factory: MagicMock
    ) -> None:
        svc = GameSnapshotService(session_factory)
        state = _make_state(turn=4)
        row = _make_row(4, state)

        sess = session_factory.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.one_or_none = MagicMock(return_value=row)
        sess.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_latest_snapshot(uuid4())

        assert result is not None
        turn_number, restored = result
        assert turn_number == 4
        assert restored.turn_number == state.turn_number
        assert restored.current_location_id == state.current_location_id

    async def test_handles_string_world_state(
        self, session_factory: MagicMock
    ) -> None:
        """world_state may arrive as JSON string (non-asyncpg drivers)."""
        svc = GameSnapshotService(session_factory)
        state = _make_state(turn=6)
        row = MagicMock()
        row.turn_number = 6
        row.world_state = state.model_dump_json()  # raw string

        sess = session_factory.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.one_or_none = MagicMock(return_value=row)
        sess.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_latest_snapshot(uuid4())

        assert result is not None
        _, restored = result
        assert restored.turn_number == 6
