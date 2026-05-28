# S49 — Horizontal Scaling & Multi-Instance Sessions

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v3
> **Implementation Fit**: ⚠️ Partial
> **Level**: 4 — Operations
> **Dependencies**: v1 S11 (Player Identity & Sessions), v1 S12 (Persistence Strategy)
> **Related**: S46 (Cloud Deployment), S48 (Async Job Runner), v1 S10 (API & Streaming)
> **Last Updated**: 2026-05-28

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

## 2. User Stories

- **As a** player, **I want** my session to continue when requests hit different app instances, **so that** scaling and deploys do not log me out or lose progress.
- **As a** player, **I want** streaming turns to recover after an instance restart, **so that** rolling deploys do not strand an active game.
- **As an** operator, **I want** multiple identical FastAPI instances to share Redis-backed state, **so that** v3 can scale without introducing microservices.
- **As a** developer, **I want** cron/job deduplication across workers, **so that** multiple instances do not run destructive maintenance jobs twice.

## 3. Design Decisions

### 3.1 Stateless Sessions via Redis (No Affinity)

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

### 3.2 SSE and Multi-Instance Routing

SSE connections (S10 streaming) are long-lived; they must remain on the same
instance for the duration of the stream. However, when an instance restarts
(e.g., rolling deploy), the client MUST reconnect to another instance.

**Decision**: SSE correctness MUST NOT depend on sticky sessions. A stream naturally stays on the instance that accepted the TCP connection for its lifetime, and reconnect correctness is provided by Redis-backed replay/snapshot state. Fly routing hints such as documented `fly-prefer-instance-id`, `fly-force-instance-id`, or `fly-replay` MAY be evaluated as an optimization in the implementation plan, but they are not the v3 correctness mechanism and must not be required for local/CI behavior.

If the streaming instance disappears, the client sees a stream error and the existing SSE reconnect logic (S10 FR-10.41–FR-10.44, AC-10.05) handles reconnection to a healthy instance. The new instance reconstructs turn state from Redis + PostgreSQL.

### 3.3 Redis PubSub for Cross-Instance Notifications

In-process event notifications (e.g., admin broadcast, session invalidation)
that previously relied on in-process state MUST be migrated to Redis PubSub
channels so all instances receive the event.

---

## 4. Functional Requirements

### FR-49.01 — No In-Process Session State

After S49, no in-process Python object SHALL hold the canonical copy of any
session attribute. All reads and writes to session state MUST go through Redis.
A code audit SHALL be performed as part of S49 to identify and remove any
remaining in-process caches of session data.

### FR-49.02 — Redis Session Key Schema

Session keys in Redis SHALL follow the pattern:
- `tta:session:{session_id}` → JSON blob (all session fields from S11)
- `tta:session_idx:player:{player_id}` → sorted set of active session IDs for the player (score = creation Unix timestamp). This is an S49-required implementation gap if not already present in the S11 Redis session store.

All reads use `GET`; all writes use `SET ... EX {ttl}`. No instance-local
shadow copies.

### FR-49.03 — SSE Reconnect Portability

`GET /api/v1/games/{id}/stream` SHALL be correct when reconnects land on any healthy instance. The endpoint MAY emit or consume Fly.io routing hints only as an optimization after verifying the current Fly documentation, but no acceptance criterion may depend on a specific Fly-only header. In non-Fly environments (local dev, CI), behavior is identical except for the absence of routing hints.

### FR-49.04 — Cross-Instance Event Log

SSE reconnect protocol (EventSource `onerror`, 2 s delay, `Last-Event-ID`
header) is governed by S10 (FR-10.41–FR-10.44, AC-10.05). S49's novel
addition is the backing store that makes reconnection to *any* instance
possible:

- All instances that stream events to clients SHALL persist each SSE event to a cross-instance replay store before or while sending it to the client. The preferred v3 store is a Redis stream keyed `tta:stream:{session_id}` (XADD, `MAXLEN ~` 500). If existing code uses a different Redis structure, S49 implementation must either migrate it or document the equivalent replay guarantees before approval.
- On reconnect, the receiving instance (which may differ from the original) SHALL replay events since `Last-Event-ID` from the cross-instance replay store, rather than relying on in-process memory.
- If the replay entry for `Last-Event-ID` has been evicted, the instance SHALL return a snapshot of current game state instead of replaying.

### FR-49.05 — Redis PubSub for Admin Broadcasts

Admin operations that must reach all instances (e.g., session invalidation,
game termination signals) SHALL publish to a Redis channel `tta:broadcast`.
Each instance subscribes to this channel on startup and acts on messages
it receives. Instances that are not subscribed when a message is published will pick up canonical invalidation/session state from Redis on next request (eventual consistency). Broadcasts that have no durable Redis state are best-effort only and MUST NOT be used for security-critical invalidation.

### FR-49.06 — ARQ Job Deduplication

When multiple worker processes are running (one per Fly Machine), ARQ's
built-in job deduplication via `_job_id` SHALL be used for all cron jobs.
The `job_id` for cron jobs uses the explicit format `{job_fn}:{YYYYMMDDHH}` in UTC, truncated to the hour. This prevents multiple workers from running the same retention sweep simultaneously and matches S48 cron semantics.

