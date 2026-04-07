"""Tests for the deliver pipeline stage."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from tta.models.turn import TurnState, TurnStatus
from tta.pipeline.stages.deliver import deliver_stage
from tta.pipeline.types import PipelineDeps


def _make_state(**overrides: object) -> TurnState:
    defaults: dict = {
        "session_id": uuid4(),
        "turn_number": 1,
        "player_input": "look around",
        "game_state": {},
    }
    defaults.update(overrides)
    return TurnState(**defaults)


def _make_deps() -> PipelineDeps:
    return PipelineDeps(
        llm=AsyncMock(),
        world=AsyncMock(),
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=AsyncMock(),
        safety_pre_gen=AsyncMock(),
        safety_post_gen=AsyncMock(),
    )


async def test_deliver_sets_complete_status() -> None:
    state = _make_state(narrative_output="You see a dark room.")
    result = await deliver_stage(state, _make_deps())

    assert result.status == TurnStatus.complete


async def test_deliver_sets_delivered_true() -> None:
    state = _make_state(narrative_output="You see a dark room.")
    result = await deliver_stage(state, _make_deps())

    assert result.delivered is True


async def test_deliver_preserves_narrative_output() -> None:
    narrative = "A dragon appears before you."
    state = _make_state(narrative_output=narrative)
    result = await deliver_stage(state, _make_deps())

    assert result.narrative_output == narrative


async def test_deliver_fails_without_narrative() -> None:
    """Missing narrative_output → status=failed."""
    state = _make_state(narrative_output=None)
    result = await deliver_stage(state, _make_deps())

    assert result.status == TurnStatus.failed
    assert result.delivered is False


async def test_deliver_fails_with_empty_narrative() -> None:
    """Empty string narrative → status=failed."""
    state = _make_state(narrative_output="")
    result = await deliver_stage(state, _make_deps())

    assert result.status == TurnStatus.failed
    assert result.delivered is False


async def test_original_state_not_mutated() -> None:
    state = _make_state(narrative_output="Some text.")
    result = await deliver_stage(state, _make_deps())

    assert state.delivered is False
    assert result.delivered is True
    assert state is not result
