# S15 — Observability

> **Status**: 📝 Draft
> **Level**: 4 — Operations
> **Dependencies**: S08 (Turn Pipeline), S14 (Deployment)
> **Last Updated**: 2026-04-09

## Overview

This spec defines how TTA exposes its internal state to operators and developers. Observability is built on three pillars — logs, metrics, and traces — using OSS-first tooling. LLM-specific observability uses Langfuse. General-purpose observability uses OpenTelemetry.

The goal is not enterprise-grade monitoring. The goal is: **when something goes wrong, can a developer figure out what happened within 5 minutes?**

### Out of Scope

- **APM SaaS (Datadog, New Relic)** — OSS-first stack; commercial APM is unnecessary for v1 — future if commercialized
- **Log aggregation (ELK, Loki)** — stdout + `docker compose logs` suffice for v1 — future ops maturity
- **Synthetic monitoring / uptime checks** — single-developer project, no SLA — future ops maturity
- **User-facing error tracking (Sentry)** — structured logs and traces cover v1 debugging needs — future enhancement
- **SLO / SLA definitions** — no production environment in v1 — revisit when staging becomes production
- **Custom Grafana plugin development** — pre-built dashboards with standard panels only — Grafana ecosystem

---

## 1. Logging

### 1.1 User Stories

- **US-15.1**: As a developer, I can read structured logs and understand what happened during a player turn without reading source code.
- **US-15.2**: As an operator, I can change the log level at runtime without restarting the application.
- **US-15.3**: As a developer, I can filter logs by player session, request ID, or component.

### 1.2 Functional Requirements

**FR-15.1**: All application logs SHALL be structured JSON. No free-form print statements or unstructured log lines in application code.

```json
{
  "timestamp": "2025-07-24T12:00:00.000Z",
  "level": "info",
  "logger": "tta.turn_pipeline",
  "message": "Turn processing complete",
  "turn_id": "turn_abc123",
  "session_id": "sess_xyz789",
  "player_id": "player_42",
  "duration_ms": 1523,
  "llm_model": "gpt-4o-mini",
  "trace_id": "abc123def456"
}
```

**FR-15.2**: Every log entry SHALL include the following context fields when available:
- `trace_id` — OpenTelemetry trace ID
- `session_id` — player session
- `turn_id` — current turn being processed
- `player_id` — anonymized or pseudonymized player identifier

**FR-15.3**: Log levels SHALL follow standard semantics:

| Level | When to use | Example |
|-------|-------------|---------|
| `ERROR` | Something failed and the operation could not complete | LLM API returned 500, database write failed |
| `WARNING` | Something unexpected but the operation continued | LLM response was slow (> 5s), retry succeeded |
| `INFO` | Key lifecycle events | Turn started, turn completed, session created |
| `DEBUG` | Detailed internal state for troubleshooting | Prompt template rendered, cache hit/miss |

**FR-15.4**: The application SHALL support the following log level configuration:
- Default: `INFO` in staging, `DEBUG` in development, `WARNING` in testing.
- Override via `TTA_LOG_LEVEL` environment variable.
- Runtime change via admin endpoint `POST /admin/log-level` (development and staging only).

**FR-15.5**: Logs SHALL be written to stdout. The deployment environment (Docker, CI) handles log routing. The application SHALL NOT manage log files, rotation, or shipping.

### 1.3 What NOT to Log

**FR-15.6**: The following SHALL NOT appear in logs at any level:

| Data | Reason | Alternative |
|------|--------|-------------|
| Raw player input text | Privacy — may contain personal disclosures | Log input length, intent classification, or hash |
| Full LLM prompts | May embed player data; logged separately in Langfuse | Log prompt template name and version |
| Full LLM responses | Privacy, volume | Log response length, safety classification |
| API keys or secrets | Security | Never log, period |
| Database connection strings with passwords | Security | Log host/port only |
| Player IP addresses | Privacy (GDPR) | Log anonymized region if needed |

**FR-15.7**: In development mode (`TTA_ENV=development`), the restriction on logging player input and LLM prompts MAY be relaxed via an explicit opt-in flag (`TTA_LOG_SENSITIVE=true`). This flag SHALL NOT be settable in staging.

### 1.4 Edge Cases

- **EC-15.1**: If structured logging fails (serialization error), the system SHALL fall back to a plain-text log line containing the error rather than silently dropping the log.
- **EC-15.2**: If a log line exceeds 64KB, it SHALL be truncated with a `[truncated]` marker.

