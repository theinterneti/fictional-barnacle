"""Tests for the context pipeline stage."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from tta.models.turn import ParsedIntent, TurnState
from tta.pipeline.stages.context import context_stage
from tta.pipeline.types import PipelineDeps


def _make_state(**overrides: object) -> TurnState:
    defaults: dict = {
        "session_id": uuid4(),
        "turn_number": 1,
        "player_input": "look around",
        "game_state": {"location": "tavern", "hp": 100},
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


async def test_context_includes_game_state() -> None:
    state = _make_state()
    result = await context_stage(state, _make_deps())

    assert result.world_context is not None
    assert result.world_context["game_state"] == {
        "location": "tavern",
        "hp": 100,
    }


async def test_context_includes_intent() -> None:
    state = _make_state(parsed_intent=ParsedIntent(intent="examine", confidence=0.9))
    result = await context_stage(state, _make_deps())

    assert result.world_context is not None
    assert result.world_context["intent"] == "examine"


async def test_context_intent_defaults_to_unknown() -> None:
    state = _make_state(parsed_intent=None)
    result = await context_stage(state, _make_deps())

    assert result.world_context is not None
    assert result.world_context["intent"] == "unknown"


async def test_context_includes_turn_number() -> None:
    state = _make_state(turn_number=5)
    result = await context_stage(state, _make_deps())

    assert result.world_context is not None
    assert result.world_context["turn_number"] == 5


async def test_context_includes_session_id() -> None:
    sid = uuid4()
    state = _make_state(session_id=sid)
    result = await context_stage(state, _make_deps())

    assert result.world_context is not None
    assert result.world_context["session_id"] == str(sid)


async def test_context_partial_is_true_for_stub() -> None:
    """V1 stub sets context_partial=True."""
    state = _make_state()
    result = await context_stage(state, _make_deps())
    assert result.context_partial is True


async def test_original_state_not_mutated() -> None:
    state = _make_state()
    result = await context_stage(state, _make_deps())

    assert state.world_context is None
    assert result.world_context is not None
    assert state is not result
