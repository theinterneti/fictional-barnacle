# S23 — Error Handling & Resilience

> **Status**: 📝 Draft
> **Level**: 3 — Platform
> **Dependencies**: S07 (LLM Integration), S08 (Turn Pipeline), S10 (API & Streaming), S12 (Persistence Strategy)
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

This spec defines how TTA handles errors across every layer — from database failures to
LLM timeouts to malformed player input. It is a **cross-cutting concern** that touches
the API surface, the turn pipeline, persistence, and LLM integration.

Today, error handling is scattered across individual specs (S07 defines LLM fallback, S10
defines HTTP error shapes, S08 handles pipeline failures). This spec consolidates those
fragments into a single, coherent error taxonomy, defines the player-facing error
experience, and establishes system-wide resilience contracts.

The guiding principle is **graceful degradation**: the game should always present a
playable response. A player should never see a raw stack trace, a connection refused
message, or an opaque 500 error. When things break, the system tells the player what
happened in narrative terms and either recovers automatically or guides them to a safe
state.

### Design values applied

| Value | Implication |
|---|---|
| **Fun** | Errors must never shatter immersion. Player-facing messages stay in-character when possible. |
| **Coherence** | Partial failures must not corrupt game state. Either a turn completes fully or rolls back. |
| **Craftsmanship** | Error handling is a first-class design concern, not bolted on after the fact. |
| **Transparency** | Operators see the real error; players see a helpful message. Never the reverse. |

---

## 2. User Stories

### US-23.1 — Player sees a helpful message on failure
> As a **player**, I want to see a clear, friendly message when something goes wrong —
> never a stack trace, HTTP status code, or technical jargon — so that I can understand
> what happened and what to do next.

### US-23.2 — Player's game state is never corrupted
> As a **player**, I want my game to remain in a consistent state even when the server
> encounters an error mid-turn, so that I never lose progress or end up in an impossible
> game state.

### US-23.3 — Operator diagnoses failures quickly
> As an **operator**, I want structured error logs with correlation IDs, error categories,
> and full context (request, session, turn), so that I can diagnose and resolve production
> issues in minutes, not hours.

### US-23.4 — Developer writes consistent error handling
> As a **developer**, I want a well-defined error taxonomy and standard error-raising
> patterns, so that every module handles errors consistently and I don't have to invent
> error shapes per feature.

### US-23.5 — System recovers from transient failures
> As an **operator**, I want the system to automatically retry transient failures (database
> reconnects, LLM provider blips, Redis timeouts) with backoff, so that brief
> infrastructure hiccups don't become player-facing outages.

### US-23.6 — Player can retry after a failure
> As a **player**, I want the option to retry my last action when a recoverable error
> occurs, so that I don't have to retype my input or wonder if it was lost.

---

## 3. Functional Requirements

### 3.1 — Error Taxonomy

TTA classifies every error into one of the following categories. Each category has
defined behavior for the player, the operator, and the system.

**FR-23.01**: The system SHALL classify all errors into exactly one of these categories:

| Category | HTTP Status | Player sees | System behavior | Example |
|---|---|---|---|---|
| `input_invalid` | 400 | Specific validation message | Log at WARN, no retry | Missing turn text, invalid game ID format |
| `schema_invalid` | 422 | Specific validation message | Log at WARN, no retry | Pydantic schema/type violations on request body |
| `auth_required` | 401 | Prompt to register or log in | Log at INFO | Expired session, missing token |
| `forbidden` | 403 | "You don't have access to this" | Log at WARN | Player accessing another's game |
| `not_found` | 404 | "Game not found" / "Page not found" | Log at INFO | Deleted game, bad URL |
| `conflict` | 409 | "Action already in progress" | Log at WARN, no retry | Duplicate turn submission |
| `rate_limited` | 429 | "Too many requests, try again in Xs" | Log at INFO, include Retry-After | See S25 |
| `llm_failure` | 502 | "The story needs a moment…" | Retry per S07 tiers, log at ERROR | All LLM tiers exhausted |
| `service_unavailable` | 503 | "Server is busy, please wait" | Log at ERROR, circuit-break | Database down, Redis down |
| `internal_error` | 500 | "Something went wrong" | Log at ERROR with full context | Unhandled exception, bug |

**FR-23.02**: Every error response SHALL conform to a standard JSON envelope:

