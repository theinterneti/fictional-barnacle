"""Tests for Prometheus metrics module."""

from __future__ import annotations

from prometheus_client import CollectorRegistry

from tta.observability.metrics import (
    DURATION_BUCKETS,
    HTTP_IN_FLIGHT,
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_TOTAL,
    REGISTRY,
    SESSION_DURATION,
    SESSION_TURNS,
    SESSIONS_ACTIVE,
    TURN_DURATION,
    TURN_LLM_CALLS,
    TURN_LLM_COST,
    TURN_LLM_DURATION,
    TURN_LLM_TOKENS,
    TURN_SAFETY_FLAGS,
    TURN_TOTAL,
    metrics_output,
)


class TestRegistrySetup:
    """Metrics use a custom CollectorRegistry for test isolation."""

    def test_registry_is_collector_registry(self) -> None:
        assert isinstance(REGISTRY, CollectorRegistry)

    def test_registry_not_default(self) -> None:
        from prometheus_client import REGISTRY as DEFAULT_REGISTRY

        assert REGISTRY is not DEFAULT_REGISTRY


class TestDurationBuckets:
    """DURATION_BUCKETS matches the ops.md spec."""

    def test_bucket_values(self) -> None:
        expected = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
        assert DURATION_BUCKETS == expected

    def test_bucket_count(self) -> None:
        assert len(DURATION_BUCKETS) == 10


class TestHTTPMetrics:
    """HTTP-level Prometheus metrics are registered."""

    def test_requests_total_labels(self) -> None:
        assert HTTP_REQUESTS_TOTAL._labelnames == ("method", "route", "status")

    def test_request_duration_labels(self) -> None:
        assert HTTP_REQUEST_DURATION._labelnames == ("method", "route")

    def test_in_flight_is_gauge(self) -> None:
        HTTP_IN_FLIGHT.inc()
        HTTP_IN_FLIGHT.dec()


class TestPipelineMetrics:
    """Pipeline-level Prometheus metrics are registered."""

    def test_turn_duration_labels(self) -> None:
        assert TURN_DURATION._labelnames == ("stage",)

    def test_turn_total_labels(self) -> None:
        assert TURN_TOTAL._labelnames == ("status",)

    def test_llm_calls_labels(self) -> None:
        assert TURN_LLM_CALLS._labelnames == ("model", "provider")

    def test_llm_duration_labels(self) -> None:
        assert TURN_LLM_DURATION._labelnames == ("model",)

    def test_llm_tokens_labels(self) -> None:
        assert TURN_LLM_TOKENS._labelnames == ("model", "direction")

    def test_llm_cost_labels(self) -> None:
        assert TURN_LLM_COST._labelnames == ("model",)

    def test_safety_flags_labels(self) -> None:
        assert TURN_SAFETY_FLAGS._labelnames == ("level",)


class TestSessionMetrics:
    """Session-level Prometheus metrics are registered."""

    def test_sessions_active_is_gauge(self) -> None:
        SESSIONS_ACTIVE.inc()
        SESSIONS_ACTIVE.dec()

    def test_session_duration_exists(self) -> None:
        assert SESSION_DURATION._name == "tta_session_duration_seconds"

    def test_session_turns_exists(self) -> None:
        assert SESSION_TURNS._name == "tta_session_turns_total"


class TestMetricsOutput:
    """metrics_output() returns valid Prometheus exposition format."""

    def test_returns_bytes(self) -> None:
        output = metrics_output()
        assert isinstance(output, bytes)

    def test_contains_metric_names(self) -> None:
        TURN_TOTAL.labels(status="success").inc()
        output = metrics_output().decode()
        assert "tta_turn_total" in output

    def test_contains_help_text(self) -> None:
        output = metrics_output().decode()
        assert "# HELP" in output

    def test_contains_type_text(self) -> None:
        output = metrics_output().decode()
        assert "# TYPE" in output
