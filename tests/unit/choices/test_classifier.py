"""Tests for the choice classifier (S05 FR-2, AC-5.2)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tta.choices.classifier import (
    INTENT_CHOICE_MAP,
    classify_choice,
    classify_choice_with_llm,
)
from tta.llm.client import LLMResponse
from tta.models.choice import (
    ChoiceType,
    ImpactLevel,
    Reversibility,
)
from tta.models.turn import TokenCount

_ZERO_TOKENS = TokenCount(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def _llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model_used="test",
        token_count=_ZERO_TOKENS,
        latency_ms=0.0,
    )


class TestIntentChoiceMap:
    """All intents map to a valid choice type."""

    def test_all_intents_mapped(self) -> None:
        expected_intents = {"move", "examine", "talk", "use", "meta", "other"}
        assert expected_intents == set(INTENT_CHOICE_MAP.keys())

    def test_move_maps_to_movement(self) -> None:
        assert INTENT_CHOICE_MAP["move"] == ChoiceType.MOVEMENT

    def test_talk_maps_to_dialogue(self) -> None:
        assert INTENT_CHOICE_MAP["talk"] == ChoiceType.DIALOGUE


class TestClassifyChoice:
    """Rules-based choice classification."""

    def test_basic_movement(self) -> None:
        cc = classify_choice("Go to the tavern", "move")
        assert ChoiceType.MOVEMENT in cc.types
        assert cc.confidence == 0.9

    def test_basic_dialogue(self) -> None:
        cc = classify_choice("Ask the merchant about the map", "talk")
        assert ChoiceType.DIALOGUE in cc.types

    def test_basic_action(self) -> None:
        cc = classify_choice("Pick up the sword", "use")
        assert ChoiceType.ACTION in cc.types

    def test_refusal_detected(self) -> None:
        cc = classify_choice("I refuse to help the king", "talk")
        assert ChoiceType.REFUSAL in cc.types
        assert ChoiceType.DIALOGUE in cc.types

    def test_moral_detected(self) -> None:
        cc = classify_choice("I steal the merchant's gold", "use")
        assert ChoiceType.MORAL in cc.types
        assert ChoiceType.ACTION in cc.types

    def test_strategic_detected(self) -> None:
        cc = classify_choice("Set up an ambush near the bridge", "use")
        assert ChoiceType.STRATEGIC in cc.types

    def test_high_impact_detected(self) -> None:
        cc = classify_choice("Kill the dragon", "use")
        assert cc.impact == ImpactLevel.CONSEQUENTIAL
        assert cc.reversibility == Reversibility.PERMANENT

    def test_moral_gets_significant_reversibility(self) -> None:
        cc = classify_choice("Betray your friend", "talk")
        assert cc.reversibility in (
            Reversibility.SIGNIFICANT,
            Reversibility.PERMANENT,
        )

    def test_normal_impact_default(self) -> None:
        cc = classify_choice("Look around the room", "examine")
        assert cc.impact == ImpactLevel.ATMOSPHERIC
        assert cc.reversibility == Reversibility.MODERATE

    def test_do_nothing_is_refusal(self) -> None:
        cc = classify_choice("Do nothing", "other")
        assert ChoiceType.REFUSAL in cc.types

    def test_walk_away_is_refusal(self) -> None:
        cc = classify_choice("Walk away from the conversation", "move")
        assert ChoiceType.REFUSAL in cc.types
        assert ChoiceType.MOVEMENT in cc.types

    def test_negotiate_is_strategic(self) -> None:
        cc = classify_choice("Negotiate a trade deal", "talk")
        assert ChoiceType.STRATEGIC in cc.types
        assert ChoiceType.DIALOGUE in cc.types

    def test_unknown_intent_defaults_to_action(self) -> None:
        cc = classify_choice("Something weird", "unknown_intent")
        assert ChoiceType.ACTION in cc.types


class TestClassifyChoiceWithLLM:
    """LLM-based classification fallback."""

    @pytest.mark.asyncio
    async def test_successful_llm_classification(self) -> None:
        llm = AsyncMock()
        llm.generate.return_value = _llm_response("moral, dialogue")
        cc = await classify_choice_with_llm("Help the wounded thief", "talk", llm)
        assert ChoiceType.MORAL in cc.types
        assert ChoiceType.DIALOGUE in cc.types
        assert cc.confidence == 0.7

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_rules(self) -> None:
        llm = AsyncMock()
        llm.generate.side_effect = RuntimeError("API error")
        cc = await classify_choice_with_llm("Go north", "move", llm)
        assert ChoiceType.MOVEMENT in cc.types
        assert cc.confidence == 0.5

    @pytest.mark.asyncio
    async def test_llm_invalid_types_falls_back(self) -> None:
        llm = AsyncMock()
        llm.generate.return_value = _llm_response("invalid_type, nonsense")
        cc = await classify_choice_with_llm("Walk north", "move", llm)
        # Falls back to rules since no valid types parsed
        assert ChoiceType.MOVEMENT in cc.types
        assert cc.confidence == 0.5

    @pytest.mark.asyncio
    async def test_llm_partial_valid_types(self) -> None:
        llm = AsyncMock()
        llm.generate.return_value = _llm_response("moral, invalid_garbage")
        cc = await classify_choice_with_llm("Save the child", "use", llm)
        assert ChoiceType.MORAL in cc.types
        assert cc.confidence == 0.7