```json
{
  "error": {
    "code": "llm_failure",
    "message": "The story needs a moment to gather its thoughts. Please try again.",
    "retry_after_seconds": 5,
    "correlation_id": "req-abc123",
    "details": {}
  }
}
```

**FR-23.03**: The `correlation_id` field SHALL be present on every error response. It
SHALL match the request correlation ID from the `X-Request-ID` header (if provided by
the client) or be generated server-side. The same ID SHALL appear in the corresponding
log entry.

**FR-23.04**: The `details` field SHALL be empty for player-facing responses in
production. In development mode (`TTA_DEBUG=true`), it MAY include stack trace and
request context for developer convenience.

**FR-23.05**: The `message` field SHALL be a human-readable string suitable for direct
display to the player. It SHALL NOT contain technical details, module names, or
exception class names.

### 3.2 — Error Logging

**FR-23.06**: Every error SHALL be logged as a structured JSON event with at minimum:
- `level` (ERROR, WARN, INFO)
- `error_code` (from taxonomy)
- `correlation_id`
- `player_id` (if authenticated, "anonymous" otherwise)
- `game_id` (if in game context)
- `turn_id` (if in turn context)
- `timestamp` (ISO 8601)
- `module` (source module, e.g. `tta.pipeline.generate`)

**FR-23.07**: Error logs at ERROR level SHALL additionally include:
- `exception_type` (Python exception class name)
- `exception_message` (raw exception string)
- `stack_trace` (full traceback)
- `request_method` and `request_path`

**FR-23.08**: The system SHALL NOT log player input text, turn content, or PII in error
logs. Error context SHALL reference IDs (player_id, game_id, turn_id), not data values.
This aligns with S15 (Observability) and S17 (Data Privacy).

### 3.3 — Transient Failure Recovery

**FR-23.09**: The system SHALL automatically retry the following transient failures with
exponential backoff and jitter:

| Failure type | Max retries | Initial backoff | Max backoff |
|---|---|---|---|
| Database connection lost | 3 | 0.5s | 4s |
| Database query timeout | 2 | 1s | 4s |
| Redis connection lost | 3 | 0.5s | 2s |
| Redis timeout | 2 | 0.5s | 2s |
| LLM provider 429 (rate limit) | Per S07 tier rules | Per S07 | Per S07 |
| LLM provider 5xx | Per S07 tier rules | Per S07 | Per S07 |
| Neo4j connection lost | 3 | 0.5s | 4s |

**FR-23.10**: Retry logic SHALL be implemented via a shared retry utility — not
duplicated per module. The utility SHALL accept configurable retry count, backoff
strategy, and exception filter.

> **Implementation note (non-normative):** tenacity's `@retry` decorator satisfies this
> requirement. The spec does not mandate tenacity; any library with equivalent retry,
> backoff, and circuit-breaking capabilities is acceptable.

**FR-23.11**: After all retries are exhausted, the system SHALL raise the appropriate
error category from §3.1 (typically `service_unavailable` for infrastructure failures
or `llm_failure` for LLM failures).

### 3.4 — Circuit Breaking

**FR-23.12**: The system SHALL implement circuit-breaking for external service calls
(LLM providers, Neo4j, Redis). When a service accumulates N failures within M seconds,
subsequent calls SHALL immediately fail-fast for a cooldown period rather than
attempting the call.

**FR-23.13**: Circuit breaker state transitions SHALL be:
- **Closed** (normal): all calls pass through
- **Open** (tripped): all calls immediately fail-fast with `service_unavailable`
- **Half-open** (probing): after cooldown, one call is allowed through. If it succeeds,
  the circuit closes. If it fails, the circuit re-opens.

**FR-23.14**: Circuit breaker configuration SHALL be per-service:
- LLM provider: N=5, M=60s, cooldown=30s (aligns with S07 FR-07.11)
- PostgreSQL: N=3, M=30s, cooldown=15s
- Neo4j: N=3, M=30s, cooldown=15s
- Redis: N=5, M=30s, cooldown=10s

**FR-23.15**: Circuit breaker state changes (open, close, half-open) SHALL be logged at
WARN level and exposed as metrics for operator alerting.

### 3.5 — Turn Atomicity

**FR-23.16**: Turn processing SHALL be atomic with respect to game state. Either:
1. The entire turn completes (player input recorded, pipeline stages run, narrative
   generated, state updated) and all changes are persisted, OR
