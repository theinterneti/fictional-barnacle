"""Tests for the generate pipeline stage."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

from tta.llm.client import LLMResponse
from tta.llm.testing import MockLLMClient
from tta.models.turn import (
    ParsedIntent,
    TokenCount,
    TurnState,
    TurnStatus,
)
from tta.pipeline.stages.generate import generate_stage
from tta.pipeline.types import PipelineDeps
from tta.safety.hooks import SafetyResult


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


def _safe_result() -> SafetyResult:
    return SafetyResult(safe=True)


def _make_deps(
    *,
    llm: MockLLMClient | AsyncMock | None = None,
    safety_pre_gen: AsyncMock | None = None,
    safety_post_gen: AsyncMock | None = None,
) -> PipelineDeps:
    safe = _safe_result()
    pre_gen = safety_pre_gen or AsyncMock()
    post_gen = safety_post_gen or AsyncMock()
    if safety_pre_gen is None:
        pre_gen.pre_generation_check = AsyncMock(return_value=safe)
    if safety_post_gen is None:
        post_gen.post_generation_check = AsyncMock(return_value=safe)
    return PipelineDeps(
        llm=llm or MockLLMClient(),
        world=AsyncMock(),
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=AsyncMock(),
        safety_pre_gen=pre_gen,
        safety_post_gen=post_gen,
    )


# --- happy path ---


async def test_generate_sets_narrative_output() -> None:
    state = _make_state()
    deps = _make_deps()
    result = await generate_stage(state, deps)

    assert result.narrative_output is not None
    assert len(result.narrative_output) > 0


async def test_generate_sets_model_used() -> None:
    state = _make_state()
    deps = _make_deps()
    result = await generate_stage(state, deps)

    assert result.model_used == "mock"


async def test_generate_sets_token_count() -> None:
    state = _make_state()
    deps = _make_deps()
    result = await generate_stage(state, deps)

    assert result.token_count is not None
    assert result.token_count.total_tokens > 0


async def test_generate_sets_generation_prompt() -> None:
    state = _make_state()
    deps = _make_deps()
    result = await generate_stage(state, deps)

    assert result.generation_prompt is not None
    assert "look around" in result.generation_prompt


async def test_generate_calls_llm_with_generation_role() -> None:
    mock_llm = MockLLMClient()
    state = _make_state()
    deps = _make_deps(llm=mock_llm)
    await generate_stage(state, deps)

    gen_calls = [c for c in mock_llm.call_history if c["role"] == "generation"]
    assert len(gen_calls) == 1


async def test_generate_calls_extraction_after_generation() -> None:
    mock_llm = MockLLMClient()
    state = _make_state()
    deps = _make_deps(llm=mock_llm)
    await generate_stage(state, deps)

    roles = [c["role"] for c in mock_llm.call_history]
    assert "generation" in roles
    assert "extraction" in roles


# --- safety hooks ---


async def test_pre_gen_safety_blocks() -> None:
    blocked = SafetyResult(safe=False, flags=["injection"])
    pre_gen = AsyncMock()
    pre_gen.pre_generation_check = AsyncMock(return_value=blocked)
    state = _make_state()
    deps = _make_deps(safety_pre_gen=pre_gen)
    result = await generate_stage(state, deps)

    assert result.status == TurnStatus.failed
    assert "injection" in result.safety_flags
    assert result.narrative_output is None


async def test_post_gen_safety_blocks() -> None:
    blocked = SafetyResult(safe=False, flags=["harmful_content"])
    post_gen = AsyncMock()
    post_gen.post_generation_check = AsyncMock(return_value=blocked)
    state = _make_state()
    deps = _make_deps(safety_post_gen=post_gen)
    result = await generate_stage(state, deps)

    assert result.status == TurnStatus.failed
    assert "harmful_content" in result.safety_flags
    assert result.narrative_output is None


async def test_post_gen_safety_block_with_redirect() -> None:
    """Blocked output with modified_content → complete with redirect."""
    redirect = SafetyResult(
        safe=False,
        flags=["moderation:graphic_violence"],
        modified_content="Redirect narrative.",
    )
    post_gen = AsyncMock()
    post_gen.post_generation_check = AsyncMock(return_value=redirect)
    state = _make_state()
    deps = _make_deps(safety_post_gen=post_gen)
    result = await generate_stage(state, deps)

    assert result.status == TurnStatus.moderated
    assert result.narrative_output == "Redirect narrative."
    assert "moderation:graphic_violence" in result.safety_flags


async def test_post_gen_safety_modifies_content() -> None:
    """Safety hook can replace content via modified_content."""
    modified = SafetyResult(safe=True, modified_content="Sanitized narrative.")
    post_gen = AsyncMock()
    post_gen.post_generation_check = AsyncMock(return_value=modified)
    state = _make_state()
    deps = _make_deps(safety_post_gen=post_gen)
    result = await generate_stage(state, deps)

    assert result.narrative_output == "Sanitized narrative."


# --- extraction ---


async def test_extraction_returns_empty_on_invalid_json() -> None:
    """MockLLMClient returns prose, not JSON → world_state_updates=[]."""
    state = _make_state()
    deps = _make_deps()
    result = await generate_stage(state, deps)

    # Mock response is "You enter a dimly lit chamber." — not JSON
    assert result.world_state_updates == []


async def test_extraction_returns_parsed_list() -> None:
    """LLM returns valid JSON array → stored as world_state_updates."""
    changes = [
        {
            "entity": "player",
            "attribute": "location",
            "old_value": None,
            "new_value": "north",
            "reason": "moved north",
        }
    ]
    # First call = generation, second call = extraction
    call_count = 0

    async def _generate(role, messages, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content="You walk north.",
                model_used="mock",
                token_count=TokenCount(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                ),
                latency_ms=0.0,
            )
        return LLMResponse(
            content=json.dumps(changes),
            model_used="mock",
            token_count=TokenCount(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
            latency_ms=0.0,
        )

    llm = AsyncMock()
    llm.generate = _generate
    state = _make_state()
    deps = _make_deps(llm=llm)
    result = await generate_stage(state, deps)

    assert result.world_state_updates == changes


async def test_extraction_non_list_json_returns_empty() -> None:
    """LLM returns JSON object (not array) → empty list."""
    call_count = 0

    async def _generate(role, messages, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content="Narrative text.",
                model_used="mock",
                token_count=TokenCount(
                    prompt_tokens=5,
                    completion_tokens=3,
                    total_tokens=8,
                ),
                latency_ms=0.0,
            )
        return LLMResponse(
            content='{"not": "a list"}',
            model_used="mock",
            token_count=TokenCount(
                prompt_tokens=5,
                completion_tokens=3,
                total_tokens=8,
            ),
            latency_ms=0.0,
        )

    llm = AsyncMock()
    llm.generate = _generate
    state = _make_state()
    deps = _make_deps(llm=llm)
    result = await generate_stage(state, deps)

    assert result.world_state_updates == []


async def test_extraction_dict_format_with_suggestions() -> None:
    """New dict format returns both world_changes and suggested_actions."""
    call_count = 0
    payload = json.dumps(
        {
            "world_changes": [{"entity": "door", "attribute": "open", "value": True}],
            "suggested_actions": ["Open the chest", "Talk to the guard", "Leave"],
        }
    )

    async def _generate(role, messages, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content="Narrative text.",
                model_used="mock",
                token_count=TokenCount(
                    prompt_tokens=5, completion_tokens=3, total_tokens=8
                ),
                latency_ms=0.0,
            )
        return LLMResponse(
            content=payload,
            model_used="mock",
            token_count=TokenCount(
                prompt_tokens=5, completion_tokens=3, total_tokens=8
            ),
            latency_ms=0.0,
        )

    llm = AsyncMock()
    llm.generate = _generate
    state = _make_state()
    deps = _make_deps(llm=llm)
    result = await generate_stage(state, deps)

    assert len(result.world_state_updates) == 1
    assert result.world_state_updates[0]["entity"] == "door"
    assert result.suggested_actions == [
        "Open the chest",
        "Talk to the guard",
        "Leave",
    ]


async def test_extraction_list_format_gives_no_suggestions() -> None:
    """Old plain-list format → world_changes work, suggested_actions is None."""
    call_count = 0
    payload = json.dumps([{"entity": "x", "attribute": "y", "value": 1}])

    async def _generate(role, messages, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content="Narrative.",
                model_used="mock",
                token_count=TokenCount(
                    prompt_tokens=5, completion_tokens=3, total_tokens=8
                ),
                latency_ms=0.0,
            )
        return LLMResponse(
            content=payload,
            model_used="mock",
            token_count=TokenCount(
                prompt_tokens=5, completion_tokens=3, total_tokens=8
            ),
            latency_ms=0.0,
        )

    llm = AsyncMock()
    llm.generate = _generate
    state = _make_state()
    deps = _make_deps(llm=llm)
    result = await generate_stage(state, deps)

    assert len(result.world_state_updates) == 1
    assert result.suggested_actions is None


async def test_extraction_filters_invalid_suggestions() -> None:
    """Non-string, empty, and duplicate suggestions are filtered; <3 distinct → None."""
    call_count = 0
    payload = json.dumps(
        {
            "world_changes": [],
            "suggested_actions": ["valid", "", 123, "also valid"],
        }
    )

    async def _generate(role, messages, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content="Narrative.",
                model_used="mock",
                token_count=TokenCount(
                    prompt_tokens=5, completion_tokens=3, total_tokens=8
                ),
                latency_ms=0.0,
            )
        return LLMResponse(
            content=payload,
            model_used="mock",
            token_count=TokenCount(
                prompt_tokens=5, completion_tokens=3, total_tokens=8
            ),
            latency_ms=0.0,
        )

    llm = AsyncMock()
    llm.generate = _generate
    state = _make_state()
    deps = _make_deps(llm=llm)
    result = await generate_stage(state, deps)

    # Only 2 valid suggestions — below the minimum of 3, so discarded
    assert result.suggested_actions is None


async def test_extraction_deduplicates_suggestions() -> None:
    """Duplicate suggestions (case-insensitive) are removed."""
    call_count = 0
    payload = json.dumps(
        {
            "world_changes": [],
            "suggested_actions": [
                "Open the door",
                "open the door",
                "Talk to NPC",
                "Search the room",
            ],
        }
    )

    async def _generate(role, messages, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content="Narrative.",
                model_used="mock",
                token_count=TokenCount(
                    prompt_tokens=5, completion_tokens=3, total_tokens=8
                ),
                latency_ms=0.0,
            )
        return LLMResponse(
            content=payload,
            model_used="mock",
            token_count=TokenCount(
                prompt_tokens=5, completion_tokens=3, total_tokens=8
            ),
            latency_ms=0.0,
        )

    llm = AsyncMock()
    llm.generate = _generate
    state = _make_state()
    deps = _make_deps(llm=llm)
    result = await generate_stage(state, deps)

    # 4 items but "Open the door" and "open the door" are dupes → 3 distinct
    assert result.suggested_actions == [
        "Open the door",
        "Talk to NPC",
        "Search the room",
    ]


# --- immutability ---


async def test_original_state_not_mutated() -> None:
    state = _make_state()
    deps = _make_deps()
    result = await generate_stage(state, deps)

    assert state.narrative_output is None
    assert result.narrative_output is not None
    assert state is not result