### FR-49.07 — Fly Autoscale Configuration

For v3, Fly autoscaling SHALL be configured to scale between 1 and 3 instances based on HTTP request concurrency (`min = 1, max = 3`) for cost-aware staging/beta operation. If S46 requires no user-visible interruption during routine deploys, production must run `min >= 2`; otherwise S46 must phrase the guarantee as reconnect/recovery rather than strict zero downtime. Scaling thresholds and instance sizes are defined in the Fly configuration artifact.

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

## 5. Non-Functional Requirements

### NFR-49.01 — Session consistency

**Category**: Reliability

**Target**: Any healthy instance can serve any non-streaming session request without relying on instance-local state.

### NFR-49.02 — Stream recovery

**Category**: Reliability

**Target**: SSE clients recover from instance loss within 5 seconds when network and backend stores are healthy.

### NFR-49.03 — Bounded v3 scale

**Category**: Scalability

**Target**: v3 scales within a single region from 1 to 3 identical FastAPI instances without service decomposition.

## 6. User Journeys

### Journey 1: Player continues across instances

- **Trigger**: A load balancer routes a session request to a different instance.
- **Steps**:
  1. Instance reads session state from Redis.
  2. Instance processes the request without requiring sticky session state.
  3. Updated state is written back to Redis.
- **Happy path**: Player sees no difference when requests move between instances.
- **Alternative paths**: If Redis is unavailable, readiness removes the instance from rotation.

### Journey 2: SSE reconnects after rolling deploy

- **Trigger**: The instance serving a stream stops during deploy.
- **Steps**:
  1. Client detects stream error and reconnects.
  2. New instance reads `Last-Event-ID` and Redis stream state.
  3. Missing events replay, or current snapshot is returned if replay is no longer possible.
- **Happy path**: The active turn resumes without session loss.

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | Request lands on an instance different from the original session creator | Instance reads canonical session state from Redis and serves normally. |
| E2 | SSE instance stops during rolling deploy | Client reconnects and receives replay/snapshot according to Redis stream state. |
| E3 | Redis stream no longer contains `Last-Event-ID` | New instance returns current game snapshot instead of replaying missing events. |
| E4 | Redis is unreachable from one instance | Readiness returns 503 and load balancer removes that instance. |
| E5 | Two workers receive the same cron trigger | ARQ `_job_id` deduplication allows only one job execution. |
| E6 | Admin broadcast occurs while an instance is down | Down instance observes canonical Redis state on next request after restart. |
| E7 | Fly routing hints are absent or ignored | Local/CI behavior remains valid; reconnect correctness comes from Redis-backed replay/snapshot state, not affinity. |

## 8. Acceptance Criteria (Gherkin)

```gherkin
Feature: Horizontal Scaling

  Scenario: AC-49.01 — Session readable from any instance
    Given a session created on instance A
    When a request for that session arrives on instance B
    Then instance B reads the full session from Redis
    And returns a correct response without re-authentication

  Scenario: AC-49.02 — SSE reconnect is instance-portable
    Given an SSE stream originally ran on instance A
    And the next reconnect is routed to instance B
    When GET /api/v1/games/{id}/stream resumes with Last-Event-ID
    Then instance B uses the cross-instance replay store or current-state snapshot
    And the response does not depend on instance-local stream memory

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

### Criteria Checklist

- [ ] **AC-49.01**: Session readable from any instance.
- [ ] **AC-49.02**: SSE reconnect is instance-portable.
- [ ] **AC-49.03**: SSE client reconnects after instance restart.
- [ ] **AC-49.04**: Admin session invalidation reaches all instances.
- [ ] **AC-49.05**: Duplicate cron jobs are prevented.
- [ ] **AC-49.06**: Instance without Redis is removed from rotation.

---

## 9. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|---|---|---|
| S10 | API & streaming | SSE reconnect protocol and Last-Event-ID behavior remain the client/server contract. |
| S11 | Sessions | Redis is the canonical session store across instances. |
| S12 | Persistence | Durable game/session data must be reconstructable after instance loss. |
| S15 | Observability | Readiness and scaling failures must be visible through health and metrics. |
| S46 | Cloud deployment | Fly.io deployment provides the single-region multi-instance runtime. |
| S48 | Async job runner | Worker deduplication prevents duplicate scheduled jobs across instances. |

## 10. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-49.01 | Session affinity vs stateless sessions? | ✅ Resolved | **Stateless sessions via Redis** for all request types; **Fly-instance affinity for SSE only** via `fly-force-instance-id` response header. |
| OQ-49.02 | How to handle SSE on instance loss? | ✅ Resolved | Client reconnects via existing SSE `onerror` + `Last-Event-ID` replay from Redis stream. No additional server-side machinery needed. |

## 11. Out of Scope

- Multi-region deployments (all instances in a single Fly region for v3).
- Database read replicas (all instances share one PostgreSQL primary).
- Redis clustering (single Redis instance is sufficient for v3 scale).
- Distributed Neo4j (CE is single-instance; clustering deferred to v4+).
- WebSocket transport (handled by S59 in v4+; SSE is the v3 streaming model).

---