### 1.5 Acceptance Criteria

- [ ] All log lines are valid JSON when parsed by a standard JSON parser.
- [ ] Filtering logs by `session_id` returns all log lines for a single player session.
- [ ] No log line at INFO level or below contains raw player input text.
- [ ] Changing `TTA_LOG_LEVEL` to `ERROR` silences INFO and WARNING logs without restart.

---

## 2. Metrics

### 2.1 User Stories

- **US-15.4**: As an operator, I can see the current request rate and error rate at a glance.
- **US-15.5**: As a developer, I can identify which LLM model is slowest or most expensive.
- **US-15.6**: As an operator, I can see how many concurrent sessions are active.

### 2.2 Functional Requirements

**FR-15.8**: Metrics SHALL be exposed via a Prometheus-compatible `/metrics` endpoint on the API container.

**FR-15.9**: The following metrics SHALL be collected:

#### HTTP Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tta_http_requests_total` | Counter | `method`, `path`, `status` | Total HTTP requests |
| `tta_http_request_duration_seconds` | Histogram | `method`, `path` | Request latency |
| `tta_http_requests_in_flight` | Gauge | — | Currently processing requests |

#### Turn Pipeline Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tta_turn_processing_duration_seconds` | Histogram | `stage` | Time per pipeline stage |
| `tta_turn_total` | Counter | `status` | Turns processed (success/failure) |
| `tta_turn_llm_calls_total` | Counter | `model`, `provider` | LLM API calls |
| `tta_turn_llm_duration_seconds` | Histogram | `model` | LLM response time |
| `tta_turn_llm_tokens_total` | Counter | `model`, `direction` | Tokens used (prompt/completion) |
| `tta_turn_safety_flags_total` | Counter | `level` | Safety system activations |

#### Session Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tta_sessions_active` | Gauge | — | Currently active sessions |
| `tta_session_duration_seconds` | Histogram | — | Session lifetime |
| `tta_session_turns_total` | Histogram | — | Turns per session |

#### Infrastructure Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tta_db_query_duration_seconds` | Histogram | `database`, `operation` | Database query latency |
| `tta_db_connections_active` | Gauge | `database` | Active DB connections |
| `tta_redis_operations_total` | Counter | `operation` | Redis operations |

**FR-15.10**: Histogram buckets for latency metrics SHALL include: `0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0` seconds.

**FR-15.11**: Metrics SHALL have low cardinality. Path labels SHALL use route patterns (`/api/turn/{session_id}`), not actual paths (`/api/turn/sess_abc123`).

### 2.3 Acceptance Criteria

- [ ] `GET /metrics` returns Prometheus-format text.
- [ ] After processing 10 turns, `tta_turn_total` shows a count of 10.
- [ ] LLM token usage is tracked per model.
- [ ] No metric label has unbounded cardinality (no raw IDs in labels).

---

## 3. Distributed Tracing

### 3.1 User Stories

- **US-15.7**: As a developer, I can trace a single player turn from HTTP request through every pipeline stage to the final SSE response.
- **US-15.8**: As a developer, I can see how much time was spent in the LLM vs. database vs. application logic for any given turn.

### 3.2 Functional Requirements

**FR-15.12**: The application SHALL use OpenTelemetry (OTel) for distributed tracing. Traces SHALL be exportable to any OTel-compatible backend (Jaeger, Zipkin, or Grafana Tempo).

**FR-15.13**: For v1 local development, the recommended trace backend is **Jaeger** (all-in-one Docker image). For staging, traces MAY go to Grafana Tempo or be disabled.

**FR-15.14**: Every incoming HTTP request SHALL create a root span. The following child spans SHALL be created within a turn processing request:

```
HTTP POST /api/turn
├── input_validation
├── session_load (Redis)
├── turn_pipeline
│   ├── input_understanding
│   │   └── llm_call (model, tokens, duration)
│   ├── context_assembly
│   │   ├── neo4j_query (world state load)
│   │   └── llm_call
│   ├── generation (Narrative Generation)
│   │   └── llm_call
│   └── delivery
├── session_save (Redis)
└── sse_stream_start
```

**FR-15.15**: Each span SHALL include relevant attributes:
- LLM spans: `llm.model`, `llm.provider`, `llm.tokens.prompt`, `llm.tokens.completion`, `llm.cost_usd`
- Database spans: `db.system`, `db.operation`, `db.statement` (sanitized, no values)
- Pipeline spans: `turn.id`, `session.id`, `player.id`

