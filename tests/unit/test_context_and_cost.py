"""Tests for S07 context window budget management and cost enforcement.

Covers:
- Context chunk priority fitting (FR-07.12–16, AC-07.3)
- Cost tracking and session budget checks (FR-07.17–22, AC-07.5)
- guarded_llm_call cost enforcement (BudgetExceededError)
"""

from __future__ import annotations

import pytest

from tta.llm.context_budget import (
    ContextChunk,
    Priority,
    count_tokens,
    fit_chunks_to_budget,
)
from tta.privacy.cost import LLMCostTracker, get_cost_tracker, reset_cost_tracker

# ── Token counting ──────────────────────────────────────────────────────


class TestCountTokens:
    """FR-07.14: over-counting OK, under-counting NOT OK."""

    def test_conservative_estimate(self) -> None:
        text = "Hello world, this is a test sentence."
        tokens = count_tokens(text)
        # len=37, //2 = 18; real tokens ~8-9, so we over-count (safe)
        assert tokens >= 8

    def test_empty_string_returns_one(self) -> None:
        assert count_tokens("") == 1

    def test_long_text_over_counts(self) -> None:
        text = "word " * 1000  # ~5000 chars, ~1000 real tokens
        tokens = count_tokens(text)
        assert tokens >= 1000  # Must not under-count


# ── Chunk fitting ────────────────────────────────────────────────────────


class TestFitChunksToBudget:
    """FR-07.12–13: P0 never truncated, P3 dropped first."""

    def _make_chunk(self, name: str, priority: Priority, tokens: int) -> ContextChunk:
        content = "x" * (tokens * 2)  # content that count_tokens maps to ~tokens
        return ContextChunk(
            name=name, content=content, priority=priority, token_count=tokens
        )

    def test_all_fit(self) -> None:
        chunks = [
            self._make_chunk("system", Priority.P0, 100),
            self._make_chunk("recent", Priority.P1, 200),
            self._make_chunk("world", Priority.P2, 300),
            self._make_chunk("history", Priority.P3, 100),
        ]
        result = fit_chunks_to_budget(chunks, budget_tokens=800)
        assert len(result.chunks) == 4
        assert result.dropped == []
        assert result.total_tokens == 700

    def test_p3_dropped_first(self) -> None:
        chunks = [
            self._make_chunk("system", Priority.P0, 100),
            self._make_chunk("recent", Priority.P1, 200),
            self._make_chunk("world", Priority.P2, 300),
            self._make_chunk("history", Priority.P3, 300),
        ]
        result = fit_chunks_to_budget(chunks, budget_tokens=650)
        assert "history" in result.dropped
        assert all(c.name != "history" for c in result.chunks)

    def test_p2_dropped_after_p3(self) -> None:
        chunks = [
            self._make_chunk("system", Priority.P0, 100),
            self._make_chunk("recent", Priority.P1, 200),
            self._make_chunk("world", Priority.P2, 300),
            self._make_chunk("history", Priority.P3, 300),
        ]
        # Budget only fits P0 + P1
        result = fit_chunks_to_budget(chunks, budget_tokens=350)
        assert "history" in result.dropped
        assert "world" in result.dropped
        assert len(result.chunks) == 2

    def test_p0_never_dropped(self) -> None:
        """P0 is always kept even if budget is exceeded."""
        chunks = [
            self._make_chunk("system", Priority.P0, 500),
            self._make_chunk("world", Priority.P2, 100),
        ]
        result = fit_chunks_to_budget(chunks, budget_tokens=100)
        assert any(c.name == "system" for c in result.chunks)
        assert "world" in result.dropped

    def test_p1_never_dropped(self) -> None:
        """P1 is always kept along with P0."""
        chunks = [
            self._make_chunk("system", Priority.P0, 100),
            self._make_chunk("recent", Priority.P1, 400),
            self._make_chunk("world", Priority.P2, 200),
        ]
        result = fit_chunks_to_budget(chunks, budget_tokens=200)
        kept_names = {c.name for c in result.chunks}
        assert "system" in kept_names
        assert "recent" in kept_names

    def test_empty_chunks(self) -> None:
        result = fit_chunks_to_budget([], budget_tokens=1000)
        assert result.chunks == []
        assert result.total_tokens == 0

    def test_result_sorted_by_priority(self) -> None:
        chunks = [
            self._make_chunk("history", Priority.P3, 50),
            self._make_chunk("system", Priority.P0, 50),
            self._make_chunk("world", Priority.P2, 50),
            self._make_chunk("recent", Priority.P1, 50),
        ]
        result = fit_chunks_to_budget(chunks, budget_tokens=1000)
        priorities = [c.priority for c in result.chunks]
        assert priorities == sorted(priorities)


# ── Cost tracker ─────────────────────────────────────────────────────────


