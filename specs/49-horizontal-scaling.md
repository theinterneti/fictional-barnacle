# S49 — Horizontal Scaling & Multi-Instance Sessions

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v3
> **Implementation Fit**: ❌ Not Started
> **Level**: 4 — Operations
> **Dependencies**: v1 S11 (Player Identity & Sessions), v1 S12 (Persistence Strategy)
> **Related**: S46 (Cloud Deployment), S48 (Async Job Runner), v1 S10 (API & Streaming)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

v1 TTA runs as a single process. For v3, TTA must tolerate multiple instances
of the FastAPI process running behind a load balancer without any session
data loss or routing failures.

**Clarifying note on the project charter's "single FastAPI process, no
microservices" mandate.** S49 does not introduce microservices. Each instance
is a full, self-contained FastAPI process. Horizontal scaling runs multiple
*identical* copies. No service decomposition occurs.

This spec answers:
- Session affinity vs. stateless sessions: which approach?
- How are Redis-backed sessions shared across instances?
- How is SSE (streaming) handled when a player's instance restarts or moves?
- What is the ARQ job deduplication strategy across multiple workers?

---

## 2. Design Decisions

### 2.1 Stateless Sessions via Redis (No Affinity)

**Decision**: TTA uses **stateless sessions** stored entirely in Redis. No
session affinity (sticky sessions) at the load balancer is required.

Rationale:
- All session state is already in Redis (S11). Per-instance in-memory session
  caches are not used. Any instance can serve any request.
- Session affinity complicates rolling deploys and health-check routing.
- Fly.io's proxy does not guarantee sticky sessions for free; stateless is
  more reliable.
- The only complication is SSE streams (see §2.2).

Alternatives considered:
- **Session affinity**: Simpler for SSE but creates hot spots and complicates
  deploys. Rejected.

### 2.2 SSE and Multi-Instance Routing

SSE connections (S10 streaming) are long-lived; they must remain on the same
instance for the duration of the stream. However, when an instance restarts
(e.g., rolling deploy), the client MUST reconnect to another instance.

**Decision**: Use **Fly.io session affinity** for SSE connections only.
Fly's `fly-force-instance-id` response header enables affinity for a specific
request type. SSE endpoints set this header; non-streaming endpoints do not.

If the pinned instance disappears, the client sees a stream error and the
existing SSE reconnect logic (S10 FR-10.16) handles reconnection to a new
instance. The new instance reconstructs turn state from Redis + PostgreSQL.

### 2.3 Redis PubSub for Cross-Instance Notifications

In-process event notifications (e.g., admin broadcast, session invalidation)
that previously relied on in-process state MUST be migrated to Redis PubSub
channels so all instances receive the event.

---

## 3. Functional Requirements

### FR-49.01 — No In-Process Session State

After S49, no in-process Python object SHALL hold the canonical copy of any
session attribute. All reads and writes to session state MUST go through Redis.
A code audit SHALL be performed as part of S49 to identify and remove any
remaining in-process caches of session data.

### FR-49.02 — Redis Session Key Schema

Session keys in Redis SHALL follow the pattern:
- `tta:session:{session_id}` → JSON blob (all session fields from S11)
- `tta:session_idx:player:{player_id}` → sorted set of session IDs (S11 FR-11.09)

All reads use `GET`; all writes use `SET ... EX {ttl}`. No instance-local
shadow copies.

### FR-49.03 — SSE Affinity Header

Every SSE response from `GET /api/v1/games/{id}/stream` SHALL include:
```
fly-force-instance-id: {fly_machine_id}
```
where `fly_machine_id` is read from the `FLY_MACHINE_ID` environment variable.
In non-Fly environments (local dev, CI), this header is omitted.

### FR-49.04 — SSE Client Reconnect Behavior

The static web client (S10) SHALL implement SSE reconnect with:
- `EventSource` `onerror` handler that reconnects after 2 seconds
- On reconnect, re-sends `Last-Event-ID` header to resume from last event
- Server uses `Last-Event-ID` to replay events since that ID from a
  Redis stream (or returns `204 No Content` if no new events are available
  and the game is in a terminal state)

