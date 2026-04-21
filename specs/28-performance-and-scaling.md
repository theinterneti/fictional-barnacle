# S28 — Performance & Scaling

> **Status**: 📝 Draft
> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ⚠️ Partial
> **Level**: 4 — Operations
> **Dependencies**: S07 (LLM Integration), S10 (API), S12 (Persistence), S14 (Deployment)
> **Last Updated**: 2026-04-09

---

## How to Read This Spec

This is a **functional specification** — it describes *what* the system does, not *how*
it's built. It is one half of a testable contract:

- **This spec** (the "what") defines behavior, acceptance criteria, and boundaries
- **The technical plan** (the "how") will define architecture, stack, and implementation
- **Tasks** will decompose both into small, reviewable chunks of work

Acceptance criteria use **Gherkin syntax** (Given/When/Then) so they can be directly
executed as automated BDD tests using frameworks like Behave or pytest-bdd.

---

## 1. Purpose

This spec defines the performance requirements and scaling strategy for TTA. It
establishes measurable latency budgets, throughput targets, and resource management
policies that ensure the system delivers a responsive experience under expected load.

TTA is a narrative game with AI at its core. The dominant latency contributor is LLM
inference — typically 1-5 seconds per turn. Performance optimization focuses on keeping
everything *except* the LLM under tight budgets so that total turn time stays below
the player's patience threshold (~10 seconds).

### Design values applied

| Value | Implication |
|---|---|
| **Fun** | Players feel the game responds quickly. Loading, saving, and navigating are near-instant. The only perceived "wait" is narrative generation, which is masked by streaming. |
| **Craftsmanship** | Performance targets are explicit, measured, and enforced by automated benchmarks. No guessing. |
| **Coherence** | The system degrades gracefully under load. Players experience slower responses, not errors or data loss. |
| **Transparency** | Performance metrics are exposed, tracked, and alertable. Operators know when targets are at risk. |

---

## 2. User Stories

### US-28.1 — Player expects fast responses
> As a **player**, I want game interactions (starting, resuming, navigating, submitting
> turns) to feel responsive, so that the experience doesn't feel sluggish or broken.

### US-28.2 — Operator monitors performance
> As an **operator**, I want clear performance metrics with defined targets and alerts,
> so that I can identify and address degradation before players notice.

### US-28.3 — System handles concurrent players
> As the **platform**, the system must serve multiple concurrent players without
> individual player performance degrading below acceptable thresholds.

### US-28.4 — System degrades gracefully under overload
> As the **platform**, when load exceeds capacity, the system must degrade gracefully
> (slower responses, queuing) rather than failing catastrophically (errors, data loss).

---

## 3. Functional Requirements

### 3.1 — Latency Budgets

**FR-28.01**: The system SHALL meet the following latency targets at p95 under normal
load (defined as ≤ 80% of capacity):

| Operation | p95 Target | Budget breakdown |
|-----------|-----------|-----------------|
| `POST /games` (create) | 8 seconds | LLM genesis: ≤6s, persistence: ≤1s, overhead: ≤1s |
| `GET /games` (list) | 200ms | DB query: ≤150ms, serialization: ≤50ms |
| `GET /games/{id}` (resume) | 3 seconds | DB query: ≤200ms, context summary LLM: ≤2.5s, serialization: ≤300ms |
| `GET /games/{id}` (resume, cached summary) | 500ms | DB query: ≤300ms, serialization: ≤200ms |
| `POST /turns` (submit, acceptance) | 200ms | Validation: ≤50ms, queue/start: ≤150ms |
| Turn processing (total) | 10 seconds | Understand: ≤500ms, Enrich: ≤1s, Generate (LLM): ≤7s, Persist: ≤1s, Overhead: ≤500ms |
| First SSE token | 2 seconds | From turn submission to first narrative_token event |
| `DELETE /games/{id}` | 500ms | Soft delete: ≤200ms, cleanup: ≤300ms |
| Health check (`/api/v1/health`) | 100ms | Subsystem checks: ≤80ms, aggregation: ≤20ms |

**FR-28.02**: When a turn's LLM generation exceeds 7 seconds (p95 target), the system
SHALL NOT add additional latency beyond the specified non-LLM budgets. The LLM is the
expected bottleneck; everything else must stay fast.