2. The turn fails and no partial state changes are visible to the player. The game
   reverts to the state before the turn was submitted.

**FR-23.17**: If an error occurs during turn processing AFTER the player input has been
recorded but BEFORE narrative generation completes, the system SHALL:
1. Mark the turn as `failed` in persistence (not `completed`)
2. Log the failure with full context
3. Return an error to the player with `retry_after_seconds` and a message indicating
   they can re-submit
4. NOT advance the turn counter

**FR-23.18**: If an error occurs during SSE streaming AFTER narrative generation has
begun, the system SHALL:
1. Send an SSE `error` event to the client with the error envelope from FR-23.02
2. Close the SSE connection cleanly
3. Persist whatever narrative was generated up to the failure point as a partial turn
4. Allow the player to re-submit, which replays from the partial state

**FR-23.19**: Concurrent turn submissions for the same game SHALL be rejected with
`conflict` (409). Only one turn may be in-flight per game at any time.

### 3.6 — SSE Error Events

**FR-23.20**: The SSE stream SHALL support an `error` event type that carries the
standard error envelope (FR-23.02). Clients MUST handle this event type.

**FR-23.21**: If the server cannot send an SSE error event (client already disconnected),
the error SHALL still be logged and the turn state updated per FR-23.17/FR-23.18.

**FR-23.22**: SSE keep-alive comments SHALL continue during long-running operations
(per S10 FR-10.32) to distinguish "server is still working" from "server has crashed."
If no keep-alive arrives within 30 seconds, the client SHOULD assume a failure and
reconnect.

### 3.7 — Health and Readiness

**FR-23.23**: The system SHALL expose a `/api/v1/health` endpoint that returns:
- `status`: "healthy", "degraded", or "unhealthy"
- `checks`: object with per-service health (postgres, redis, neo4j, llm)
- `version`: application version string

**FR-23.24**: "Degraded" status SHALL be returned when any non-critical service (Redis,
Neo4j) is unavailable but the core game loop can still function (with reduced features).
"Unhealthy" SHALL be returned only when PostgreSQL is unreachable.

**FR-23.25**: The system SHALL expose a `/api/v1/health/ready` endpoint that returns
200 only when all required services are connected and the application is ready to accept
player requests. Orchestrators SHALL use this for traffic routing.

---

## 4. Non-Functional Requirements

### NFR-23.1 — Error Response Latency
**Category**: Performance
**Target**: Error responses SHALL be returned within 200ms (p95) of error detection. No
error path should involve additional network calls beyond logging.

### NFR-23.2 — Retry Overhead
**Category**: Performance
**Target**: Retry-with-backoff SHALL NOT block the request handler's thread/event loop.
Retries for infrastructure calls use async I/O. Player-facing timeout for the entire
turn processing (including retries) SHALL NOT exceed 60 seconds.

### NFR-23.3 — Error Rate Threshold
**Category**: Reliability
**Target**: The system SHALL maintain <1% error rate (5xx responses / total responses)
under normal operating conditions. Error rate exceeding 5% for 5 consecutive minutes
SHALL trigger operator alerts.

### NFR-23.4 — Log Volume
**Category**: Scalability
**Target**: Error logging SHALL NOT exceed 1KB per error event (structured JSON). At peak
load (100 concurrent sessions), error logging overhead SHALL NOT measurably impact
request latency.

### NFR-23.5 — Zero Information Leak
**Category**: Security
**Target**: No error response SHALL expose internal module paths, database table names,
SQL queries, or stack traces in production mode. Only `correlation_id` connects the
player-visible error to the operator-visible details.

---

## 5. User Journeys

### Journey 1: Player encounters a temporary LLM failure

- **Trigger**: Player submits a turn, but the primary LLM provider is experiencing a brief outage.
- **Steps**:
  1. Player types "I open the ancient chest" and submits.
  2. POST /turns is accepted (202). SSE stream opens.
  3. Primary LLM call fails (timeout after 10s).
  4. System automatically retries on fallback model (per S07).
  5. Fallback succeeds. Narrative streams to player via SSE.
  6. Player sees normal narrative — never aware of the retry.
- **Happy path**: Fallback succeeds, transparent to player.
- **Alternative path**: All tiers fail. Player sees "The story needs a moment to gather
  its thoughts. Please try again." with a retry button.

