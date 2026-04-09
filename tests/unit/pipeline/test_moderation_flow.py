"""Tests for moderation flow through the pipeline.

Verifies FR-24.06 (stream interruption), FR-24.07 (early exit),
and FR-24.08 (moderation event emission) via orchestrator, understand,
and generate stages.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from tta.llm.testing import MockLLMClient
from tta.models.turn import TurnState, TurnStatus
from tta.pipeline.orchestrator import run_pipeline
from tta.pipeline.types import PipelineDeps
from tta.safety.hooks import SafetyResult


def _make_state(**overrides: object) -> TurnState:
    defaults: dict = {
        "session_id": uuid4(),
        "turn_number": 1,
        "player_input": "look around",
        "game_state": {"location": "tavern"},
    }
    defaults.update(overrides)
    return TurnState(**defaults)


def _safe() -> SafetyResult:
    return SafetyResult(safe=True)


def _block_with_redirect() -> SafetyResult:
    return SafetyResult(
        safe=False,
        flags=["moderation:blocked"],
        modified_content="The story gently shifts direction...",
    )


def _block_without_redirect() -> SafetyResult:
    return SafetyResult(safe=False, flags=["moderation:hard_block"])


def _make_deps(
    *,
    safety_pre_input: AsyncMock | None = None,
    safety_post_gen: AsyncMock | None = None,
) -> PipelineDeps:
    safe = _safe()

    pre_input = safety_pre_input or AsyncMock()
    pre_gen = AsyncMock()
    post_gen = safety_post_gen or AsyncMock()

    if safety_pre_input is None:
        pre_input.pre_generation_check = AsyncMock(return_value=safe)
    pre_gen.pre_generation_check = AsyncMock(return_value=safe)
    if safety_post_gen is None:
        post_gen.post_generation_check = AsyncMock(return_value=safe)

    return PipelineDeps(
        llm=MockLLMClient(),
        world=AsyncMock(),
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=pre_input,
        safety_pre_gen=pre_gen,
        safety_post_gen=post_gen,
    )


# --- orchestrator early-exit on moderated ---


class TestOrchestratorModeratedExit:
    """Orchestrator stops the pipeline on TurnStatus.moderated."""

    async def test_input_block_with_redirect_sets_moderated(self) -> None:
        """Input moderation block with redirect → TurnStatus.moderated."""
        blocked = _block_with_redirect()
        safety = AsyncMock()
        safety.pre_generation_check = AsyncMock(return_value=blocked)
        deps = _make_deps(safety_pre_input=safety)
        result = await run_pipeline(_make_state(), deps)

        assert result.status == TurnStatus.moderated
        assert result.narrative_output == blocked.modified_content
        assert "moderation:blocked" in result.safety_flags

    async def test_moderated_skips_context_and_generate(self) -> None:
        """Moderated in understand → context/generate/deliver never run."""
        blocked = _block_with_redirect()
        safety = AsyncMock()
        safety.pre_generation_check = AsyncMock(return_value=blocked)
        deps = _make_deps(safety_pre_input=safety)
        result = await run_pipeline(_make_state(), deps)

        assert result.status == TurnStatus.moderated
        # Context stage never ran — no world_context populated.
        assert result.world_context is None
        # Generate stage never ran — no model_used.
        assert result.model_used is None
        # Deliver stage never ran — delivered stays False.
        assert result.delivered is False

    async def test_output_block_with_redirect_sets_moderated(self) -> None:
        """Output moderation block with redirect → TurnStatus.moderated."""
        blocked = _block_with_redirect()
        safety = AsyncMock()
        safety.post_generation_check = AsyncMock(return_value=blocked)
        deps = _make_deps(safety_post_gen=safety)
        result = await run_pipeline(_make_state(), deps)

        assert result.status == TurnStatus.moderated
        assert result.narrative_output == blocked.modified_content

    async def test_input_block_without_redirect_fails(self) -> None:
        """Input moderation block without redirect → TurnStatus.failed."""
        blocked = _block_without_redirect()
        safety = AsyncMock()
        safety.pre_generation_check = AsyncMock(return_value=blocked)
        deps = _make_deps(safety_pre_input=safety)
        result = await run_pipeline(_make_state(), deps)

        assert result.status == TurnStatus.failed
        assert result.narrative_output is None


# --- understand stage sets moderated ---


class TestUnderstandModerated:
    """understand stage sets TurnStatus.moderated on safety block."""

    async def test_safety_block_with_redirect_sets_moderated(self) -> None:
        """Pre-input safety block with redirect → moderated status."""
        from tta.pipeline.stages.understand import understand_stage

        blocked = _block_with_redirect()
        safety = AsyncMock()
        safety.pre_generation_check = AsyncMock(return_value=blocked)
        deps = _make_deps(safety_pre_input=safety)
        state = _make_state()
        result = await understand_stage(state, deps)

        assert result.status == TurnStatus.moderated
        assert result.narrative_output == blocked.modified_content
        assert result.safety_flags == blocked.flags


# --- generate stage sets moderated + logs ---


class TestGenerateModerated:
    """generate stage sets TurnStatus.moderated on post-gen safety block."""

    async def test_post_gen_block_with_redirect_sets_moderated(
        self,
    ) -> None:
        """Post-gen safety block with redirect → moderated status."""
        from tta.pipeline.stages.generate import generate_stage

        blocked = _block_with_redirect()
        safety = AsyncMock()
        safety.post_generation_check = AsyncMock(return_value=blocked)

        from tta.models.turn import ParsedIntent

        deps = _make_deps(safety_post_gen=safety)
        # Pre-populate fields that earlier stages would have set.
        state = _make_state(
            parsed_intent=ParsedIntent(intent="attack the guard", confidence=0.9),
            world_context={"enemies": ["guard"]},
            generation_prompt="Generate combat narrative",
        )
        result = await generate_stage(state, deps)

        assert result.status == TurnStatus.moderated
        assert result.narrative_output == blocked.modified_content
        assert result.safety_flags == blocked.flags