**FR-15.16**: The trace ID SHALL be returned in the HTTP response header `X-Trace-Id` for correlation with client-side debugging.

### 3.3 Edge Cases

- **EC-15.3**: If the trace backend is unreachable, tracing SHALL degrade silently. No traces are lost from the application's perspective — they're simply not exported. Application functionality is unaffected.
- **EC-15.4**: If a span name is missing (bug in instrumentation), the span SHALL be named `unknown` rather than causing a crash.
- **EC-15.5**: If Langfuse is configured but unreachable at runtime (network partition, service crash), LLM calls SHALL proceed without Langfuse instrumentation. A warning SHALL be logged (not per-call — throttled to once per minute). Gameplay MUST NOT be affected by Langfuse availability.

### 3.4 Acceptance Criteria

- [ ] A single turn generates a trace with at least 5 spans (HTTP, pipeline stages, LLM call).
- [ ] Trace includes LLM token counts and estimated cost.
- [ ] `X-Trace-Id` header is present in HTTP responses.
- [ ] Disabling the trace exporter does not affect application behavior.

---

## 4. LLM Observability (Langfuse)

### 4.1 User Stories

- **US-15.9**: As a developer, I can see the exact prompt sent to the LLM and the exact response received, for any turn, in Langfuse.
- **US-15.10**: As a developer, I can compare prompt performance across different models or prompt versions.
- **US-15.11**: As an operator, I can see total LLM cost per day/week/month.

### 4.2 Functional Requirements

**FR-15.17**: All LLM calls SHALL be instrumented via Langfuse. Each call SHALL record:
- Prompt template name and version
- Rendered prompt (full text sent to LLM)
- Model name and provider
- Completion text (full response from LLM)
- Token counts (prompt, completion, total)
- Latency (time to first token, total time)
- Estimated cost in USD
- Associated `trace_id`, `session_id`, `turn_id`

**FR-15.18**: Langfuse traces SHALL be organized hierarchically:
- **Session** = player game session
- **Trace** = single turn
- **Generation** = single LLM call within a turn (there may be multiple per turn — in different pipeline stages: input understanding, context assembly, generation)

**FR-15.19**: Langfuse SHALL be optional. If `TTA_OBS_LANGFUSE_PUBLIC_KEY` is not set, LLM calls proceed without Langfuse instrumentation and a warning is logged at startup.

**FR-15.20**: Prompt templates SHALL be versioned in Langfuse. When a prompt is updated, the old version is preserved and both versions can be compared in the Langfuse UI.

### 4.3 Privacy Considerations

**FR-15.21**: Langfuse stores full prompts and completions. Since prompts may contain player input and completions contain narrative responses:
- Players SHALL be informed that their game interactions are logged for quality improvement (see S17 — Data Privacy).
- Player identifiers in Langfuse SHALL be pseudonymized (use `player_id` hash, not username or email).
- A mechanism SHALL exist to purge a specific player's Langfuse data on request (GDPR erasure).

### 4.4 Acceptance Criteria

- [ ] Every LLM call appears in Langfuse with prompt, completion, model, cost, and latency.
- [ ] Langfuse traces are linked to OTel traces via shared trace ID.
- [ ] Starting without Langfuse keys does not prevent the application from running.
- [ ] LLM cost per session is calculable from Langfuse data.

---

## 5. Alerting

### 5.1 User Stories

- **US-15.12**: As an operator, I am notified when the error rate exceeds normal levels.
- **US-15.13**: As an operator, I am notified when LLM costs spike unexpectedly.

### 5.2 Functional Requirements

**FR-15.22**: For v1, alerting is simple: log-based alerts or basic Prometheus alerting rules. No PagerDuty, no on-call rotation.

**FR-15.23**: The following conditions SHALL generate alerts:

| Condition | Severity | Action |
|-----------|----------|--------|
| API error rate > 10% over 5 minutes | Critical | Log alert, optional webhook |
| LLM API unreachable for > 2 minutes | Critical | Log alert |
| Turn processing time > 30 seconds (p95) | Warning | Log alert |
| Daily LLM cost exceeds configured threshold | Warning | Log alert |
| Database connection pool exhausted | Critical | Log alert |
| Disk usage > 80% on any volume | Warning | Log alert |

**FR-15.24**: Alerts SHALL be idempotent. The same condition SHALL NOT generate repeated alerts more frequently than once per 15 minutes.

**FR-15.25**: Alert thresholds SHALL be configurable via environment variables, not hardcoded.

