"""Tests for pipeline stage types and configuration."""

from collections.abc import Callable
from uuid import uuid4

import pytest

from tta.models.turn import TurnState
from tta.pipeline.types import (
    PipelineConfig,
    Stage,
    StageConfig,
    StageName,
)

# --- helpers ---


def _make_turn_state(**overrides: object) -> TurnState:
    defaults: dict = {
        "session_id": uuid4(),
        "turn_number": 1,
        "player_input": "look around",
        "game_state": {},
    }
    defaults.update(overrides)
    return TurnState(**defaults)


# --- StageName ---


def test_stage_name_has_four_values() -> None:
    assert len(StageName) == 4


def test_stage_name_values() -> None:
    assert list(StageName) == [
        "understand",
        "context",
        "generate",
        "deliver",
    ]


# --- StageConfig ---


def test_stage_config_default_timeout() -> None:
    cfg = StageConfig(name=StageName.UNDERSTAND)
    assert cfg.timeout_seconds == 30.0


def test_stage_config_custom_timeout() -> None:
    cfg = StageConfig(name=StageName.GENERATE, timeout_seconds=60.0)
    assert cfg.timeout_seconds == 60.0


# --- PipelineConfig ---


def test_pipeline_config_default_stages() -> None:
    cfg = PipelineConfig()
    assert len(cfg.stages) == 4
    assert [s.name for s in cfg.stages] == [
        StageName.UNDERSTAND,
        StageName.CONTEXT,
        StageName.GENERATE,
        StageName.DELIVER,
    ]


def test_pipeline_config_overall_timeout() -> None:
    cfg = PipelineConfig()
    assert cfg.overall_timeout_seconds == 120.0


# --- Stage type annotation ---


async def _dummy_stage(state: TurnState) -> TurnState:
    return state


def test_async_function_matches_stage_type() -> None:
    stage: Stage = _dummy_stage
    assert isinstance(
        stage,
        Callable,  # type: ignore[arg-type]
    )


# --- Composability ---


@pytest.mark.asyncio
async def test_stage_composability() -> None:
    """Two stages chained: each enriches TurnState."""

    async def understand(state: TurnState) -> TurnState:
        return state.model_copy(update={"generation_prompt": "enriched"})

    async def generate(state: TurnState) -> TurnState:
        return state.model_copy(update={"narrative_output": "story text"})

    state = _make_turn_state()
    state = await understand(state)
    state = await generate(state)

    assert state.generation_prompt == "enriched"
    assert state.narrative_output == "story text"