**FR-28.03**: The `POST /turns` endpoint SHALL return the 202 Accepted response within
200ms. Turn processing happens asynchronously. The player is NOT waiting for the full
turn to complete before receiving acknowledgment.

### 3.2 — Throughput Targets

**FR-28.04**: The system SHALL support the following concurrent load targets on a
single deployment instance:

| Metric | Target |
|--------|--------|
| Concurrent active players | 100 |
| Concurrent in-flight turns | 20 |
| Concurrent SSE connections | 200 |
| Requests per second (all endpoints) | 500 |

**FR-28.05**: Under normal load (≤80% of capacity targets), all latency budgets
(FR-28.01) SHALL be met.

**FR-28.06**: Under peak load (80-100% of capacity targets), latency budgets MAY be
exceeded by up to 2x, but no requests SHALL fail due to resource exhaustion. Rate
limiting (per S25) handles requests beyond capacity.

### 3.3 — Connection Pool Management

**FR-28.07**: PostgreSQL connection pooling SHALL be configured with:
- Minimum pool size: configurable (default: 5)
- Maximum pool size: configurable (default: 20)
- Connection timeout: 5 seconds (fail fast if pool exhausted)
- Idle connection timeout: 300 seconds (release unused connections)

**FR-28.08**: Redis connection pooling SHALL be configured with:
- Maximum connections: configurable (default: 20)
- Connection timeout: 2 seconds
- Retry on connection loss: 3 attempts with exponential backoff

**FR-28.09**: Neo4j connection pooling SHALL be configured with:
- Maximum connections: configurable (default: 10)
- Connection timeout: 5 seconds
- Connection liveness check interval: 60 seconds

**FR-28.10**: All connection pool metrics (active, idle, waiting, timeouts) SHALL be
exposed as Prometheus metrics (per S15).

### 3.4 — LLM Request Management

**FR-28.11**: LLM requests (via LiteLLM, per S07) SHALL be bounded by a concurrency
semaphore: configurable maximum concurrent LLM requests (default: 10).

**FR-28.12**: When the LLM concurrency limit is reached, additional turn requests SHALL
be queued (not rejected). Queue depth SHALL be bounded (configurable, default: 50).
Requests exceeding queue capacity SHALL return 503 Service Unavailable per S23.

**FR-28.13**: LLM request timeout SHALL be configurable (default: 30 seconds). Requests
exceeding the timeout SHALL be cancelled and the turn marked as failed per S23.

**FR-28.14**: LLM token usage per turn SHALL be bounded:
- Input context window: configurable maximum (default: 4,000 tokens)
- Output generation: configurable maximum (default: 2,000 tokens)
- Total per turn: SHALL NOT exceed the model's context window

### 3.5 — Memory and Resource Management

**FR-28.15**: The application process SHALL NOT exceed a configurable memory limit
(default: 512 MB RSS). If memory usage exceeds 90% of the limit, the system SHALL:
1. Log a warning with current memory breakdown
2. Stop accepting new game creation requests (existing games continue)
3. Trigger garbage collection

**FR-28.16**: SSE connections SHALL have a maximum lifetime (configurable, default:
30 minutes). Connections exceeding the lifetime are gracefully closed with a
`stream_end` event. Clients may reconnect.

**FR-28.17**: Turn history loaded into memory for LLM context SHALL be bounded to the
most recent N turns (configurable, default: 20). Older turns are summarized, not
loaded verbatim.

### 3.6 — Graceful Degradation

**FR-28.18**: When the system is under heavy load (>80% capacity), it SHALL degrade
gracefully according to this priority order:
1. **Protect**: Active games (in-flight turns complete, SSE streams continue)
2. **Slow**: New game creation (queued, not rejected)
3. **Defer**: Context summary regeneration (return cached summary)
4. **Defer**: Game title/summary updates (skip, use previous)
5. **Reject last**: Health check responses (always fast)

**FR-28.19**: Graceful degradation decisions SHALL be logged at INFO level with the
degradation tier and reason.

### 3.7 — Horizontal Scaling Readiness

**FR-28.20**: The application SHALL be stateless at the process level. All state is
stored in external systems (PostgreSQL, Redis, Neo4j). This enables horizontal scaling
by running multiple instances behind a load balancer.

