"""Tests for InMemoryTurnResultStore."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from tta.api.turn_results import InMemoryTurnResultStore
from tta.models.turn import TurnState, TurnStatus


def _make_result(*, status: TurnStatus = TurnStatus.complete) -> TurnState:
    return TurnState(
        session_id=uuid4(),
        turn_number=1,
        player_input="look around",
        game_state={},
        status=status,
        narrative_output="Once upon a time...",
    )


@pytest.fixture
def store() -> InMemoryTurnResultStore:
    return InMemoryTurnResultStore()


class TestInMemoryTurnResultStore:
    """Unit tests for the in-memory implementation."""

    async def test_publish_then_wait(self, store: InMemoryTurnResultStore):
        """Result published before waiter connects (late-client path)."""
        turn_id = str(uuid4())
        result = _make_result()

        await store.publish(turn_id, result)
        got = await store.wait_for_result(turn_id, timeout=1.0)

        assert got is not None
        assert got.status == TurnStatus.complete
        assert got.narrative_output == "Once upon a time..."

    async def test_wait_then_publish(self, store: InMemoryTurnResultStore):
        """Waiter subscribes before result is published."""
        turn_id = str(uuid4())
        result = _make_result()

        async def delayed_publish():
            await asyncio.sleep(0.05)
            await store.publish(turn_id, result)

        task = asyncio.create_task(delayed_publish())
        got = await store.wait_for_result(turn_id, timeout=5.0)
        await task

        assert got is not None
        assert got.status == TurnStatus.complete

    async def test_timeout_returns_none(self, store: InMemoryTurnResultStore):
        """Timeout returns None without raising."""
        got = await store.wait_for_result("nonexistent", timeout=0.1)
        assert got is None

    async def test_concurrent_waiters(self, store: InMemoryTurnResultStore):
        """Multiple waiters on the same turn_id all get the result."""
        turn_id = str(uuid4())
        result = _make_result()

        async def delayed_publish():
            await asyncio.sleep(0.05)
            await store.publish(turn_id, result)

        task = asyncio.create_task(delayed_publish())
        got1, got2 = await asyncio.gather(
            store.wait_for_result(turn_id, timeout=5.0),
            store.wait_for_result(turn_id, timeout=5.0),
        )
        await task

        assert got1 is not None
        assert got2 is not None
        assert got1.status == result.status
        assert got2.status == result.status
        assert got1.narrative_output == result.narrative_output
        assert got2.narrative_output == result.narrative_output
        assert got1.session_id == result.session_id
        assert got2.session_id == result.session_id
        assert got1.turn_number == result.turn_number
        assert got2.turn_number == result.turn_number
        assert got1.player_input == result.player_input
        assert got2.player_input == result.player_input
        assert got1.game_state == result.game_state
        assert got2.game_state == result.game_state

    async def test_event_cleanup_after_wait(self, store: InMemoryTurnResultStore):
        """Internal event dict is cleaned up after wait completes."""
        turn_id = str(uuid4())
        await store.publish(turn_id, _make_result())
        await store.wait_for_result(turn_id, timeout=1.0)

        # Event should be cleaned up (only created if late-client path
        # wasn't taken, but either way no lingering events)
        assert turn_id not in store._events

    async def test_result_persists_after_read(self, store: InMemoryTurnResultStore):
        """Results are NOT deleted on read (multiple consumers)."""
        turn_id = str(uuid4())
        await store.publish(turn_id, _make_result())

        first = await store.wait_for_result(turn_id, timeout=1.0)
        second = await store.wait_for_result(turn_id, timeout=1.0)

        assert first is not None
        assert second is not None

    async def test_failed_turn_result(self, store: InMemoryTurnResultStore):
        """Failed turn results are delivered correctly."""
        turn_id = str(uuid4())
        result = _make_result(status=TurnStatus.failed)

        await store.publish(turn_id, result)
        got = await store.wait_for_result(turn_id, timeout=1.0)

        assert got is not None
        assert got.status == TurnStatus.failed

    async def test_different_turn_ids_isolated(self, store: InMemoryTurnResultStore):
        """Results are isolated per turn_id."""
        id_a = str(uuid4())
        id_b = str(uuid4())
        result_a = _make_result()
        result_a.narrative_output = "A"
        result_b = _make_result()
        result_b.narrative_output = "B"

        await store.publish(id_a, result_a)
        await store.publish(id_b, result_b)

        got_a = await store.wait_for_result(id_a, timeout=1.0)
        got_b = await store.wait_for_result(id_b, timeout=1.0)

        assert got_a is not None
        assert got_a.narrative_output == "A"
        assert got_b is not None
        assert got_b.narrative_output == "B"