### 5.3 Acceptance Criteria

- [ ] Simulating 10% error rate for 5 minutes triggers a log alert.
- [ ] Alert thresholds are configurable via env vars.
- [ ] The same alert does not fire more than once in 15 minutes.

---

## 6. Dashboards

### 6.1 User Stories

- **US-15.14**: As an operator, I can see system health at a glance on a single dashboard page.
- **US-15.15**: As a developer, I can see LLM cost breakdown by model and prompt version.

### 6.2 Functional Requirements

**FR-15.26**: The project SHALL include a Grafana dashboard definition (JSON export) with the following panels:

**System Health Dashboard:**
- Request rate (requests/second)
- Error rate (percentage)
- Response time (p50, p95, p99)
- Active sessions count
- Container health status

**Turn Pipeline Dashboard:**
- Turn processing time breakdown by stage
- LLM call latency by model
- Token usage over time
- Safety flag activations
- Turn success/failure rate

**Cost Dashboard:**
- LLM cost per hour/day
- Cost per model
- Cost per turn (average)
- Cost per session (average)
- Projected monthly cost

**FR-15.27**: Dashboards SHALL be provisioned automatically when Grafana starts (via Grafana provisioning). No manual import required.

**FR-15.28**: Grafana is optional for v1. The `/metrics` endpoint and Langfuse provide sufficient observability without Grafana. Grafana is a nice-to-have for visual operators.

### 6.3 Acceptance Criteria

- [ ] Starting Grafana (if included in Compose) shows pre-configured dashboards.
- [ ] The system health dashboard updates in real-time during gameplay.
- [ ] Cost dashboard shows per-model cost breakdown.

---

## 7. Correlation

### 7.1 User Stories

- **US-15.16**: As a developer investigating a bug report, I can take a session ID and find all related logs, traces, metrics, and Langfuse data.

### 7.2 Functional Requirements

**FR-15.29**: Every operation within a player turn SHALL share a common `trace_id` across:
- Application logs (JSON field)
- OpenTelemetry traces (trace context)
- Langfuse traces (metadata field)
- HTTP response headers (`X-Trace-Id`)

**FR-15.30**: Every operation within a session SHALL share a common `session_id` across all three systems.

**FR-15.31**: Given a `session_id`, it SHALL be possible to:
1. Find all log lines for that session (log search by `session_id`).
2. Find all traces for that session (OTel trace search).
3. Find all LLM calls for that session (Langfuse session view).
4. Determine total cost for that session (Langfuse cost aggregation).

### 7.3 Acceptance Criteria

- [ ] A single `session_id` retrieves correlated data from logs, traces, and Langfuse.
- [ ] A single `trace_id` retrieves the full turn processing trace from OTel and Langfuse.
- [ ] No observability system uses a different ID format (all use the same `trace_id` string).

---

## 8. Sensitive Data Handling

### 8.1 Functional Requirements

**FR-15.32**: The following data classification SHALL govern what appears in observability systems:

| Data | Logs | Metrics | Traces | Langfuse |
|------|------|---------|--------|----------|
| Player input text | ❌ (hash only) | ❌ | ❌ | ✅ (with consent) |
| LLM prompt (full) | ❌ | ❌ | ❌ | ✅ (with consent) |
| LLM response (full) | ❌ | ❌ | ❌ | ✅ (with consent) |
| Token counts | ✅ | ✅ | ✅ | ✅ |
| Model name | ✅ | ✅ | ✅ | ✅ |
| Cost | ✅ | ✅ | ✅ | ✅ |
| Player ID (pseudonymized) | ✅ | ❌ | ✅ | ✅ |
| Session ID | ✅ | ❌ | ✅ | ✅ |
| API keys | ❌ | ❌ | ❌ | ❌ |
| Database passwords | ❌ | ❌ | ❌ | ❌ |

**FR-15.33**: Langfuse is the ONLY system that stores full prompt/completion text. This is by design — Langfuse is the controlled environment for LLM data review. Logs and traces SHALL NOT duplicate this data.

### 8.2 Acceptance Criteria

- [ ] A search across all log files for known player input text returns zero results.
- [ ] Langfuse contains the full prompt and completion for every LLM call.
- [ ] No trace span attribute contains player input text.

---

## 9. Cost Tracking

### 9.1 User Stories

- **US-15.17**: As an operator, I can see how much LLM usage costs per day and per player session.
- **US-15.18**: As a developer, I can compare cost between different models to make informed model selection decisions.