**FR-28.21**: SSE stream state SHALL be stored in Redis (per S12), not in process
memory. This ensures that if a process restarts, clients can reconnect to any instance
and resume streaming.

**FR-28.22**: The following features SHALL work correctly across multiple instances:
- Rate limiting (Redis-backed counters are shared, per S25)
- Turn result delivery (Redis pub/sub, per existing TurnResultStore)
- Session tokens (stateless JWT verification, per S11)
- Health checks (each instance reports its own health)

**FR-28.23**: Database migrations (Alembic, per S12) SHALL use a distributed lock
to prevent concurrent migration execution across instances.

---

## 4. Non-Functional Requirements

### NFR-28.1 — Performance Regression Detection
**Category**: Quality
**Target**: A performance benchmark suite SHALL exist that runs as part of CI/CD (or
on a schedule) and detects latency regressions >20% from baseline.

### NFR-28.2 — Startup Time
**Category**: Performance
**Target**: Application cold start (from process launch to accepting requests) SHALL
complete within 10 seconds, including database connection establishment and migration
check.

### NFR-28.3 — Shutdown Graceful Period
**Category**: Reliability
**Target**: On SIGTERM, the application SHALL complete in-flight requests and close
SSE connections within 30 seconds before exiting. No data loss during graceful
shutdown.

### NFR-28.4 — Resource Efficiency
**Category**: Operations
**Target**: Under idle conditions (no active players), the application SHALL consume
<100 MB RSS and <5% CPU on a 2-core instance.

---

## 5. User Journeys

### Journey 1: Normal gameplay experience

- **Trigger**: Player submits a turn during normal load.
- **Steps**:
  1. Player sends `POST /turns`. Response: 202 Accepted within 200ms.
  2. Player opens SSE stream. First token arrives within 2 seconds.
  3. Full narrative streams over 3-5 seconds.
  4. Game state persisted within 1 second of generation completing.
  5. Player's game listing reflects updated last_played_at immediately.
- **Outcome**: Responsive, fluid experience. Player perceives ~5 second turn time.

### Journey 2: System under heavy load

- **Trigger**: 80 concurrent players, 15 in-flight turns.
- **Steps**:
  1. Player submits a turn. `POST /turns` still returns within 200ms.
  2. Turn is queued behind other in-flight turns (LLM semaphore).
  3. First token arrives within 4 seconds (slower than normal, but within 2x budget).
  4. Full narrative completes in ~8 seconds.
  5. Context summary regeneration for a resuming player is skipped — cached version used.
- **Outcome**: Slightly slower but functional. No errors. Graceful degradation visible.

### Journey 3: Operator responds to latency alert

- **Trigger**: Monitoring detects p95 turn time exceeding 12 seconds.
- **Steps**:
  1. Alert fires via S15 observability pipeline.
  2. Operator checks `/admin/health` — LLM provider showing elevated latency.
  3. Operator checks Prometheus metrics — LLM p95 at 9s (normally 4s).
  4. Root cause: upstream LLM provider degradation.
  5. Operator adjusts LLM timeout and considers switching to fallback model.
- **Outcome**: Issue identified within minutes. Operator has actionable data.

---

## 6. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| EC-28.1 | PostgreSQL connection pool exhausted | New requests wait up to 5 seconds for a connection. If still unavailable, return 503 per S23. |
| EC-28.2 | Redis connection lost | Fall back to in-memory rate limiting (per S25). Log warning. Health status: degraded. |
| EC-28.3 | LLM queue full (50 pending requests) | New turn submissions return 503 with `retry_after_seconds`. |
| EC-28.4 | Memory usage exceeds 90% of limit | New game creation paused. Existing games continue. Warning logged with memory breakdown. |
| EC-28.5 | SSE connection reaches 30-minute lifetime | Graceful close with `stream_end` event. Client should reconnect. |
| EC-28.6 | LLM request times out at 30 seconds | Turn marked as failed. Player receives error via SSE. Retry is manual (player resubmits). |
| EC-28.7 | Multiple instances run Alembic simultaneously | Distributed lock ensures only one runs migrations. Others wait or skip. |
| EC-28.8 | Cold start during high traffic | Requests received before startup completes return 503. Health check returns unhealthy until ready. Kubernetes readiness probe prevents traffic routing. |

