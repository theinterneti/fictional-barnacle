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

# -- Cost tracking metrics (S15 §4 US-15.11, S07 §6 FR-07.22) -------------

LLM_COST_DAILY_USD = Gauge(
    "tta_llm_cost_daily_usd",
    "Cumulative LLM cost in USD since last reset (daily)",
    registry=REGISTRY,
)

LLM_COST_TOTAL = Counter(
    "tta_llm_cost_usd_total",
    "Cumulative LLM cost in USD by model and role",
    ["model", "role"],
    registry=REGISTRY,
)

SESSION_COST_EXCEEDED = Counter(
    "tta_session_cost_exceeded_total",
    "Sessions that hit the cost cap",
    registry=REGISTRY,
)

CONTEXT_CHUNKS_DROPPED = Counter(
    "tta_context_chunks_dropped_total",
    "Context chunks dropped due to budget fitting",
    registry=REGISTRY,
)


# -- Connection pool metrics (S28 FR-28.10) --------------------------------

PG_POOL_SIZE = Gauge(
    "tta_pg_pool_size",
    "PostgreSQL connection pool size",
    registry=REGISTRY,
)

PG_POOL_CHECKED_OUT = Gauge(
    "tta_pg_pool_checked_out",
    "PostgreSQL connections currently checked out",
    registry=REGISTRY,
)

PG_POOL_OVERFLOW = Gauge(
    "tta_pg_pool_overflow",
    "PostgreSQL pool overflow connections",
    registry=REGISTRY,
)

REDIS_POOL_ACTIVE = Gauge(
    "tta_redis_pool_active_connections",
    "Redis active connections",
    registry=REGISTRY,
)

NEO4J_POOL_ACTIVE = Gauge(
    "tta_neo4j_pool_active_connections",
    "Neo4j active connections",
    registry=REGISTRY,
)

# -- Rate limiting & abuse metrics (S15 §4, S25) ---------------------------

RATE_LIMIT_ENFORCED = Counter(
    "tta_rate_limit_enforced_total",
    "Rate limit rejections",
    ["route"],
    registry=REGISTRY,
)

ABUSE_DETECTED = Counter(
    "tta_abuse_detected_total",
    "Abuse pattern violations detected",
    ["pattern"],
    registry=REGISTRY,
)

# -- DB & Redis metrics (S15 §4) ------------------------------------------

DB_QUERY_DURATION = Histogram(
    "tta_db_query_duration_seconds",
    "Database query duration",
    ["database", "operation"],
    buckets=DURATION_BUCKETS,
    registry=REGISTRY,
)

REDIS_OPERATIONS = Counter(
    "tta_redis_operations_total",
    "Redis operations",
    ["operation"],
    registry=REGISTRY,
)

# -- S12 Persistence metrics -----------------------------------------------

# AC-12.05: Redis cache read/write latency (p95 < 5 ms target)
REDIS_CACHE_BUCKETS = (
    0.0005,
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
)

REDIS_CACHE_READ_DURATION = Histogram(
    "tta_redis_cache_read_duration_seconds",
    "Redis cache read latency",
    ["operation"],
    buckets=REDIS_CACHE_BUCKETS,
    registry=REGISTRY,
)

REDIS_CACHE_WRITE_DURATION = Histogram(
    "tta_redis_cache_write_duration_seconds",
    "Redis cache write latency",
    ["operation"],
    buckets=REDIS_CACHE_BUCKETS,
    registry=REGISTRY,
)

# AC-12.07: Turn storage ops latency (p95 < 200 ms target)
STORAGE_OPS_BUCKETS = (
    0.01,
    0.025,
    0.05,
    0.1,
    0.2,
    0.5,
)

TURN_STORAGE_OPS_DURATION = Histogram(
    "tta_turn_storage_ops_duration_seconds",
    "Turn storage operations duration (SQL + cache)",
    ["operation"],
    buckets=STORAGE_OPS_BUCKETS,
    registry=REGISTRY,
)

# AC-12.02: Cache reconstruction metrics
CACHE_RECONSTRUCTION_TOTAL = Counter(
    "tta_cache_reconstruction_total",
    "Cache reconstruction events after Redis miss",
    registry=REGISTRY,
)

CACHE_RECONSTRUCTION_DURATION = Histogram(
    "tta_cache_reconstruction_duration_seconds",
    "Cache reconstruction duration",
    buckets=STORAGE_OPS_BUCKETS,
    registry=REGISTRY,
)

# AC-12.12: Redis TTL compliance
REDIS_KEYS_WITHOUT_TTL = Gauge(
    "tta_redis_keys_without_ttl",
    "Redis keys missing a TTL in the tta: namespace",
    labelnames=["prefix"],
    registry=REGISTRY,
)

# -- LLM semaphore metrics (S28 FR-28.11) ---------------------------------

LLM_SEMAPHORE_ACTIVE = Gauge(
    "tta_llm_semaphore_active",
    "LLM requests currently executing",
    registry=REGISTRY,
)

LLM_SEMAPHORE_WAITING = Gauge(
    "tta_llm_semaphore_waiting",
    "LLM requests waiting in queue",
    registry=REGISTRY,
)


# -- S12 state-drift detection (AC-12.04, EC-12.01) -----------------------

STATE_DRIFT_CHECKS = Counter(
    "tta_state_drift_checks_total",
    "Number of Redis/SQL consistency checks performed",
    registry=REGISTRY,
)

STATE_DRIFT_DETECTED = Counter(
    "tta_state_drift_detected_total",
    "Number of Redis/SQL inconsistencies detected",
    labelnames=["kind"],
    registry=REGISTRY,
)


# -- S10 SSE replay buffer metrics (FR-10.41–10.44) --------------------------

SSE_REPLAY_HITS = Counter(
    "tta_sse_replay_hits_total",
    "Number of SSE reconnections that were served from the replay buffer",
    registry=REGISTRY,
)

SSE_REPLAY_MISSES = Counter(
    "tta_sse_replay_misses_total",
    "Number of SSE reconnections where the replay buffer was exhausted",
    registry=REGISTRY,
)

SSE_BUFFER_SIZE = Gauge(
    "tta_sse_buffer_size",
    "Current number of events in the SSE replay buffer for a game",
    labelnames=["game_id"],
    registry=REGISTRY,
)


def metrics_output() -> bytes:
    """Generate Prometheus metrics output from the registry."""
    return generate_latest(REGISTRY)