### 9.2 Functional Requirements

**FR-15.34**: Every LLM call SHALL calculate estimated cost based on:
- Model pricing (configured per model, updatable without code changes)
- Token counts (prompt + completion)
- Formula: `cost = (prompt_tokens * prompt_price_per_1k / 1000) + (completion_tokens * completion_price_per_1k / 1000)`

**FR-15.35**: Model pricing SHALL be stored in a configuration file (not hardcoded). The format:

```yaml
llm_pricing:
  gpt-4o-mini:
    prompt_per_1k_tokens: 0.00015
    completion_per_1k_tokens: 0.0006
  gpt-4o:
    prompt_per_1k_tokens: 0.005
    completion_per_1k_tokens: 0.015
```

**FR-15.36**: Cost SHALL be recorded as:
- A metric (`tta_turn_llm_cost_usd` histogram, labeled by model)
- A Langfuse generation attribute
- A trace span attribute

**FR-15.37**: A daily cost summary SHALL be logged at INFO level at midnight UTC:
```json
{
  "message": "Daily LLM cost summary",
  "date": "2025-07-24",
  "total_cost_usd": 12.34,
  "by_model": {
    "gpt-4o-mini": 8.50,
    "gpt-4o": 3.84
  },
  "total_turns": 1523,
  "avg_cost_per_turn_usd": 0.0081
}
```

### 9.3 Acceptance Criteria

- [ ] Every LLM call has an estimated cost in USD recorded in metrics and Langfuse.
- [ ] Model pricing is configurable without code changes.
- [ ] A daily cost summary is logged.
- [ ] Cost per session is calculable from Langfuse data.

---

## Key Scenarios (Gherkin)

```gherkin
Scenario: Structured log includes required context fields
  Given the application is running with TTA_LOG_LEVEL=INFO
  When a player turn is processed for session "sess_abc"
  Then every log line for that turn is valid JSON
  And every log line includes "session_id", "turn_id", and "trace_id" fields
  And no log line contains raw player input text

Scenario: Langfuse unavailability does not break gameplay
  Given the application is configured with Langfuse keys
  And Langfuse is unreachable (connection refused)
  When a player submits a turn
  Then the turn is processed and a narrative response is returned via SSE
  And a warning is logged indicating Langfuse export failed
  And no error is returned to the player

Scenario: Turn trace contains pipeline stage spans
  Given the application is running with tracing enabled
  When a player turn is processed through all four pipeline stages
  Then a trace is created with a root HTTP span
  And child spans exist for "input_understanding", "context_assembly", "generation", and "delivery"
  And each LLM span includes "llm.model" and "llm.tokens.prompt" attributes
  And the HTTP response includes an "X-Trace-Id" header

Scenario: Sensitive data excluded from logs and traces
  Given a player submits input containing personal disclosures
  When the turn is processed
  Then no application log line contains the player's input text
  And no trace span attribute contains the player's input text
  And the full prompt and completion appear only in Langfuse
```

---

## Appendix A: Recommended OSS Stack

| Component | Tool | Purpose |
|-----------|------|---------|
| Structured logging | `structlog` | JSON logging for Python |
| Metrics | Prometheus + `prometheus_client` | Metrics collection and exposition |
| Tracing | OpenTelemetry + Jaeger | Distributed tracing |
| LLM observability | Langfuse (self-hosted or cloud) | Prompt/completion tracking |
| Dashboards | Grafana | Visualization (optional for v1) |
| Log viewing | `docker compose logs` or Loki | Log aggregation (Loki optional for v1) |

## Appendix B: OpenTelemetry Configuration

> **Note**: The Jaeger thrift exporter (`opentelemetry-exporter-jaeger`) is deprecated upstream. Modern OpenTelemetry uses the OTLP exporter, and Jaeger 1.35+ natively accepts OTLP. The example below uses the OTLP exporter for forward-compatibility.

```python
# Minimal OTel setup (OTLP exporter — works with Jaeger, Tempo, etc.)
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
processor = BatchSpanProcessor(OTLPSpanExporter(
    endpoint=os.getenv("TTA_OBS_OTEL_ENDPOINT", "http://localhost:4317"),
))
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
```

## Changelog

- 2026-04-09: Replaced deprecated IPA/WBA/NGA agent names with pipeline stage names
  (input_understanding, context_assembly, generation, delivery) in trace span diagram,
  FR-15.18 (Langfuse definition), and AC-15.01 acceptance criteria.
