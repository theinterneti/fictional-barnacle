"""Tests for choice classification enrichment in understand stage."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from tta.llm.testing import MockLLMClient
from tta.models.choice import ChoiceType
from tta.models.turn import TurnState
from tta.pipeline.stages.understand import understand_stage
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


def _make_deps(*, llm: MockLLMClient | AsyncMock | None = None) -> PipelineDeps:
    safe_result = SafetyResult(safe=True)
    pre_input = AsyncMock()
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


# --- choice classification after intent ---


async def test_regex_match_populates_choice_classification() -> None:
    """Regex intent match also produces choice classification."""
    state = _make_state(player_input="go north")
    result = await understand_stage(state, _make_deps())

    assert result.choice_classification is not None
    assert ChoiceType.MOVEMENT in result.choice_classification.types


async def test_examine_classified_as_action() -> None:
    state = _make_state(player_input="look around")
    result = await understand_stage(state, _make_deps())

    assert result.choice_classification is not None
    assert ChoiceType.ACTION in result.choice_classification.types


async def test_talk_classified_as_dialogue() -> None:
    state = _make_state(player_input="talk to the merchant")
    result = await understand_stage(state, _make_deps())

    assert result.choice_classification is not None
    assert ChoiceType.DIALOGUE in result.choice_classification.types


async def test_llm_fallback_still_classifies_choice() -> None:
    """LLM-based intent still gets choice classification."""
    mock_llm = MockLLMClient(response="examine")
    state = _make_state(player_input="what is this place")
    result = await understand_stage(state, _make_deps(llm=mock_llm))

    assert result.choice_classification is not None
    # LLM fallback intent "examine" maps to action
    assert ChoiceType.ACTION in result.choice_classification.types


async def test_choice_classification_never_none_on_success() -> None:
    """Every successful understand stage populates choice_classification."""
    state = _make_state(player_input="use the key")
    result = await understand_stage(state, _make_deps())

    assert result.parsed_intent is not None
    assert result.choice_classification is not None


async def test_safety_blocked_skips_choice() -> None:
    """Blocked input has no choice classification."""
    safety = AsyncMock()
    safety.pre_generation_check = AsyncMock(
        return_value=SafetyResult(safe=False, flags=["blocked"])
    )
    deps = PipelineDeps(
        llm=MockLLMClient(),
        world=AsyncMock(),
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=safety,
        safety_pre_gen=AsyncMock(),
        safety_post_gen=AsyncMock(),
    )

    state = _make_state(player_input="bad input")
    result = await understand_stage(state, deps)

    assert result.choice_classification is None


async def test_original_state_choice_unchanged() -> None:
    """Original state's choice_classification stays None."""
    state = _make_state(player_input="go north")
    result = await understand_stage(state, _make_deps())

    assert state.choice_classification is None
    assert result.choice_classification is not None
