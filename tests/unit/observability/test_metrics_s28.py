"""Unit tests for S28 performance metrics.

Spec ref: S28 §4 AC-28.01–28.03
"""

from __future__ import annotations

from prometheus_client import Gauge, Histogram

from tta.observability.metrics import (
    DURATION_BUCKETS,
    LLM_TOKENS_PER_SECOND,
    TURN_STAGE_DURATION,
    TURN_TOTAL_DURATION,
)


class TestTurnStageDuration:
    """AC-28.01: Per-stage duration histogram with outcome label."""

    def test_is_histogram(self) -> None:
        assert isinstance(TURN_STAGE_DURATION, Histogram)

    def test_metric_name(self) -> None:
        assert TURN_STAGE_DURATION._name == "tta_turn_stage_duration_seconds"

    def test_label_names(self) -> None:
        assert list(TURN_STAGE_DURATION._labelnames) == ["stage", "status"]

    def test_uses_standard_buckets(self) -> None:
        # Buckets stored without the +Inf sentinel
        assert tuple(TURN_STAGE_DURATION._upper_bounds[:-1]) == DURATION_BUCKETS

    def test_observe_success(self) -> None:
        TURN_STAGE_DURATION.labels(stage="generate", status="success").observe(0.5)

    def test_observe_error(self) -> None:
        TURN_STAGE_DURATION.labels(stage="understand", status="error").observe(0.1)

    def test_observe_timeout(self) -> None:
        TURN_STAGE_DURATION.labels(stage="enrich", status="timeout").observe(10.0)


class TestTurnTotalDuration:
    """AC-28.02: End-to-end pipeline duration histogram (drives TurnLatencyBudget)."""

    def test_is_histogram(self) -> None:
        assert isinstance(TURN_TOTAL_DURATION, Histogram)

    def test_metric_name(self) -> None:
        assert TURN_TOTAL_DURATION._name == "tta_turn_total_duration_seconds"

    def test_no_labels(self) -> None:
        assert list(TURN_TOTAL_DURATION._labelnames) == []

    def test_uses_standard_buckets(self) -> None:
        assert tuple(TURN_TOTAL_DURATION._upper_bounds[:-1]) == DURATION_BUCKETS

    def test_observe(self) -> None:
        TURN_TOTAL_DURATION.observe(1.25)

    def test_latency_budget_boundary(self) -> None:
        # 2 s is the alert threshold — must fall into a bucket
        TURN_TOTAL_DURATION.observe(2.0)
        TURN_TOTAL_DURATION.observe(2.001)


class TestLlmTokensPerSecond:
    """AC-28.03: LLM throughput gauge per model."""

    def test_is_gauge(self) -> None:
        assert isinstance(LLM_TOKENS_PER_SECOND, Gauge)

    def test_metric_name(self) -> None:
        assert LLM_TOKENS_PER_SECOND._name == "tta_llm_tokens_per_second"

    def test_label_names(self) -> None:
        assert list(LLM_TOKENS_PER_SECOND._labelnames) == ["model"]

    def test_set_value(self) -> None:
        LLM_TOKENS_PER_SECOND.labels(model="gpt-4o-mini").set(45.2)

    def test_set_zero(self) -> None:
        # Zero TPS is valid (e.g., empty response)
        LLM_TOKENS_PER_SECOND.labels(model="groq/llama3").set(0.0)