### Journey 2: Database goes down mid-session

- **Trigger**: PostgreSQL becomes unreachable while a player is in an active game.
- **Steps**:
  1. Player submits a turn.
  2. System attempts to record turn input — PostgreSQL connection fails.
  3. Retry with backoff (3 attempts over ~6s).
  4. All retries fail. Circuit breaker opens.
  5. Player receives: "The server is temporarily unavailable. Your game is safe — please
     try again in a moment." (503 with `retry_after_seconds: 30`).
  6. Subsequent requests fail-fast (circuit is open) until PostgreSQL recovers.
  7. PostgreSQL recovers. Half-open probe succeeds. Circuit closes.
  8. Player retries — turn processes normally.
- **Happy path**: Database recovers quickly, circuit closes, player resumes.
- **Alternative path**: Extended outage. `/api/v1/health` reports "unhealthy."
  Operator is alerted.

### Journey 3: Player submits malformed input

- **Trigger**: Player submits a turn with empty text or invalid characters.
- **Steps**:
  1. Player submits an empty string as turn input.
  2. Request validation fails (Pydantic model).
  3. System returns 400 with: "Please enter what you'd like to do."
  4. Player sees the validation message and resubmits with valid input.
- **Happy path**: Clear message, quick recovery.

### Journey 4: Developer debugging a production error

- **Trigger**: A player reports "something went wrong."
- **Steps**:
  1. Player provides the correlation ID shown in the error message.
  2. Developer searches structured logs by correlation_id.
  3. Finds the full error context: exception type, stack trace, request path, game ID, turn ID.
  4. Traces the error to a specific module and line.
  5. Fixes the bug, deploys, verifies.

---

## 6. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| EC-23.1 | Error occurs during error handling (logging fails) | System uses fallback stderr logging. Player still sees standard error response. |
| EC-23.2 | Client disconnects before error response is sent | Error is logged. Turn state is updated. No player notification possible — client reconnect will show current state. |
| EC-23.3 | Multiple services fail simultaneously | Circuit breakers open independently. `/api/v1/health` reports each service's status. Player sees most relevant error (database > LLM > Redis). |
| EC-23.4 | Error response body exceeds reasonable size | Error responses are capped at the standard envelope (FR-23.02). No unbounded data in error responses. |
| EC-23.5 | Retry succeeds but response is too slow | Player-facing timeout (60s per NFR-23.2) applies to the entire operation including retries. After 60s, return `service_unavailable`. |
| EC-23.6 | Circuit breaker flaps (service repeatedly fails and recovers) | Exponential cooldown: each consecutive open→close→open cycle doubles the cooldown period, up to a maximum of 5 minutes. |
| EC-23.7 | Error occurs in a background task (not request-scoped) | Errors in background tasks (e.g., cleanup jobs) are logged but do not produce HTTP error responses. They use the same structured log format. |
| EC-23.8 | Player submits a turn while a previous turn is still processing | Return 409 `conflict` per FR-23.19. Client should poll or listen for the in-progress turn's completion. |
| EC-23.9 | Game state is in an inconsistent state from a previous partial failure | System detects inconsistency on next turn. Returns `internal_error` with suggestion to load a save point. Operator alert fires. |
| EC-23.10 | Error occurs inside a database transaction | Transaction is rolled back. No partial writes are committed. Aligns with FR-23.16 (turn atomicity). |