---

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: Performance & Scaling

  Scenario: AC-28.1 — Turn submission responds within budget
    Given the system is under normal load
    When a player submits a turn via POST /turns
    Then the response is received within 200ms
    And the response status is 202

  Scenario: AC-28.2 — First SSE token within budget
    Given the system is under normal load
    When a player submits a turn and opens the SSE stream
    Then the first narrative_token event arrives within 2 seconds

  Scenario: AC-28.3 — Game listing responds within budget
    Given a player with 10 games
    When the player sends GET /games
    Then the response is received within 200ms

  Scenario: AC-28.4 — Connection pool metrics exposed
    Given the application is running
    When the /metrics endpoint is queried
    Then Prometheus metrics include pool_active, pool_idle, and pool_waiting for each database

  Scenario: AC-28.5 — LLM concurrency bounded
    Given 10 LLM requests are already in flight
    When an 11th turn is submitted
    Then the turn is queued (not rejected)
    And the queue depth metric is incremented

  Scenario: AC-28.6 — Graceful degradation under load
    Given the system is at 90% capacity
    When a player resumes a game
    Then the cached context_summary is returned (not regenerated)
    And the response latency is within 2x of the normal budget

  Scenario: AC-28.7 — Graceful shutdown
    Given the application receives SIGTERM
    And there are in-flight requests and active SSE connections
    Then all in-flight requests complete
    And all SSE connections receive a stream_end event
    And the process exits within 30 seconds

  Scenario: AC-28.8 — Horizontal scaling readiness
    Given two application instances are running behind a load balancer
    When a player submits a turn on instance A
    And opens the SSE stream on instance B
    Then the SSE stream delivers the turn's narrative tokens
```

### Criteria Checklist
- [ ] **AC-28.1**: Turn submission latency budget
- [ ] **AC-28.2**: First SSE token latency budget
- [ ] **AC-28.3**: Game listing latency budget
- [ ] **AC-28.4**: Connection pool metrics
- [ ] **AC-28.5**: LLM concurrency control
- [ ] **AC-28.6**: Graceful degradation behavior
- [ ] **AC-28.7**: Graceful shutdown behavior
- [ ] **AC-28.8**: Multi-instance correctness

---

## 8. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|------|-------------|----------|
| S07 (LLM Integration) | Constrains | S28 defines LLM concurrency limits and timeout budgets. S07 defines the LLM client interface. |
| S08 (Turn Pipeline) | Constrains | S28 defines the total turn processing time budget. S08 defines the pipeline stages that consume that budget. |
| S10 (API & Streaming) | Constrains | S28 defines endpoint-level latency budgets. S10 defines the endpoint contracts. |
| S12 (Persistence) | Cooperates | S28 defines connection pool parameters and persistence latency budgets. S12 defines the storage layer. |
| S14 (Deployment) | Cooperates | S28's horizontal scaling requirements inform S14's container orchestration and load balancer configuration. |
| S15 (Observability) | Requires | S28 depends on S15's metrics pipeline for latency tracking, alerting, and performance regression detection. |
| S23 (Error Handling) | Cooperates | S28's degradation modes use S23's error responses. Resource exhaustion maps to S23's `service_unavailable` error category. |
| S25 (Rate Limiting) | Cooperates | S28's throughput targets define the ceiling. S25's rate limits prevent exceeding it. |
| S27 (Save/Load) | Constrains | S28 defines latency budgets for S27's game creation, listing, and resume operations. |

---

## 9. Open Questions

| # | Question | Impact | Resolution needed by |
|---|----------|--------|---------------------|
| Q-28.1 | Should we use a task queue (e.g., Celery, arq) for turn processing, or keep it in-process with asyncio? | In-process is simpler and sufficient for v1 targets. Task queue adds complexity but enables better horizontal scaling. | Before implementation |
| Q-28.2 | What is the target deployment instance size (CPU, memory)? | Affects throughput targets. Current targets assume 2-core, 2 GB instance. | Before implementation |
| Q-28.3 | Should performance benchmarks run in CI on every PR, or on a schedule? | PR-level: catches regressions early but slower CI. Scheduled: less frequent but lower overhead. | Before implementation |

---

## 10. Out of Scope

- **Auto-scaling policies** — v1 defines horizontal scaling readiness (stateless
  processes). Actual auto-scaling policies (based on CPU, memory, or custom metrics)
  are an operational concern for S14, not specified here. — Handled by S14.
- **CDN / edge caching** — TTA content is dynamic and personalized. CDN caching does
  not apply to core game endpoints. Static assets (if any) can use standard CDN
  practices. — N/A for v1.
- **Database query optimization** — Specific index strategies and query plans are
  implementation details for the technical plan, not this spec. This spec defines the
  latency budgets the queries must meet. — Covered in plans.
- **LLM model selection / cost optimization** — S07 defines model selection. S28
  defines the performance budget the selected model must fit within. — Covered by S07.
- **Multi-region deployment** — v1 targets a single-region deployment. Multi-region
  with data replication is deferred. — Recommended for v2.

---

## Appendix

### A. Latency Budget Diagram

```
Player submits turn:
  ├─ POST /turns ──────────────────────── ≤200ms (202 Accepted)
  │
  └─ Background processing:
      ├─ Understand stage ─────────────── ≤500ms
      ├─ Enrich stage ─────────────────── ≤1,000ms
      ├─ Generate stage (LLM) ─────────── ≤7,000ms  ← dominant cost
      │   ├─ First token ──────────────── ≤2,000ms from submission
      │   └─ Full generation ──────────── ≤7,000ms
      ├─ Persist stage ────────────────── ≤1,000ms
      └─ Overhead (routing, etc.) ─────── ≤500ms
                                           ─────────
                                     Total: ≤10,000ms
