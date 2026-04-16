"""First playable turn — end-to-end pipeline test with mock LLM.

Validates the entire pipeline path: understand → context → generate → deliver
with a mock LLM client and in-memory world service. This test proves
the vertical slice works without external services.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tta.llm.roles import ModelRole
from tta.llm.testing import MockLLMClient
from tta.models.turn import TurnState, TurnStatus
from tta.persistence.memory import InMemorySessionRepository, InMemoryTurnRepository
from tta.pipeline.orchestrator import run_pipeline
from tta.pipeline.types import PipelineDeps
from tta.safety.hooks import PassthroughHook
from tta.world.memory_service import InMemoryWorldService


def _build_deps(
    *,
    llm_response: str = "You step through the creaking door into a dimly lit tavern.",
) -> PipelineDeps:
    """Build pipeline deps with all in-memory fakes."""
    from tests.unit.pipeline.conftest import make_mock_registry

    return PipelineDeps(
        llm=MockLLMClient(response=llm_response),
        world=InMemoryWorldService(),
        session_repo=InMemorySessionRepository(),
        turn_repo=InMemoryTurnRepository(),
        safety_pre_input=PassthroughHook(),
        safety_pre_gen=PassthroughHook(),
        safety_post_gen=PassthroughHook(),
        prompt_registry=make_mock_registry(),
    )


def _fresh_state(player_input: str = "look around") -> TurnState:
    return TurnState(
        session_id=uuid4(),
        turn_number=1,
        player_input=player_input,
        game_state={"location": "tavern", "turn": 1},
    )


# ------------------------------------------------------------------
# Core pipeline path
# ------------------------------------------------------------------


class TestFirstPlayableTurn:
    """Pipeline produces narrative output for a valid player input."""

    async def test_pipeline_completes_successfully(self) -> None:
        deps = _build_deps()
        state = _fresh_state("look around the room")

        result = await run_pipeline(state, deps)

        assert result.status == TurnStatus.complete

    async def test_pipeline_produces_narrative(self) -> None:
        deps = _build_deps(llm_response="The tavern is warm and inviting.")
        state = _fresh_state("look around")

        result = await run_pipeline(state, deps)

        assert result.narrative_output is not None
        assert len(result.narrative_output) > 0
        assert "tavern" in result.narrative_output.lower()

    async def test_pipeline_classifies_intent(self) -> None:
        deps = _build_deps()
        state = _fresh_state("examine the old painting")

        result = await run_pipeline(state, deps)

        assert result.parsed_intent is not None
        assert result.parsed_intent.intent == "examine"
        assert result.parsed_intent.confidence > 0

    async def test_pipeline_assembles_world_context(self) -> None:
        deps = _build_deps()
        state = _fresh_state("go north")

        result = await run_pipeline(state, deps)

        # Context fallback to game_state dict (no world graph)
        assert result.world_context is not None
        assert "intent" in result.world_context

    async def test_pipeline_tracks_model_used(self) -> None:
        deps = _build_deps()
        state = _fresh_state("talk to bartender")

        result = await run_pipeline(state, deps)

        assert result.model_used == "mock"

    async def test_pipeline_tracks_token_count(self) -> None:
        deps = _build_deps()
        state = _fresh_state("use the key on the door")

        result = await run_pipeline(state, deps)

        assert result.token_count is not None
        assert result.token_count.total_tokens > 0

    async def test_pipeline_marks_delivered(self) -> None:
        deps = _build_deps()
        state = _fresh_state("look around")

        result = await run_pipeline(state, deps)

        assert result.delivered is True


# ------------------------------------------------------------------
# Intent classification coverage
# ------------------------------------------------------------------


class TestIntentClassification:
    """Rules-first classification resolves common input patterns."""

    @pytest.mark.parametrize(
        ("player_input", "expected_intent"),
        [
            ("go north", "move"),
            ("walk to the cave", "move"),
            ("look at the painting", "examine"),
            ("inspect the chest", "examine"),
            ("talk to the bartender", "talk"),
            ("ask about the rumors", "talk"),
            ("use the golden key", "use"),
            ("take the sword", "use"),
            ("help", "meta"),
            ("save game", "meta"),
            ("quit", "meta"),
        ],
    )
    async def test_regex_classification(
        self, player_input: str, expected_intent: str
    ) -> None:
        deps = _build_deps()
        state = _fresh_state(player_input)

        result = await run_pipeline(state, deps)

        assert result.parsed_intent is not None
        assert result.parsed_intent.intent == expected_intent
        assert result.parsed_intent.confidence == 0.9  # regex confidence

    async def test_ambiguous_input_falls_back_to_llm(self) -> None:
        """Non-matching input triggers LLM classification fallback."""
        deps = _build_deps()
        state = _fresh_state("hmm interesting")

        result = await run_pipeline(state, deps)

        assert result.parsed_intent is not None
        # MockLLMClient returns fixed text, classified as 'other'
        assert result.parsed_intent.confidence < 0.9


# ------------------------------------------------------------------
# Safety hooks
# ------------------------------------------------------------------


class TestSafetyIntegration:
    """Safety hooks can block content at pre-input and pre-gen stages."""

    async def test_passthrough_allows_all(self) -> None:
        deps = _build_deps()
        state = _fresh_state("explore the dark forest")

        result = await run_pipeline(state, deps)

        assert result.status == TurnStatus.complete
        assert result.safety_flags == []


# ------------------------------------------------------------------
# LLM call tracking
# ------------------------------------------------------------------


class TestLLMCallTracking:
    """MockLLMClient records all calls for inspection."""

    async def test_regex_match_skips_classification_call(self) -> None:
        deps = _build_deps()
        state = _fresh_state("look around")  # regex → no classify call

        await run_pipeline(state, deps)

        mock_llm: MockLLMClient = deps.llm  # type: ignore[assignment]
        classify_calls = [
            c for c in mock_llm.call_history if c["role"] == ModelRole.CLASSIFICATION
        ]
        assert len(classify_calls) == 0

    async def test_ambiguous_input_triggers_classification(self) -> None:
        deps = _build_deps()
        state = _fresh_state("mysterious phrase")  # ambiguous → LLM classify

        await run_pipeline(state, deps)

        mock_llm: MockLLMClient = deps.llm  # type: ignore[assignment]
        classify_calls = [
            c for c in mock_llm.call_history if c["role"] == ModelRole.CLASSIFICATION
        ]
        assert len(classify_calls) == 1

    async def test_generation_call_uses_correct_role(self) -> None:
        deps = _build_deps()
        state = _fresh_state("look around")

        await run_pipeline(state, deps)

        mock_llm: MockLLMClient = deps.llm  # type: ignore[assignment]
        gen_calls = [
            c for c in mock_llm.call_history if c["role"] == ModelRole.GENERATION
        ]
        assert len(gen_calls) == 1