class TestLLMCostTracker:
    """FR-07.17–22: cost recording and budget checks."""

    def test_session_total_seeded(self) -> None:
        tracker = LLMCostTracker(session_id="s1", session_total_usd=0.50)
        assert tracker.session_total_usd == 0.50

    def test_record_accumulates(self) -> None:
        tracker = LLMCostTracker(session_id="s1", session_total_usd=0.0)
        tracker.record(model="test", prompt_tokens=100, completion_tokens=50)
        # Unknown model → 0 cost, but call is still recorded
        assert len(tracker._calls) == 1
        assert tracker._calls[0]["prompt_tokens"] == 100.0

    def test_budget_ok(self) -> None:
        tracker = LLMCostTracker(session_id="s1", session_total_usd=0.10)
        status = tracker.check_session_budget(cap_usd=1.0, warn_pct=0.8)
        assert status == "ok"

    def test_budget_warning(self) -> None:
        tracker = LLMCostTracker(session_id="s1", session_total_usd=0.85)
        status = tracker.check_session_budget(cap_usd=1.0, warn_pct=0.8)
        assert status == "warning"

    def test_budget_exceeded(self) -> None:
        tracker = LLMCostTracker(session_id="s1", session_total_usd=1.05)
        status = tracker.check_session_budget(cap_usd=1.0, warn_pct=0.8)
        assert status == "exceeded"

    def test_reset_cost_tracker_seeds_total(self) -> None:
        tracker = reset_cost_tracker(session_id="s2", session_total_usd=0.33)
        assert tracker.session_total_usd == 0.33
        assert get_cost_tracker() is tracker


# ── Guarded LLM call cost enforcement ────────────────────────────────────


class TestGuardedLLMCallCostEnforcement:
    """FR-07.20: session cap enforcement via guarded_llm_call."""

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self) -> None:
        """When session cost exceeds cap, BudgetExceededError is raised."""
        from unittest.mock import AsyncMock, MagicMock

        from tta.llm.errors import BudgetExceededError
        from tta.llm.roles import ModelRole
        from tta.pipeline.llm_guard import guarded_llm_call

        # Seed tracker well over budget
        reset_cost_tracker(session_id="test", session_total_usd=5.0)

        # Create minimal deps with settings
        settings = MagicMock()
        settings.session_cost_cap_usd = 1.0
        settings.session_cost_warn_pct = 0.8

        deps = MagicMock()
        deps.settings = settings
        deps.llm_semaphore = None
        deps.llm_circuit_breaker = None
        deps.llm = AsyncMock()

        with pytest.raises(BudgetExceededError):
            await guarded_llm_call(
                deps=deps,
                role=ModelRole.GENERATION,
                messages=[{"role": "user", "content": "test"}],
            )

    @pytest.mark.asyncio
    async def test_under_budget_proceeds(self) -> None:
        """When under budget, the LLM call proceeds normally."""
        from unittest.mock import AsyncMock, MagicMock

        from tta.llm.client import LLMResponse
        from tta.llm.roles import ModelRole
        from tta.models.turn import TokenCount
        from tta.pipeline.llm_guard import guarded_llm_call

        reset_cost_tracker(session_id="test", session_total_usd=0.01)

        settings = MagicMock()
        settings.session_cost_cap_usd = 1.0
        settings.session_cost_warn_pct = 0.8

        mock_response = LLMResponse(
            content="hello",
            model_used="test-model",
            token_count=TokenCount(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
            latency_ms=50.0,
            cost_usd=0.001,
        )

        deps = MagicMock()
        deps.settings = settings
        deps.llm_semaphore = None
        deps.llm_circuit_breaker = None
        deps.llm = AsyncMock()
        deps.llm.generate = AsyncMock(return_value=mock_response)

        result = await guarded_llm_call(
            deps=deps,
            role=ModelRole.GENERATION,
            messages=[{"role": "user", "content": "test"}],
        )
        assert result.content == "hello"

    @pytest.mark.asyncio
    async def test_no_settings_skips_budget_check(self) -> None:
        """When deps.settings is None, budget check is skipped."""
        from unittest.mock import AsyncMock, MagicMock

        from tta.llm.client import LLMResponse
        from tta.llm.roles import ModelRole
        from tta.models.turn import TokenCount
        from tta.pipeline.llm_guard import guarded_llm_call

        # Over budget but no settings → should NOT raise
        reset_cost_tracker(session_id="test", session_total_usd=99.0)

        mock_response = LLMResponse(
            content="hello",
            model_used="test-model",
            token_count=TokenCount(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
            latency_ms=50.0,
            cost_usd=0.001,
        )

        deps = MagicMock()
        deps.settings = None
        deps.llm_semaphore = None
        deps.llm_circuit_breaker = None
        deps.llm = AsyncMock()
        deps.llm.generate = AsyncMock(return_value=mock_response)

        result = await guarded_llm_call(
            deps=deps,
            role=ModelRole.GENERATION,
            messages=[{"role": "user", "content": "test"}],
        )
        assert result.content == "hello"