```

### B. Glossary

| Term | Definition |
|---|---|
| **p95** | 95th percentile — 95% of requests complete within this time. Used as the standard latency target. |
| **Connection pool** | A cache of reusable database connections that avoids the overhead of establishing new connections per request. |
| **Concurrency semaphore** | A synchronization primitive that limits the number of concurrent operations (e.g., LLM requests). |
| **Graceful degradation** | The system's ability to maintain partial functionality under overload rather than failing completely. |
| **Cold start** | The time from process launch to the application being ready to serve requests. |
| **RSS** | Resident Set Size — the amount of physical memory used by the process. |
| **Horizontal scaling** | Adding more instances of the application (vs. vertical scaling: adding more resources to a single instance). |

---

## v1 Closeout (Non-normative)

> This section is retrospective and non-normative. It documents what shipped in the v1
> baseline, what was verified, what gaps were found, and what is deferred to v2.

### What Shipped

- **Turn latency budget** — AC-28.1 P95 < 30 s enforced via `test_s28_performance.py`
- **LLM concurrency semaphore** — `src/tta/llm/semaphore.py`; limits parallel LLM calls
  to `settings.max_concurrent_llm_calls` (AC-28.5)
- **Connection pool config** — PostgreSQL and Redis pool sizes set in `settings` and
  tested in `test_s28_performance.py`
- **Graceful degradation under load** — `test_s28_performance.py` verifies server stays
  responsive when semaphore is at capacity
- **Pool metrics** — `tests/unit/observability/test_pool_metrics.py` covers AC-28.4

### Evidence

- `tests/unit/performance/test_s28_performance.py` — 6 test classes:
  `TestS28LatencyBudgets`, `TestS28Semaphore`, `TestS28PoolConfig`,
  `TestS28GracefulDegradation`, `TestS28Shutdown`, `TestS28MemoryBounds`
- `tests/unit/observability/test_pool_metrics.py` — AC-28.4

### Gaps Found in v1

1. **No live load test** — all performance tests run against in-process mocks; no JMeter
   / k6 load test against a real server with PostgreSQL + Redis + Neo4j
2. **Multi-instance throughput untested** (AC-28.8 deferred) — horizontal scaling
   behaviour is unknown
3. **Memory bounds are soft** — `TestS28MemoryBounds` asserts no obvious leak in unit
   tests; no long-running soak test exists

### Deferred to v2

| Feature | Reason |
|---------|--------|
| Live load test (k6/JMeter) | Requires live infra environment |
| Multi-instance throughput (AC-28.8) | Requires container orchestration |
| Soak test for memory leaks | Requires long-running test environment |

### Lessons for v2

- The semaphore is the most important performance control we have; never remove it or
  make it optional
- Pool sizing is declarative and easy to tune; document recommended production values in
  the ops runbook
- P95 latency budget (30 s) is generous for v1; v2 should target P95 < 15 s with live
  infrastructure measurements
