"""Prometheus metrics for TTA.

Defines all application metrics exposed via ``/metrics``.
Labels are kept low-cardinality (no raw IDs, no user data).

Spec ref: S15 §4 (metrics), plans/ops.md §5.3 (metric inventory).
"""

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

# Shared histogram buckets (seconds) — ops.md §5.3
DURATION_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

# -- HTTP metrics ----------------------------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    "tta_http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION = Histogram(
    "tta_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "route"],
    buckets=DURATION_BUCKETS,
    registry=REGISTRY,
)

HTTP_IN_FLIGHT = Gauge(
    "tta_http_requests_in_flight",
    "HTTP requests currently being processed",
    registry=REGISTRY,
)

# -- Turn pipeline metrics -------------------------------------------------

TURN_DURATION = Histogram(
    "tta_turn_processing_duration_seconds",
    "Turn processing duration by pipeline stage",
    ["stage"],
    buckets=DURATION_BUCKETS,
    registry=REGISTRY,
)

TURN_TOTAL = Counter(
    "tta_turn_total",
    "Total turns processed",
    ["status"],
    registry=REGISTRY,
)

TURN_LLM_CALLS = Counter(
    "tta_turn_llm_calls_total",
    "Total LLM calls",
    ["model", "provider"],
    registry=REGISTRY,
)

TURN_LLM_DURATION = Histogram(
    "tta_turn_llm_duration_seconds",
    "LLM call duration in seconds",
    ["model"],
    buckets=DURATION_BUCKETS,
    registry=REGISTRY,
)

TURN_LLM_TOKENS = Counter(
    "tta_turn_llm_tokens_total",
    "Total LLM tokens",
    ["model", "direction"],
    registry=REGISTRY,
)

TURN_LLM_COST = Histogram(
    "tta_turn_llm_cost_usd",
    "LLM call cost in USD",
    ["model"],
    registry=REGISTRY,
)

TURN_SAFETY_FLAGS = Counter(
    "tta_turn_safety_flags_total",
    "Safety flags raised during turn processing",
    ["level"],
    registry=REGISTRY,
)

# -- Session metrics -------------------------------------------------------

SESSIONS_ACTIVE = Gauge(
    "tta_sessions_active",
    "Currently active game sessions",
    registry=REGISTRY,
)

SESSION_DURATION = Histogram(
    "tta_session_duration_seconds",
    "Game session duration in seconds",
    buckets=DURATION_BUCKETS,
    registry=REGISTRY,
)

SESSION_TURNS = Histogram(
    "tta_session_turns_total",
    "Turns per game session",
    registry=REGISTRY,
)


def metrics_output() -> bytes:
    """Generate Prometheus metrics output from the registry."""
    return generate_latest(REGISTRY)