---

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: Error Handling & Resilience

  Scenario: AC-23.1 — Standard error response shape
    Given the API is running
    When a request results in any error
    Then the response body contains "error.code", "error.message", and "error.correlation_id"
    And the "error.message" does not contain stack traces or module names

  Scenario: AC-23.2 — Correlation ID in error logs
    Given a request with X-Request-ID header "test-123"
    When the request results in an error
    Then the error response contains correlation_id "test-123"
    And the structured log entry for this error contains correlation_id "test-123"

  Scenario: AC-23.3 — LLM failure graceful degradation
    Given the primary LLM model is unavailable
    And the fallback LLM model is unavailable
    And the last-resort LLM model is unavailable
    When a player submits a turn
    Then the player receives a friendly error message mentioning the story needs a moment
    And the error code is "llm_failure"
    And the HTTP status is 502
    And the turn is NOT marked as completed

  Scenario: AC-23.4 — Database retry with backoff
    Given PostgreSQL is temporarily unreachable
    When a player submits a turn
    Then the system retries the database operation up to 3 times
    And each retry uses exponential backoff with jitter
    When PostgreSQL becomes reachable during retries
    Then the turn completes normally
    And the player is unaware of the retry

  Scenario: AC-23.5 — Circuit breaker opens on repeated failures
    Given PostgreSQL has failed 3 times in the last 30 seconds
    When a new database operation is attempted
    Then the operation fails immediately without contacting PostgreSQL
    And the error response is "service_unavailable" (503)
    And the circuit breaker state is logged as "open"

  Scenario: AC-23.6 — Turn atomicity on mid-turn failure
    Given a player submits a turn
    And the turn input is recorded successfully
    When narrative generation fails after partial completion
    Then the turn is marked as "failed" in the database
    And the game state is NOT advanced
    And the player can re-submit the same turn

  Scenario: AC-23.7 — Concurrent turn rejection
    Given a turn is currently being processed for game "game-1"
    When the same player submits another turn for "game-1"
    Then the response status is 409
    And the error code is "conflict"
    And the message indicates a turn is already in progress

  # [v2 — Streaming] v1 uses buffer-then-stream: the full response is generated
  # before SSE delivery begins, so mid-stream generation errors cannot occur.
  # Mid-stream error injection requires true token-level streaming (v2).
  Scenario: AC-23.8 — SSE error event delivery
    Given a player is connected to the SSE stream
    When an error occurs during narrative streaming
    Then the SSE stream sends an "error" event with the standard error envelope
    And the SSE connection is closed cleanly

  Scenario: AC-23.9 — Health endpoint reports degraded
    Given Redis is unreachable
    And PostgreSQL is healthy
    When GET /api/v1/health is called
    Then the response contains status "degraded"
    And the "checks.redis" field indicates unhealthy
    And the "checks.postgres" field indicates healthy

  Scenario: AC-23.10 — No information leak in production
    Given the application is running in production mode
    When an unhandled exception occurs
    Then the error response contains code "internal_error"
    And the error message is generic ("Something went wrong")
    And the response does NOT contain exception type, module path, or stack trace

  Scenario: AC-23.11 — Input validation returns specific message
    Given a player submits a turn with empty text
    When the request is validated
    Then the response status is 400
    And the error code is "input_invalid"
    And the message describes what was wrong ("Turn text cannot be empty")

  Scenario: AC-23.12 — Health endpoint reports unhealthy
    Given PostgreSQL is unreachable
    When GET /api/v1/health is called
    Then the response status is 503
    And the response contains status "unhealthy"
