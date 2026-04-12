"""Tests for LLM cost tracking (S15 §4 US-15.11, ops.md §3.4)."""

import pytest

from tta.privacy.cost import (
    ModelPricing,
    estimate_cost,
    get_cost_tracker,
    reset_cost_tracker,
)


class TestModelPricing:
    def test_defaults_are_populated(self) -> None:
        p = ModelPricing(
            model="test-model",
            prompt_cost_per_1m=0.15,
            completion_cost_per_1m=0.60,
        )
        assert p.model == "test-model"
        assert p.prompt_cost_per_1m == 0.15
        assert p.completion_cost_per_1m == 0.60


class TestEstimateCost:
    def test_known_model(self) -> None:
        cost = estimate_cost(
            "openai/gpt-4o-mini", prompt_tokens=1000, completion_tokens=500
        )
        assert cost > 0.0

    def test_unknown_model_returns_zero(self) -> None:
        cost = estimate_cost(
            "unknown-model-xyz", prompt_tokens=100, completion_tokens=50
        )
        assert cost == 0.0

    def test_zero_tokens(self) -> None:
        cost = estimate_cost("openai/gpt-4o-mini", prompt_tokens=0, completion_tokens=0)
        assert cost == 0.0

    def test_cost_proportional_to_tokens(self) -> None:
        cost_small = estimate_cost(
            "openai/gpt-4o-mini", prompt_tokens=100, completion_tokens=50
        )
        cost_big = estimate_cost(
            "openai/gpt-4o-mini", prompt_tokens=1000, completion_tokens=500
        )
        assert cost_big == pytest.approx(cost_small * 10, rel=1e-6)


class TestLLMCostTracker:
    def setup_method(self) -> None:
        reset_cost_tracker()

    def test_record_and_summary(self) -> None:
        tracker = get_cost_tracker()
        tracker.record(
            model="openai/gpt-4o-mini",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        summary = tracker.summary()
        assert summary["call_count"] == 1
        assert summary["session_total_usd"] > 0  # type: ignore[operator]

    def test_multiple_records_accumulate(self) -> None:
        tracker = get_cost_tracker()
        tracker.record(
            model="openai/gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=50,
        )
        tracker.record(
            model="openai/gpt-4o-mini",
            prompt_tokens=200,
            completion_tokens=100,
        )
        summary = tracker.summary()
        assert summary["call_count"] == 2

    def test_singleton_behavior(self) -> None:
        t1 = get_cost_tracker()
        t2 = get_cost_tracker()
        assert t1 is t2

    def test_reset_clears_state(self) -> None:
        tracker = get_cost_tracker()
        tracker.record(
            model="openai/gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=50,
        )
        reset_cost_tracker()
        new_tracker = get_cost_tracker()
        assert new_tracker is not tracker
        assert new_tracker.summary()["call_count"] == 0

    def test_unknown_model_tracked_with_zero_cost(self) -> None:
        tracker = get_cost_tracker()
        tracker.record(
            model="unknown-model",
            prompt_tokens=100,
            completion_tokens=50,
        )
        summary = tracker.summary()
        assert summary["call_count"] == 1
        assert summary["session_total_usd"] == 0.0