### FR-49.05 — Redis PubSub for Admin Broadcasts

Admin operations that must reach all instances (e.g., session invalidation,
game termination signals) SHALL publish to a Redis channel `tta:broadcast`.
Each instance subscribes to this channel on startup and acts on messages
it receives. Instances that are not subscribed when a message is published
will pick up state from Redis on next request (eventual consistency).

### FR-49.06 — ARQ Job Deduplication

When multiple worker processes are running (one per Fly Machine), ARQ's
built-in job deduplication via `_job_id` SHALL be used for all cron jobs.
The `job_id` for cron jobs is the job function name + UTC date (truncated to
the hour). This prevents multiple workers from running the same retention
sweep simultaneously.

### FR-49.07 — Fly Autoscale Configuration

For v3, Fly autoscaling SHALL be configured to scale between 1 and 3
instances based on HTTP request concurrency (`min = 1, max = 3`).
Scaling thresholds and instance sizes are defined in `fly.toml`.

### FR-49.08 — Health Check Ensures Redis Connectivity

The `/api/v1/health/ready` endpoint (S15) SHALL include a Redis connectivity
check. If Redis is unreachable, the instance returns `503`. The load balancer
removes it from rotation until Redis is restored. This prevents an instance
without session access from serving requests.

### FR-49.09 — Load Test Requirement

Before v3 release, a load test SHALL be run against the staging environment
with 2 instances and 50 concurrent SSE connections. The test verifies:
- No session data loss when a request hits a different instance than the SSE
  stream
- P95 response time for `POST /api/v1/games/{id}/turn` < 2 seconds under load
- Zero session corruption events in Redis during the test

---

## 4. Acceptance Criteria (Gherkin)

```gherkin
Feature: Horizontal Scaling

  Scenario: AC-49.01 — Session readable from any instance
    Given a session created on instance A
    When a request for that session arrives on instance B
    Then instance B reads the full session from Redis
    And returns a correct response without re-authentication

  Scenario: AC-49.02 — SSE affinity header is set
    Given FLY_MACHINE_ID = "machine-xyz"
    When GET /api/v1/games/{id}/stream is called
    Then the response includes header fly-force-instance-id: machine-xyz

  Scenario: AC-49.03 — SSE client reconnects after instance restart
    Given a client is receiving an SSE stream on instance A
    When instance A is stopped (simulated rolling deploy)
    Then the client reconnects within 5 seconds
    And the new SSE stream resumes from Last-Event-ID

  Scenario: AC-49.04 — Admin session invalidation reaches all instances
    Given 2 instances are running
    And admin invalidates session S on instance A
    When any subsequent request with session S arrives on instance B
    Then instance B rejects the session as invalid

  Scenario: AC-49.05 — Duplicate cron jobs are prevented
    Given 2 ARQ workers are running
    When the hourly cron fires at 03:00 UTC
    Then only one instance of retention_sweep runs
    And the second worker's job is deduplicated by job_id

  Scenario: AC-49.06 — Instance without Redis is removed from rotation
    Given an instance cannot reach Redis
    When GET /api/v1/health/ready is called on that instance
    Then 503 is returned
    And the load balancer stops routing to the instance
```

---

## 5. Out of Scope

- Multi-region deployments (all instances in a single Fly region for v3).
- Database read replicas (all instances share one PostgreSQL primary).
- Redis clustering (single Redis instance is sufficient for v3 scale).
- Distributed Neo4j (CE is single-instance; clustering deferred to v4+).
- WebSocket transport (handled by S59 in v4+; SSE is the v3 streaming model).

---

## 6. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-49.01 | Session affinity vs stateless sessions? | ✅ Resolved | **Stateless sessions via Redis** for all request types; **Fly-instance affinity for SSE only** via `fly-force-instance-id` response header. |
| OQ-49.02 | How to handle SSE on instance loss? | ✅ Resolved | Client reconnects via existing SSE `onerror` + `Last-Event-ID` replay from Redis stream. No additional server-side machinery needed. |
