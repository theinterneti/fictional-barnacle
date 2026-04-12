"""Wave 24 tests for narrative engine enhancements (S03).

Tests adaptive word counts, narrator constraints, retry cascade,
graceful fallback, and prompt registry resolution.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tta.llm.errors import (
    AllTiersFailedError,
    BudgetExceededError,
    PermanentLLMError,
    TransientLLMError,
)
from tta.models.turn import ParsedIntent, TurnState
from tta.pipeline.stages.generate import (
    _FALLBACK_NARRATIVE,
    _GENERATION_SYSTEM_PROMPT,
    _NARRATOR_CONSTRAINTS,
    INTENT_WORD_RANGES,
    _build_generation_prompt,
    _resolve_system_prompt,
    generate_stage,
)
from tta.safety.hooks import SafetyResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides: object) -> TurnState:
    defaults: dict = {
        "session_id": uuid4(),
        "turn_number": 1,
        "player_input": "look around",
        "game_state": {},
        "parsed_intent": ParsedIntent(intent="examine", confidence=0.9),
        "world_context": {"game_state": {}, "intent": "examine"},
    }
    defaults.update(overrides)
    return TurnState(**defaults)


def _safe() -> SafetyResult:
    return SafetyResult(safe=True)


def _make_deps(
    *,
    llm: AsyncMock | None = None,
    prompt_registry: MagicMock | None = None,
) -> MagicMock:
    deps = MagicMock()
    deps.llm = llm or AsyncMock()
    deps.world = AsyncMock()
    deps.session_repo = AsyncMock()
    deps.turn_repo = AsyncMock()
    deps.safety_pre_input = AsyncMock()
    deps.safety_pre_gen = MagicMock()
    deps.safety_pre_gen.pre_generation_check = AsyncMock(return_value=_safe())
    deps.safety_post_gen = MagicMock()
    deps.safety_post_gen.post_generation_check = AsyncMock(return_value=_safe())
    deps.prompt_registry = prompt_registry
    return deps


# ===================================================================
# 1. Adaptive word counts per intent (S03 FR-4.2, AC-3.8)
# ===================================================================


class TestAdaptiveWordCounts:
    """_build_generation_prompt includes intent-specific word guidance."""

    @pytest.mark.parametrize(
        "intent,expected_range",
        list(INTENT_WORD_RANGES.items()),
    )
    def test_word_range_injected_per_intent(
        self, intent: str, expected_range: tuple[int, int]
    ) -> None:
        state = _make_state(
            parsed_intent=ParsedIntent(intent=intent, confidence=0.9),
            world_context={"game_state": {}, "intent": intent},
        )
        prompt = _build_generation_prompt(state)
        word_min, word_max = expected_range
        assert f"{word_min}-{word_max} words" in prompt

    def test_unknown_intent_uses_default_range(self) -> None:
        state = _make_state(
            parsed_intent=ParsedIntent(intent="unknown", confidence=0.5),
            world_context={"game_state": {}, "intent": "unknown"},
        )
        prompt = _build_generation_prompt(state)
        assert "100-200 words" in prompt


# ===================================================================
# 2. Narrator constraints in system prompt (S03 FR-1.4, FR-4.1)
# ===================================================================


class TestNarratorConstraints:
    """System prompt includes hard constraints and quality guidance."""

    def test_constraints_in_system_prompt(self) -> None:
        assert "fourth wall" in _NARRATOR_CONSTRAINTS.lower()
        assert "AI" in _NARRATOR_CONSTRAINTS or "ai" in _NARRATOR_CONSTRAINTS.lower()

    def test_system_prompt_includes_constraints(self) -> None:
        assert _NARRATOR_CONSTRAINTS in _GENERATION_SYSTEM_PROMPT


# ===================================================================
# 3. Tone/genre injection in prompt (S03 FR-6.1)
# ===================================================================


class TestToneGenreInjection:
    """_build_generation_prompt surfaces tone when available."""

    def test_tone_present_in_prompt(self) -> None:
        state = _make_state(
            world_context={
                "game_state": {},
                "intent": "examine",
                "tone": "dark and foreboding",
            },
        )
        prompt = _build_generation_prompt(state)
        assert "dark and foreboding" in prompt

    def test_genre_present_in_prompt(self) -> None:
        state = _make_state(
            world_context={
                "game_state": {},
                "intent": "talk",
                "genre": "steampunk",
            },
        )
        prompt = _build_generation_prompt(state)
        assert "steampunk" in prompt

    def test_no_tone_no_crash(self) -> None:
        state = _make_state(
            world_context={"game_state": {}, "intent": "move"},
        )
        prompt = _build_generation_prompt(state)
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ===================================================================
# 4. Summary injection in prompt (S03 FR-3.2)
# ===================================================================


class TestSummaryInjection:
    """_build_generation_prompt includes session summary if available."""

    def test_summary_present_in_prompt(self) -> None:
        state = _make_state(
            world_context={
                "game_state": {},
                "intent": "examine",
                "session_summary": (
                    "The hero entered the dark forest and found a sword."
                ),
            },
        )
        prompt = _build_generation_prompt(state)
        assert "The hero entered the dark forest" in prompt

    def test_no_summary_no_crash(self) -> None:
        state = _make_state(
            world_context={"game_state": {}, "intent": "move"},
        )
        prompt = _build_generation_prompt(state)
        assert isinstance(prompt, str)


# ===================================================================
# 5. Prompt registry resolution (S03 FR-4.3)
# ===================================================================


class TestPromptRegistryResolution:
    """_resolve_system_prompt uses registry when available."""

    def test_uses_registry_when_template_exists(self) -> None:
        registry = MagicMock()
        registry.has.return_value = True
        rendered = MagicMock()
        rendered.text = "Custom system prompt from registry"
        registry.render.return_value = rendered

        deps = _make_deps(prompt_registry=registry)
        result = _resolve_system_prompt(deps)
        assert result == "Custom system prompt from registry"

    def test_falls_back_when_no_registry(self) -> None:
        deps = _make_deps(prompt_registry=None)
        result = _resolve_system_prompt(deps)
        assert result == _GENERATION_SYSTEM_PROMPT

    def test_falls_back_when_template_missing(self) -> None:
        registry = MagicMock()
        registry.has.return_value = False
        deps = _make_deps(prompt_registry=registry)
        result = _resolve_system_prompt(deps)
        assert result == _GENERATION_SYSTEM_PROMPT


# ===================================================================
# 6. Graceful fallback on transient errors (S03 FR-8.1, FR-8.2)
# ===================================================================


class TestGracefulFallback:
    """Transient LLM failures trigger in-world fallback narrative."""

    @pytest.mark.asyncio
    async def test_fallback_on_transient_error(self) -> None:
        deps = _make_deps()
        # guarded_llm_call always raises transient → exhausts retries
        import tta.pipeline.stages.generate as gen_mod

        original = gen_mod.guarded_llm_call
        gen_mod.guarded_llm_call = AsyncMock(side_effect=TransientLLMError("timeout"))
        try:
            state = _make_state()
            result = await generate_stage(state, deps)
            assert result.narrative_output == _FALLBACK_NARRATIVE
            assert result.suggested_actions is None
            assert result.model_used == "fallback"
        finally:
            gen_mod.guarded_llm_call = original

    @pytest.mark.asyncio
    async def test_budget_error_propagates(self) -> None:
        deps = _make_deps()
        import tta.pipeline.stages.generate as gen_mod

        original = gen_mod.guarded_llm_call
        gen_mod.guarded_llm_call = AsyncMock(
            side_effect=BudgetExceededError("over budget")
        )
        try:
            state = _make_state()
            with pytest.raises(BudgetExceededError):
                await generate_stage(state, deps)
        finally:
            gen_mod.guarded_llm_call = original

    @pytest.mark.asyncio
    async def test_permanent_error_propagates(self) -> None:
        deps = _make_deps()
        import tta.pipeline.stages.generate as gen_mod

        original = gen_mod.guarded_llm_call
        gen_mod.guarded_llm_call = AsyncMock(
            side_effect=PermanentLLMError("auth failed")
        )
        try:
            state = _make_state()
            with pytest.raises(PermanentLLMError):
                await generate_stage(state, deps)
        finally:
            gen_mod.guarded_llm_call = original

    @pytest.mark.asyncio
    async def test_fallback_on_all_tiers_failed(self) -> None:
        deps = _make_deps()
        import tta.pipeline.stages.generate as gen_mod

        original = gen_mod.guarded_llm_call
        gen_mod.guarded_llm_call = AsyncMock(
            side_effect=AllTiersFailedError("generation", [RuntimeError("tier failed")])
        )
        try:
            state = _make_state()
            result = await generate_stage(state, deps)
            assert result.narrative_output == _FALLBACK_NARRATIVE
        finally:
            gen_mod.guarded_llm_call = original
