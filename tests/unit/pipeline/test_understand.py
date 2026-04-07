"""Tests for the understand pipeline stage."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tta.llm.testing import MockLLMClient
from tta.models.turn import TurnState, TurnStatus
from tta.pipeline.stages.understand import (
    understand_stage,
)
from tta.pipeline.types import PipelineDeps
from tta.safety.hooks import SafetyResult


def _make_state(**overrides: object) -> TurnState:
    defaults: dict = {
        "session_id": uuid4(),
        "turn_number": 1,
        "player_input": "look around",
        "game_state": {},
    }
    defaults.update(overrides)
    return TurnState(**defaults)


def _make_deps(
    *,
    llm: MockLLMClient | AsyncMock | None = None,
    safety_pre_input: AsyncMock | None = None,
) -> PipelineDeps:
    safe_result = SafetyResult(safe=True)
    pre_input = safety_pre_input or AsyncMock()
    if safety_pre_input is None:
        pre_input.pre_generation_check = AsyncMock(return_value=safe_result)
    return PipelineDeps(
        llm=llm or MockLLMClient(),
        world=AsyncMock(),
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=pre_input,
        safety_pre_gen=AsyncMock(),
        safety_post_gen=AsyncMock(),
    )


# --- regex classification ---


@pytest.mark.parametrize(
    ("player_input", "expected_intent"),
    [
        ("go north", "move"),
        ("walk to the door", "move"),
        ("move east", "move"),
        ("run away", "move"),
        ("enter the cave", "move"),
        ("leave the room", "move"),
        ("look around", "examine"),
        ("examine the chest", "examine"),
        ("inspect the lock", "examine"),
        ("search the room", "examine"),
        ("talk to the merchant", "talk"),
        ("say hello", "talk"),
        ("ask about the sword", "talk"),
        ("tell the guard my name", "talk"),
        ("use the key", "use"),
        ("take the sword", "use"),
        ("grab the rope", "use"),
        ("open the door", "use"),
        ("drop the shield", "use"),
        ("help", "meta"),
        ("save", "meta"),
        ("quit", "meta"),
        ("inventory", "meta"),
        ("status", "meta"),
    ],
)
async def test_regex_classification(player_input: str, expected_intent: str) -> None:
    state = _make_state(player_input=player_input)
    deps = _make_deps()
    result = await understand_stage(state, deps)
    assert result.parsed_intent is not None
    assert result.parsed_intent.intent == expected_intent
    assert result.parsed_intent.confidence == 0.9


async def test_meta_takes_priority_over_move_for_exit() -> None:
    """'exit' should classify as meta, not move."""
    state = _make_state(player_input="exit")
    deps = _make_deps()
    result = await understand_stage(state, deps)
    assert result.parsed_intent is not None
    assert result.parsed_intent.intent == "meta"


async def test_meta_takes_priority_over_move_for_quit() -> None:
    state = _make_state(player_input="quit the game")
    deps = _make_deps()
    result = await understand_stage(state, deps)
    assert result.parsed_intent is not None
    assert result.parsed_intent.intent == "meta"


# --- LLM fallback ---


async def test_llm_fallback_for_ambiguous_input() -> None:
    """Input with no regex match falls back to LLM classification."""
    mock_llm = MockLLMClient(response="examine")
    state = _make_state(player_input="what is this place")
    deps = _make_deps(llm=mock_llm)
    result = await understand_stage(state, deps)

    assert result.parsed_intent is not None
    assert result.parsed_intent.intent == "examine"
    assert result.parsed_intent.confidence == 0.7
    assert len(mock_llm.call_history) == 1
    assert mock_llm.call_history[0]["role"] == "classification"


async def test_llm_fallback_unknown_intent_becomes_other() -> None:
    """LLM returns an unrecognized intent → defaults to 'other'."""
    mock_llm = MockLLMClient(response="dance")
    state = _make_state(player_input="pirouette gracefully")
    deps = _make_deps(llm=mock_llm)
    result = await understand_stage(state, deps)

    assert result.parsed_intent is not None
    assert result.parsed_intent.intent == "other"


async def test_llm_failure_returns_other() -> None:
    """LLM exception → graceful fallback to 'other'."""
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
    state = _make_state(player_input="do something weird")
    deps = _make_deps(llm=llm)
    result = await understand_stage(state, deps)

    assert result.parsed_intent is not None
    assert result.parsed_intent.intent == "other"
    assert result.parsed_intent.confidence == 0.3
    assert result.status == TurnStatus.processing


# --- safety blocking ---


async def test_safety_blocks_input() -> None:
    """Safety hook blocks → status=failed + safety_flags set."""
    blocked_result = SafetyResult(safe=False, flags=["profanity"])
    safety = AsyncMock()
    safety.pre_generation_check = AsyncMock(return_value=blocked_result)
    state = _make_state(player_input="bad input")
    deps = _make_deps(safety_pre_input=safety)
    result = await understand_stage(state, deps)

    assert result.status == TurnStatus.failed
    assert "profanity" in result.safety_flags
    assert result.parsed_intent is None


async def test_safety_pass_continues_classification() -> None:
    """Safety passes → classification runs normally."""
    state = _make_state(player_input="look around")
    deps = _make_deps()
    result = await understand_stage(state, deps)

    assert result.status == TurnStatus.processing
    assert result.parsed_intent is not None


# --- immutability ---


async def test_original_state_not_mutated() -> None:
    """Understand stage returns new state, doesn't mutate input."""
    state = _make_state(player_input="go north")
    deps = _make_deps()
    result = await understand_stage(state, deps)

    assert state.parsed_intent is None  # original unchanged
    assert result.parsed_intent is not None  # new state enriched
    assert state is not result
