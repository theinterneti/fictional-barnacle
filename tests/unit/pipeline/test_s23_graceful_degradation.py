"""Tests for LLM graceful degradation (S23 AC-23.3).

When the LLM call fails (circuit breaker open, timeout, provider error),
the orchestrator must catch the exception and return TurnStatus.failed
rather than crashing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from tta.api.errors import AppError
from tta.errors import ErrorCategory
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


def _make_deps(*, llm: MockLLMClient | None = None) -> PipelineDeps:
    safe = _safe()
    return PipelineDeps(
        llm=llm or MockLLMClient(),
        world=AsyncMock(),
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=AsyncMock(
            pre_generation_check=AsyncMock(return_value=safe),
        ),
        safety_pre_gen=AsyncMock(
            pre_generation_check=AsyncMock(return_value=safe),
        ),
        safety_post_gen=AsyncMock(
            post_generation_check=AsyncMock(return_value=safe),
        ),
    )


class TestLLMFailureGracefulDegradation:
    """AC-23.3: Pipeline degrades gracefully when LLM call fails."""

    async def test_circuit_breaker_open_returns_failed(self) -> None:
        """When circuit breaker is open, generate stage raises and
        orchestrator catches it, returning TurnStatus.failed."""
        llm = MockLLMClient()
        llm.generate = AsyncMock(  # type: ignore[method-assign]
            side_effect=AppError(
                ErrorCategory.LLM_FAILURE,
                "CIRCUIT_OPEN",
                "llm circuit breaker is open",
            ),
        )
        deps = _make_deps(llm=llm)
        state = _make_state()

        result = await run_pipeline(state, deps)

        assert result.status == TurnStatus.failed

    async def test_llm_runtime_error_returns_degraded(self) -> None:
        """Runtime error triggers fallback narrative (degraded but complete).

        Wave 24 added graceful in-world fallback for transient LLM errors,
        so RuntimeError now produces a degraded narrative instead of failed.
        """
        llm = MockLLMClient()
        llm.generate = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("provider unavailable"),
        )
        deps = _make_deps(llm=llm)
        state = _make_state()

        result = await run_pipeline(state, deps)

        assert result.status == TurnStatus.complete
        assert result.narrative_output is not None

    async def test_llm_timeout_returns_degraded(self) -> None:
        """LLM timeout triggers fallback narrative (degraded but complete).

        Wave 24 added graceful in-world fallback for transient LLM errors,
        so TimeoutError now produces a degraded narrative instead of failed.
        """
        llm = MockLLMClient()
        llm.generate = AsyncMock(  # type: ignore[method-assign]
            side_effect=TimeoutError("LLM call timed out"),
        )
        deps = _make_deps(llm=llm)
        state = _make_state()

        result = await run_pipeline(state, deps)

        assert result.status == TurnStatus.complete
        assert result.narrative_output is not None

    async def test_llm_queue_full_returns_failed(self) -> None:
        """When LLM semaphore is full, pipeline fails gracefully."""
        llm = MockLLMClient()
        llm.generate = AsyncMock(  # type: ignore[method-assign]
            side_effect=AppError(
                ErrorCategory.SERVICE_UNAVAILABLE,
                "LLM_QUEUE_FULL",
                "Too many concurrent requests",
            ),
        )
        deps = _make_deps(llm=llm)
        state = _make_state()

        result = await run_pipeline(state, deps)

        assert result.status == TurnStatus.failed

    async def test_original_state_preserved_on_degraded(self) -> None:
        """Degraded fallback doesn't corrupt session_id or player_input."""
        llm = MockLLMClient()
        llm.generate = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("boom"),
        )
        deps = _make_deps(llm=llm)
        sid = uuid4()
        state = _make_state(session_id=sid, player_input="test input")

        result = await run_pipeline(state, deps)

        assert result.status == TurnStatus.complete
        assert result.session_id == sid
        assert result.player_input == "test input"

    async def test_normal_pipeline_still_succeeds(self) -> None:
        """Sanity check: normal flow still works end-to-end."""
        deps = _make_deps()
        state = _make_state()

        result = await run_pipeline(state, deps)

        assert result.status == TurnStatus.complete
