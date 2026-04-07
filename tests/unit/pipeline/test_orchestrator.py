"""Tests for the pipeline orchestrator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tta.llm.testing import MockLLMClient
from tta.models.turn import TurnState, TurnStatus
from tta.pipeline.orchestrator import run_pipeline
from tta.pipeline.types import (
    PipelineConfig,
    PipelineDeps,
    StageConfig,
    StageName,
)
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


def _safe_result() -> SafetyResult:
    return SafetyResult(safe=True)


def _make_deps(
    *,
    llm: MockLLMClient | AsyncMock | None = None,
    safety_pre_input: AsyncMock | None = None,
) -> PipelineDeps:
    safe = _safe_result()

    pre_input = safety_pre_input or AsyncMock()
    pre_gen = AsyncMock()
    post_gen = AsyncMock()

    if safety_pre_input is None:
        pre_input.pre_generation_check = AsyncMock(
            return_value=safe
        )
    pre_gen.pre_generation_check = AsyncMock(return_value=safe)
    post_gen.post_generation_check = AsyncMock(return_value=safe)

    return PipelineDeps(
        llm=llm or MockLLMClient(),
        world=AsyncMock(),
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=pre_input,
        safety_pre_gen=pre_gen,
        safety_post_gen=post_gen,
    )


# --- happy path ---


async def test_full_pipeline_happy_path() -> None:
    """Complete pipeline: processing → complete."""
    state = _make_state()
    deps = _make_deps()
    result = await run_pipeline(state, deps)

    assert result.status == TurnStatus.complete
    assert result.delivered is True
    assert result.narrative_output is not None
    assert result.parsed_intent is not None
    assert result.world_context is not None
    assert result.generation_prompt is not None
    assert result.model_used is not None
    assert result.token_count is not None


async def test_pipeline_preserves_session_id() -> None:
    sid = uuid4()
    state = _make_state(session_id=sid)
    deps = _make_deps()
    result = await run_pipeline(state, deps)

    assert result.session_id == sid


# --- early exit on safety block ---


async def test_pipeline_early_exit_on_safety_block() -> None:
    """Safety blocking in understand → pipeline stops early."""
    blocked = SafetyResult(safe=False, flags=["blocked"])
    safety = AsyncMock()
    safety.pre_generation_check = AsyncMock(
        return_value=blocked
    )
    state = _make_state()
    deps = _make_deps(safety_pre_input=safety)
    result = await run_pipeline(state, deps)

    assert result.status == TurnStatus.failed
    assert "blocked" in result.safety_flags
    assert result.narrative_output is None


# --- stage timeout ---


async def test_stage_timeout_fails_pipeline() -> None:
    """A stage that exceeds its timeout → failed."""

    async def _slow_understand(state, deps):  # type: ignore[no-untyped-def]
        await asyncio.sleep(10)
        return state

    from tta.pipeline import orchestrator

    original = orchestrator.STAGE_MAP[StageName.UNDERSTAND]
    orchestrator.STAGE_MAP[StageName.UNDERSTAND] = _slow_understand
    try:
        config = PipelineConfig(
            stages=[
                StageConfig(
                    name=StageName.UNDERSTAND, timeout_seconds=0.05
                ),
                StageConfig(name=StageName.CONTEXT),
                StageConfig(name=StageName.GENERATE),
                StageConfig(name=StageName.DELIVER),
            ]
        )
        state = _make_state()
        deps = _make_deps()
        result = await run_pipeline(state, deps, config=config)
        assert result.status == TurnStatus.failed
    finally:
        orchestrator.STAGE_MAP[StageName.UNDERSTAND] = original


# --- stage exception ---


async def test_stage_exception_fails_pipeline() -> None:
    """A stage that raises → status=failed."""

    async def _broken_understand(state, deps):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    from tta.pipeline import orchestrator

    original = orchestrator.STAGE_MAP[StageName.UNDERSTAND]
    orchestrator.STAGE_MAP[StageName.UNDERSTAND] = (
        _broken_understand
    )
    try:
        state = _make_state()
        deps = _make_deps()
        result = await run_pipeline(state, deps)
        assert result.status == TurnStatus.failed
    finally:
        orchestrator.STAGE_MAP[StageName.UNDERSTAND] = original


# --- overall timeout ---


async def test_overall_timeout_fails_pipeline() -> None:
    """Pipeline overall timeout → failed."""

    async def _slow_generate(state, deps):  # type: ignore[no-untyped-def]
        await asyncio.sleep(10)
        return state

    from tta.pipeline import orchestrator

    original = orchestrator.STAGE_MAP[StageName.GENERATE]
    orchestrator.STAGE_MAP[StageName.GENERATE] = _slow_generate
    try:
        config = PipelineConfig(
            stages=[
                StageConfig(name=StageName.UNDERSTAND),
                StageConfig(name=StageName.CONTEXT),
                StageConfig(
                    name=StageName.GENERATE,
                    timeout_seconds=100,
                ),
                StageConfig(name=StageName.DELIVER),
            ],
            overall_timeout_seconds=0.05,
        )
        state = _make_state()
        deps = _make_deps()
        result = await run_pipeline(state, deps, config=config)
        assert result.status == TurnStatus.failed
    finally:
        orchestrator.STAGE_MAP[StageName.GENERATE] = original


# --- default config ---


async def test_pipeline_uses_default_config() -> None:
    """Pipeline works without explicit config."""
    state = _make_state()
    deps = _make_deps()
    result = await run_pipeline(state, deps, config=None)
    assert result.status == TurnStatus.complete


# --- original state immutability ---


async def test_pipeline_does_not_mutate_input_state() -> None:
    state = _make_state()
    deps = _make_deps()
    result = await run_pipeline(state, deps)

    assert state.status == TurnStatus.processing
    assert result.status == TurnStatus.complete
    assert state is not result
