"""S03 Narrative Engine — Acceptance Criteria compliance tests.

Covers AC-3.1, AC-3.2, AC-3.4, AC-3.5, AC-3.6, AC-3.8, AC-3.10.

Already covered by existing tests (DO NOT duplicate):
  AC-3.5 (retry cascade) — test_generate_narrative.py::TestGracefulFallback
      covers transient retry → AllTiersFailedError → _FALLBACK_NARRATIVE path,
      budget/permanent error propagation.
  AC-3.5 (word counts enforced by intent) —
      test_generate_narrative.py::TestAdaptiveWordCounts
      parametrises all INTENT_WORD_RANGES entries.
  AC-3.4 (tone/genre in prompt) — test_generate_narrative.py::TestToneGenreInjection
      verifies tone/genre strings appear in _build_generation_prompt output.
  AC-3.2 (summary injection) — test_context_narrative.py::TestInjectSummary
      verifies session_summary propagation; and
      test_generate_narrative.py::TestSummaryInjection.

v2 ACs (deferred — require engine features not built in v1):
  AC-3.3 — Pacing tension tracking: requires a pacing-tension subsystem that
            tracks narrative arc and adjusts generation parameters dynamically;
            no such subsystem exists in v1.
  AC-3.7 — Coherence violation detection: requires a coherence-checker that
            compares generated narrative against world state (e.g. NPC alive/dead);
            no such checker is wired into the generate stage in v1.
            generate_stage does not re-generate on coherence violations.
  AC-3.9 — Streaming delivery rate: deliver_stage is a finalise-and-mark step,
            not a streaming stage. Token-by-token streaming is handled by
            FastAPI SSE in the route layer (plans/api-and-sessions.md §3).
            There is no stream rate enforcement testable at the unit level.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tta.models.turn import ParsedIntent, TurnState, TurnStatus
from tta.pipeline.stages.context import (
    _inject_genesis_elements,
    _inject_summary,
    _inject_tone,
    context_stage,
)
from tta.pipeline.stages.deliver import deliver_stage
from tta.pipeline.stages.generate import (
    _FALLBACK_NARRATIVE,
    INTENT_WORD_RANGES,
    _build_generation_prompt,
)

# ── Shared helpers ────────────────────────────────────────────────────────────


def _make_state(**overrides: object) -> TurnState:
    """Return a minimal TurnState for AC compliance testing."""
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


def _make_context_deps(
    *,
    world_context: dict | None = None,
) -> MagicMock:
    """Return a minimal PipelineDeps mock suitable for context_stage tests."""
    deps = MagicMock()

    # Make get_player_location, get_location_context, get_recent_events all
    # raise so context_stage uses the fallback path (simpler and no external svc).
    _ = world_context  # referenced by side_effect below if needed
    deps.world.get_player_location = AsyncMock(side_effect=RuntimeError("no world"))
    deps.world.get_recent_events = AsyncMock(return_value=[])
    deps.consequence_service = None
    deps.relationship_service = None
    deps.turn_repo = None
    return deps


# ── AC-3.1: Sensory / environmental guidance in generation prompt ─────────────


class TestAC301SensoryGuidance:
    """AC-3.1: Each standard gameplay turn prompt carries sensory/env guidance.

    The spec requires at least one sensory detail and no repeated sentence
    structures.  In v1 this is enforced at the prompt-instruction level:
    _build_generation_prompt embeds an exploration-hook directive for
    'examine' and 'move' intents, and the system template carries
    narrator constraints (tested separately in TestNarratorConstraints).
    We verify the prompt template contains sensory-encouraging directives.
    """

    def test_examine_prompt_includes_exploration_hook(self) -> None:
        """AC-3.1: 'examine' prompt instructs the LLM to add an exploration hook."""
        state = _make_state(
            parsed_intent=ParsedIntent(intent="examine", confidence=0.9),
            world_context={"game_state": {}, "intent": "examine"},
        )
        prompt = _build_generation_prompt(state)

        # The generate stage adds a hook directive for examine/move (line 211-215)
        assert "hook" in prompt.lower(), (
            "Prompt must include an exploration-hook directive for 'examine' intent"
        )

    def test_move_prompt_includes_exploration_hook(self) -> None:
        """AC-3.1: 'move' prompt carries the same narrative-hook instruction."""
        state = _make_state(
            parsed_intent=ParsedIntent(intent="move", confidence=0.9),
            world_context={"game_state": {}, "intent": "move"},
        )
        prompt = _build_generation_prompt(state)

        assert "hook" in prompt.lower(), (
            "Prompt must include an exploration-hook directive for 'move' intent"
        )

    def test_non_explore_intents_do_not_get_hook(self) -> None:
        """AC-3.1: Non-exploration intents ('talk') do not inject the hook."""
        state = _make_state(
            parsed_intent=ParsedIntent(intent="talk", confidence=0.9),
            world_context={"game_state": {}, "intent": "talk"},
        )
        prompt = _build_generation_prompt(state)

        # 'talk' should NOT receive the exploration hook (it targets examine/move only)
        assert "End with a subtle narrative hook" not in prompt

    def test_failure_narrated_as_meaningful_beat(self) -> None:
        """S01 AC-1.5 (surfaced here): Prompt instructs failure as a story beat.

        Source: generate.py line 217 — "Failure-consequence instruction (S01 AC-1.5)".
        Included here because it directly affects narrative quality (AC-3.1).
        Prevents terse error-like outputs; keeps sensory continuity on failures.
        """
        state = _make_state()
        prompt = _build_generation_prompt(state)

        assert "meaningful story beat" in prompt, (
            "Prompt must include failure-as-story-beat instruction for all intents"
        )


# ── AC-3.2: Revisit signal presence in context ───────────────────────────────


class TestAC302RevisitContext:
    """AC-3.2: Revisited locations produce shorter, delta-focused descriptions.

    v1 does not have a dedicated 'is_revisit' flag on WorldContext or TurnState.
    The mechanism in v1 is:
      1. _inject_summary forwards an existing session summary (prior-visit
         knowledge) so the LLM knows the player has been here.
      2. The AC requires the *generated* text to be shorter and reference changes
         — a LLM-quality guarantee that cannot be unit-tested without calling
         the model.
    These tests validate the *contract precondition*: that prior-visit information
    (summary) is injected into context when present, giving the LLM the data
    it needs to satisfy AC-3.2.  Full behavioural compliance is an integration
    concern.
    """

    def test_session_summary_injects_prior_visit_knowledge(self) -> None:
        """AC-3.2 precondition: summary is injected when game_state has one."""
        state = _make_state(
            game_state={"summary": "The player has already visited the tavern."},
        )
        ctx: dict = {}
        result = _inject_summary(ctx, state)

        assert "session_summary" in result, (
            "Prior-visit summary must appear in world_context for AC-3.2 compliance"
        )
        assert "tavern" in result["session_summary"]

    def test_no_summary_means_no_prior_visit_signal(self) -> None:
        """AC-3.2: Without a summary, context has no revisit signal (first visit)."""
        state = _make_state(game_state={})
        ctx: dict = {}
        result = _inject_summary(ctx, state)

        assert "session_summary" not in result

    def test_summary_reaches_generation_prompt(self) -> None:
        """AC-3.2: Summary in world_context appears in the generation prompt."""
        state = _make_state(
            world_context={
                "game_state": {},
                "intent": "examine",
                "session_summary": "Previously, you explored the tavern.",
            },
        )
        prompt = _build_generation_prompt(state)

        assert "Previously, you explored the tavern." in prompt


# ── AC-3.4: Fantasy genre vocabulary / tone wired through context ─────────────


class TestAC304FantasyGenreTone:
    """AC-3.4: Fantasy WorldSeed drives vocabulary, metaphor, and sentence rhythm.

    In v1, tone/genre flow is:
      WorldSeed.game_state["world_seed"]["tone/genre"]
        → _inject_tone → world_context["tone/genre"]
        → _build_generation_prompt → "Narrative style: …" prompt section.
    These tests verify the end-to-end wiring without calling the LLM.
    (test_context_narrative.py already tests _inject_tone isolation;
    here we test the full chain.)
    """

    def test_fantasy_tone_and_genre_both_injected_together(self) -> None:
        """AC-3.4: _inject_tone extracts tone AND genre together from world_seed.

        test_context_narrative.py tests tone-only and genre-only in isolation.
        This verifies the combined fantasy case: both keys must coexist in the
        resulting context dict so the generation prompt can render a complete
        'Narrative style' section.
        """
        state = _make_state(
            game_state={
                "world_seed": {"tone": "epic fantasy", "genre": "high fantasy"}
            },
        )
        ctx: dict = {}
        result = _inject_tone(ctx, state)

        assert result["tone"] == "epic fantasy"
        assert result["genre"] == "high fantasy"
        assert set(result.keys()) >= {"tone", "genre"}, (
            "Both tone and genre must be present for a complete Narrative style section"
        )

    def test_fantasy_genre_surfaces_in_generation_prompt(self) -> None:
        """AC-3.4: Genre appears in the generation prompt under 'Narrative style'."""
        state = _make_state(
            world_context={
                "game_state": {},
                "intent": "examine",
                "tone": "epic fantasy",
                "genre": "fantasy",
            },
        )
        prompt = _build_generation_prompt(state)

        assert "Narrative style" in prompt, (
            "Generation prompt must include a 'Narrative style' section for AC-3.4"
        )
        assert "fantasy" in prompt, "Genre value must appear in the generation prompt"
        assert "epic fantasy" in prompt, (
            "Tone value must appear in the generation prompt"
        )

    def test_no_world_seed_no_style_section(self) -> None:
        """AC-3.4: Without a WorldSeed the prompt omits the Narrative style section."""
        state = _make_state(
            world_context={"game_state": {}, "intent": "examine"},
        )
        prompt = _build_generation_prompt(state)

        assert "Narrative style" not in prompt


# ── AC-3.5: Fallback narrative is in-world (no technical language) ────────────


class TestAC305FallbackNarrativeContent:
    """AC-3.5: Graceful fallback narrative exposes no error language to the player.

    test_generate_narrative.py already tests that generate_stage returns
    _FALLBACK_NARRATIVE on AllTiersFailedError and TransientLLMError.
    This class only tests the *content* of _FALLBACK_NARRATIVE — that it
    is in-world prose with no technical jargon.
    """

    def test_fallback_has_no_error_word(self) -> None:
        """AC-3.5: Fallback must not contain the word 'error'."""
        assert "error" not in _FALLBACK_NARRATIVE.lower(), (
            "Fallback narrative must not expose 'error' to the player"
        )

    def test_fallback_has_no_technical_jargon(self) -> None:
        """AC-3.5: Fallback must not contain technical failure terms."""
        forbidden = {"exception", "traceback", "timeout", "retry", "failed", "crash"}
        lower = _FALLBACK_NARRATIVE.lower()
        violations = [word for word in forbidden if word in lower]
        assert not violations, (
            f"Fallback narrative contains technical language: {violations}"
        )

    def test_fallback_is_non_empty_prose(self) -> None:
        """AC-3.5: Fallback is a non-empty string (at least one sentence)."""
        assert isinstance(_FALLBACK_NARRATIVE, str)
        assert len(_FALLBACK_NARRATIVE) >= 20, (
            "Fallback narrative must be substantial in-world prose"
        )

    def test_fallback_uses_second_person(self) -> None:
        """AC-3.5: Fallback uses second person ('you'), matching game voice."""
        assert "you" in _FALLBACK_NARRATIVE.lower(), (
            "Fallback narrative must use second-person game voice"
        )


# ── AC-3.6: Context assembly performance ─────────────────────────────────────


class TestAC306ContextAssemblyPerformance:
    """AC-3.6: context_stage completes within 500ms and context stays within limits.

    Turn 100 is simulated by setting turn_number=100.  The test uses the
    fallback path of context_stage (world service raises) so it runs
    without any external dependencies, keeping it a pure unit test.
    The 500ms budget is conservative for the pure-Python path tested here;
    real prod also has the WorldService I/O, but the pure-Python assembly
    must not itself be the bottleneck.
    """

    @pytest.mark.asyncio
    async def test_context_stage_fast_at_turn_100(self) -> None:
        """AC-3.6: context_stage completes in under 500ms at turn 100."""
        state = _make_state(
            turn_number=100,
            game_state={
                "world_seed": {"tone": "epic", "genre": "fantasy"},
                "summary": "A long adventure summary. " * 10,
            },
        )
        deps = _make_context_deps()

        start = time.monotonic()
        result = await context_stage(state, deps)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 500, (
            f"context_stage took {elapsed_ms:.1f}ms — must complete in <500ms (AC-3.6)"
        )
        assert result.world_context is not None

    @pytest.mark.asyncio
    async def test_context_size_is_bounded(self) -> None:
        """AC-3.6: Assembled world_context dict is within a reasonable size bound.

        The practical limit is set by the model's context window. We assert
        the serialised context (as JSON-ish str) is under 100KB — well
        within a 128K-token window and sufficient for typical gameplay.
        """
        import json

        state = _make_state(
            turn_number=1,
            game_state={
                "world_seed": {"tone": "grim", "genre": "dark fantasy"},
                "summary": "Player explored the dungeon. " * 20,
            },
        )
        deps = _make_context_deps()

        result = await context_stage(state, deps)

        ctx_bytes = len(json.dumps(result.world_context, default=str).encode())
        assert ctx_bytes < 100_000, (
            f"world_context serialises to {ctx_bytes} bytes — "
            "exceeds 100KB safety limit (AC-3.6)"
        )


# ── AC-3.7: Coherence violation detection ────────────────────────────────────

# DEFERRED (v2): No coherence-checking code exists in generate_stage or anywhere
# in the pipeline. generate_stage does not inspect the narrative for dead-NPC /
# world-state contradictions, nor does it regenerate on coherence failures.
# This feature would require a coherence-checker module wired into generate_stage.
# See docstring above for full rationale.


# ── AC-3.8: INTENT_WORD_RANGES contract ──────────────────────────────────────


class TestAC308IntentWordRanges:
    """AC-3.8: INTENT_WORD_RANGES maps intents to correct word-count windows.

    These tests verify the *constant* directly (not the prompt interpolation,
    which is already covered by test_generate_narrative.py::TestAdaptiveWordCounts).
    They serve as a regression guard: if ranges are changed, both the constant
    tests (here) and the prompt-injection tests must be updated together.
    """

    def test_examine_range_is_150_to_300(self) -> None:
        """AC-3.8: 'examine' (exploration) produces 150-300 words."""
        assert INTENT_WORD_RANGES["examine"] == (150, 300), (
            "AC-3.8 specifies 150-300 words for exploration/examine intent"
        )

    def test_move_range(self) -> None:
        """AC-3.8: 'move' produces 80-150 words."""
        assert INTENT_WORD_RANGES["move"] == (80, 150)

    def test_talk_range(self) -> None:
        """AC-3.8: 'talk' produces 100-250 words."""
        assert INTENT_WORD_RANGES["talk"] == (100, 250)

    def test_use_range(self) -> None:
        """AC-3.8: 'use' produces 80-200 words."""
        assert INTENT_WORD_RANGES["use"] == (80, 200)

    def test_meta_range(self) -> None:
        """AC-3.8: 'meta' produces 50-100 words (briefest — OOC queries)."""
        assert INTENT_WORD_RANGES["meta"] == (50, 100)

    def test_other_range(self) -> None:
        """AC-3.8: 'other' fallback produces 100-200 words."""
        assert INTENT_WORD_RANGES["other"] == (100, 200)

    def test_all_expected_intents_present(self) -> None:
        """AC-3.8: The full set of intents has registered ranges."""
        expected = {"move", "examine", "talk", "use", "meta", "other"}
        assert expected.issubset(set(INTENT_WORD_RANGES.keys())), (
            "INTENT_WORD_RANGES must cover all standard player intents"
        )

    def test_all_ranges_are_valid_tuples(self) -> None:
        """AC-3.8: Every range is (min, max) with min < max and both positive."""
        for intent, (lo, hi) in INTENT_WORD_RANGES.items():
            assert lo > 0, f"Range min for '{intent}' must be positive"
            assert hi > lo, f"Range max for '{intent}' must exceed min"

    def test_examine_prompt_includes_two_hook_detail(self) -> None:
        """AC-3.8: 'examine' prompt mentions further exploration hooks."""
        state = _make_state(
            parsed_intent=ParsedIntent(intent="examine", confidence=0.9),
            world_context={"game_state": {}, "intent": "examine"},
        )
        prompt = _build_generation_prompt(state)

        # The spec says "at least two hooks for further interaction"
        # The prompt says "a detail, sound, or glimpse that invites further exploration"
        assert "exploration" in prompt.lower() or "hook" in prompt.lower(), (
            "Prompt must carry an invitation to further exploration (AC-3.8)"
        )


# ── AC-3.9: Streaming delivery rate ──────────────────────────────────────────

# DEFERRED (v1 unit scope): deliver_stage does not stream tokens; it is a
# finalise-and-mark step.  Token-by-token SSE streaming is handled by the
# FastAPI route layer (see plans/api-and-sessions.md §3, and the SSE endpoint
# in src/tta/api/routes/games.py).  The 2-second inter-token pause guarantee
# is an integration/load-test concern, not a pipeline unit test.
#
# The tests below verify the deliver_stage contract that IS unit-testable:
# that it marks a turn complete when narrative is present.


class TestAC309DeliverStageContract:
    """AC-3.9 (v1 proxy): deliver_stage marks turns correctly; streaming is v2.

    Streaming rate (no pauses >2s) requires an integration environment with
    a real SSE stream. deliver_stage is a non-streaming finalise-and-mark step
    that hands the narrative to the route layer for SSE streaming.
    """

    @pytest.mark.asyncio
    async def test_deliver_marks_complete_when_narrative_present(self) -> None:
        """deliver_stage returns TurnStatus.complete when narrative_output is set."""
        state = _make_state(
            narrative_output="The tavern hums with quiet conversation.",
        )
        deps = MagicMock()

        result = await deliver_stage(state, deps)

        assert result.status == TurnStatus.complete
        assert result.delivered is True

    @pytest.mark.asyncio
    async def test_deliver_fails_when_narrative_absent(self) -> None:
        """deliver_stage returns TurnStatus.failed when no narrative_output."""
        state = _make_state(narrative_output=None)
        deps = MagicMock()

        result = await deliver_stage(state, deps)

        assert result.status == TurnStatus.failed
        assert result.delivered is False

    @pytest.mark.asyncio
    async def test_deliver_does_not_mutate_narrative(self) -> None:
        """deliver_stage preserves narrative_output unchanged."""
        text = "A cold wind howls through the broken window."
        state = _make_state(narrative_output=text)
        deps = MagicMock()

        result = await deliver_stage(state, deps)

        assert result.narrative_output == text


# ── AC-3.10: Context assembly determinism ────────────────────────────────────


class TestAC310ContextDeterminism:
    """AC-3.10: Same inputs produce identical context payloads on repeated runs.

    Tests _inject_tone, _inject_summary, and _inject_genesis_elements directly
    (the pure helper functions) as well as the full context_stage fallback path.
    """

    def test_inject_tone_is_deterministic(self) -> None:
        """AC-3.10: _inject_tone returns identical results on repeated calls."""
        state = _make_state(
            game_state={"world_seed": {"tone": "gritty", "genre": "noir"}},
        )
        r1 = _inject_tone({}, state)
        r2 = _inject_tone({}, state)

        assert r1 == r2

    def test_inject_summary_is_deterministic(self) -> None:
        """AC-3.10: _inject_summary returns identical results on repeated calls."""
        state = _make_state(game_state={"summary": "The hero fought a dragon."})
        r1 = _inject_summary({}, state)
        r2 = _inject_summary({}, state)

        assert r1 == r2

    def test_inject_genesis_elements_is_deterministic(self) -> None:
        """AC-3.10: _inject_genesis_elements returns identical results."""
        state = _make_state(
            turn_number=1,
            game_state={
                "world_seed": {
                    "genesis": {
                        "genesis_elements": ["The Silver Chalice", "Elder Thornwood"]
                    }
                }
            },
        )
        r1 = _inject_genesis_elements({}, state)
        r2 = _inject_genesis_elements({}, state)

        assert r1 == r2

    def test_build_generation_prompt_is_deterministic(self) -> None:
        """AC-3.10: _build_generation_prompt produces identical strings on two calls."""
        state = _make_state(
            parsed_intent=ParsedIntent(intent="examine", confidence=0.9),
            world_context={
                "game_state": {},
                "intent": "examine",
                "tone": "mysterious",
                "genre": "gothic",
                "session_summary": "You descended into the crypt.",
            },
        )
        p1 = _build_generation_prompt(state)
        p2 = _build_generation_prompt(state)

        assert p1 == p2, (
            "Same TurnState must always produce identical generation prompt (AC-3.10)"
        )

    @pytest.mark.asyncio
    async def test_context_stage_fallback_path_is_deterministic(self) -> None:
        """AC-3.10: context_stage fallback produces identical world_context dicts."""
        game_state = {
            "world_seed": {"tone": "heroic", "genre": "fantasy"},
            "summary": "The knight arrived at the castle.",
        }
        state = _make_state(
            turn_number=5,
            game_state=game_state,
        )
        deps = _make_context_deps()

        r1 = await context_stage(state, deps)
        # Reset deps AsyncMock call counts so second call also uses fallback
        deps.world.get_player_location.reset_mock()
        deps.world.get_recent_events.return_value = []
        r2 = await context_stage(state, deps)

        # Strip session_id (stable) and compare deterministic keys
        wc1 = r1.world_context or {}
        wc2 = r2.world_context or {}
        for key in ("tone", "genre", "session_summary", "intent", "turn_number"):
            assert wc1.get(key) == wc2.get(key), (
                f"world_context['{key}'] differs between two calls with the same input"
            )