```

### Criteria Checklist
- [ ] **AC-23.1**: All error responses use standard envelope shape
- [ ] **AC-23.2**: Correlation IDs flow from request to response to logs
- [ ] **AC-23.3**: LLM total failure produces friendly player message (502)
- [ ] **AC-23.4**: Database retries with exponential backoff
- [ ] **AC-23.5**: Circuit breaker opens after threshold failures
- [ ] **AC-23.6**: Failed turns don't corrupt game state
- [ ] **AC-23.7**: Concurrent turns for same game are rejected (409)
- [ ] **AC-23.8**: SSE stream delivers error events
- [ ] **AC-23.9**: Health endpoint reports degraded when non-critical service is down
- [ ] **AC-23.10**: No stack traces or module paths in production error responses
- [ ] **AC-23.11**: Input validation errors have specific, helpful messages
- [ ] **AC-23.12**: Health endpoint reports unhealthy when Postgres is down

---

## 8. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|------|-------------|----------|
| S07 (LLM Integration) | Extends | S07 defines LLM-specific fallback tiers. S23 wraps LLM failures in the standard error taxonomy and adds circuit-breaking. S23 does not override S07 tier behavior — it standardizes the error surface after all tiers are exhausted. |
| S08 (Turn Pipeline) | Extends | S08 defines pipeline stages. S23 defines what happens when any stage fails: turn atomicity (FR-23.16–23.18), error propagation, and player notification. |
| S10 (API & Streaming) | Extends | S10 defines HTTP routing/auth integration. S23 is canonical for error taxonomy/envelope and health semantics. S10's error/status contracts and health paths MUST map to S23 FR-23.01-03 and FR-23.23-25. |
| S12 (Persistence) | Requires | S23 requires transactional semantics for turn atomicity. S12 must support atomic writes and rollback for turn state. |
| S15 (Observability) | Cooperates | S23 defines error log structure (FR-23.06–23.08). S15 defines the logging infrastructure and dashboards. Error metrics from S23 are exposed via S15's metric pipeline. |
| S17 (Data Privacy) | Constrains | S23's error logging must NOT include PII (FR-23.08). Error context references IDs, not data values. |
| S25 (Rate Limiting) | Cooperates | S25 defines when to return `rate_limited` (429). S23 defines the error envelope shape for rate limit responses. |

---

## 9. Open Questions

| # | Question | Impact | Resolution needed by |
|---|----------|--------|---------------------|
| Q-23.1 | Should circuit breaker state be shared across multiple server instances (via Redis), or per-process? | Per-process is simpler but less coordinated. Shared gives better global behavior but adds Redis dependency to the error path. | Before horizontal scaling (S28) |
| Q-23.2 | Should the system attempt to resume a partially-streamed narrative on retry, or restart from scratch? | Resume is harder but provides better UX. Restart is simpler but wastes tokens. | Before v1 launch |
| Q-23.3 | What is the right player-facing message for each error category? Should messages be localized? | Localization adds complexity. English-only for v1 is pragmatic. | Before v1 launch |
| Q-23.4 | Should error metrics be aggregated by error category, endpoint, or both? | Determines dashboard granularity and alerting rules. | Before S15 dashboarding |

---

## 10. Out of Scope

- **Distributed tracing across microservices** — TTA is a single process (per system.md). Tracing is intra-process only. — By design.
- **Custom error pages (HTML)** — TTA's API returns JSON. Client-side rendering of errors is a client concern. — Client responsibility.
- **Error budgets and SLO management** — SRE practices are beyond v1 scope. — Deferred.
- **Automatic incident creation** — Operator alerting (S15) is sufficient for v1. PagerDuty/Opsgenie integration is deferred. — Deferred.
- **Error rate-based auto-scaling** — Scaling is handled in S28. — Handled in S28.
- **User-facing error telemetry** — Client-side error tracking (Sentry for frontend) is not in v1 scope. — Deferred.
- **LLM fallback tier design** — Tier structure and model selection are S07's responsibility. S23 handles what happens after all tiers are exhausted. — Handled in S07.

---

## 11. Migration Notes (Issue #128)

- Public health/readiness paths are canonicalized as `/api/v1/health` and
  `/api/v1/health/ready`.
- `correlation_id` remains the canonical envelope field for traceability.
  `request_id` naming is non-normative legacy terminology and should not appear in
  response schemas.
- Input validation category `input_invalid` remains canonical at HTTP 400 (including
  whitespace-only turn input). Schema/type violations from Pydantic use `schema_invalid`
  at HTTP 422.

---

## Appendix

### A. Glossary

| Term | Definition |
|---|---|
| **Error taxonomy** | The classification system for all errors in TTA (§3.1). Each error maps to exactly one category. |
| **Circuit breaker** | A pattern that stops calling a failing service after a threshold, allowing it to recover before retrying. |
| **Correlation ID** | A unique identifier that links a player-visible error to the corresponding server-side log entry. |
| **Turn atomicity** | The guarantee that a turn either fully completes or fully rolls back — no partial state changes. |
| **Graceful degradation** | The system's ability to continue operating (possibly with reduced functionality) when components fail. |
| **Fail-fast** | Immediately returning an error rather than waiting for a timeout, used when a service is known to be down. |

### B. References

- [Martin Fowler — Circuit Breaker](https://martinfowler.com/bliki/CircuitBreaker.html)
- [Microsoft — Transient Fault Handling](https://learn.microsoft.com/en-us/azure/architecture/best-practices/transient-faults)
- [RFC 7807 — Problem Details for HTTP APIs](https://tools.ietf.org/html/rfc7807)

### C. Structural Notes

This spec intentionally separates concerns:
- **Sections 1-7**: Functional specification ("what") — behavior-focused, no tech choices
- **Section 8**: Integration boundaries — contracts between specs
- **Sections 9-10**: Scope management — what's unknown, what's excluded

The technical plan ("how") and task breakdown are separate documents generated
during the Plan and Tasks phases of the SDD workflow.
