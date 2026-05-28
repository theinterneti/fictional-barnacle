# S48 — Async Job Runner

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v3
> **Implementation Fit**: ⚠️ Partial
> **Level**: 4 — Operations
> **Dependencies**: v1 S17 (Data Privacy / GDPR), v1 S26 (Admin Tooling), S46 (Cloud Deployment Target), S49 (Horizontal Scaling), S66 (Rate-Limit Budget & Task Prioritization)
> **Related**: S46 (Cloud Deployment), v1 S15 (Observability)
> **Last Updated**: 2026-05-28

---

## 1. Purpose

In v1, operations that should run asynchronously (GDPR deletion requests,
data-retention sweeps, backfill jobs) are either handled inline on the
request path (causing latency spikes) or simply deferred. S48 introduces a
minimal async job runner: a persistent worker process that consumes jobs from
a Redis queue, runs them, and reports results.

The worker process is explicitly **not a microservice**. It shares the same
codebase and image as the FastAPI process; it is started with a different
entrypoint. In Fly.io (S46), the API and worker run as separate process groups from the same image (`app` and `worker`) and may run on separate Fly Machines when memory or shutdown requirements demand it. In local dev they may run on the same host. The single-process-per-deployment-unit mandate applies per process group; the worker is a separate process, not a separate service or codebase.

---

## 2. User Stories

- **As an** operator, **I want** slow maintenance work to run outside request handling, **so that** user-facing endpoints are not blocked by retention or erasure jobs.
- **As a** player, **I want** GDPR deletion and retention behavior to complete reliably, **so that** privacy guarantees are operational rather than aspirational.
- **As a** developer, **I want** all job enqueueing to go through a testable queue abstraction, **so that** job behavior can be verified without Redis in unit tests.
- **As an** operator, **I want** failed jobs to be observable and recoverable, **so that** dead-letter work does not disappear silently.

## 3. Design Decisions

### 3.1 Job Runner Library: ARQ

**Decision**: TTA uses **ARQ** (Async Redis Queue) as the job runner.

Rationale:
- ARQ is asyncio-native; jobs are `async def` coroutines — no sync/async
  bridge required.
- TTA already depends on Redis (S11 sessions, S12 persistence). No new
  infrastructure is added.
- ARQ's dependency set is minimal: `arq` + the existing `redis` client.
- ARQ supports job retries, timeouts, cron scheduling, and result storage.
- Celery requires a broker abstraction layer and heavier dependencies.
- RQ is sync-only; Dramatiq lacks built-in asyncio support.

### 3.2 Worker Entrypoint

The worker is started via:
```bash
uv run arq tta.jobs.worker.WorkerSettings
```

In Docker Compose, a `tta-worker` service (already defined in S14 FR-14.2) runs this command. In Fly.io (S46), the worker runs as a separate `worker` process group from the same image. The default v3 topology is one API process group and one worker process group; co-location on the same physical host is not required and must not be assumed for memory budgeting.

### 3.3 Job Catalog

The following job types are defined in v3:

| Job ID | Trigger | Description | Timeout |
|---|---|---|---|
| `gdpr_delete_player` | API: POST /admin/players/{id}/delete | Full GDPR erasure (S17 FR-17.09) | 120s |
| `retention_sweep` | Cron: daily 03:00 UTC | Delete data past retention window (S17 FR-17.07) | 600s |
| `session_cleanup` | Cron: hourly | Remove expired Redis session keys (S11) | 60s |
| `game_backfill` | Admin: POST /admin/jobs/game-backfill | Rebuild derived data from event log in resumable chunks | 1800s total, chunked into <=25s units |

---

## 4. Functional Requirements

### FR-48.01 — ARQ WorkerSettings

A `WorkerSettings` class in `src/tta/jobs/worker.py` SHALL define:
```python
class WorkerSettings:
    functions = [gdpr_delete_player, retention_sweep, session_cleanup, game_backfill]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 1800  # global max; per-job timeouts enforce tighter limits
    keep_result = 3600  # seconds to retain job result in Redis
    queue_name = "tta:jobs"
    cron_jobs = [
        cron(retention_sweep, hour=3, minute=0),
        cron(session_cleanup, minute=0),
    ]
```

### FR-48.02 — Job Enqueue API

Jobs SHALL be enqueued via an `ArqQueue` abstraction in `src/tta/jobs/queue.py`
that is injected as `app.state.job_queue` in the FastAPI lifespan. Job callers
MUST NOT access ARQ's `ArqRedis` directly; all enqueue calls go through the
abstraction. This allows the queue to be mocked in tests.

```python
class ArqQueue:
    async def enqueue(self, job_fn: str, *args, _job_id: str | None = None, **kwargs) -> str:
        ...
    async def job_status(self, job_id: str) -> JobStatus | None:
        ...
```

### FR-48.03 — GDPR Deletion Job

The `gdpr_delete_player` job implements the erasure sequence from S17 FR-17.09:
1. Delete player record from PostgreSQL (cascades to sessions, consent records)
2. Delete all `MemoryRecord` nodes for the player from Neo4j
3. Delete player session keys from Redis
4. Emit `player_erased` audit log event
5. If any step fails, the job retries up to 3 times before marking `failed`

Idempotency: if the player no longer exists at job start, the job returns
`already_erased` and exits successfully.

### FR-48.04 — Retention Sweep Job

The `retention_sweep` job queries PostgreSQL for records past the S17
retention window. It deletes them in batches of 500 with a 100ms sleep
between batches to prevent lock contention. The job logs the count of
deleted records as a structured event.

### FR-48.05 — Job Observability

For every job execution, the worker SHALL emit a structured log event with:
- `job_id`, `job_fn`, `status` (queued/started/complete/failed)
- `duration_ms` (on complete/failed)
- `error` (on failed, without PII)

Prometheus metrics SHALL include:
- `tta_job_runs_total{job_fn, status}` (counter)
- `tta_job_duration_seconds{job_fn}` (histogram)

### FR-48.06 — Graceful Shutdown

The ARQ worker SHALL handle `SIGTERM` by completing the current chunk of work and then exiting before the deployment stop timeout. Jobs with individual timeouts longer than the platform stop timeout, such as `game_backfill`, MUST be resumable and chunked into <=25s units under Fly's default 30s stop timeout, or S46 must explicitly raise the worker stop timeout. In-flight jobs are never reported as successful until their durable checkpoint is complete.

### FR-48.07 — Admin Job Enqueueing

The existing admin API (S26) SHALL gain two endpoints:
- `POST /admin/jobs/{job_type}/enqueue` — enqueues an allowed job type on demand and returns a generated `job_id`
- `GET /admin/jobs/{job_id}/status` — returns current status from ARQ result store

These endpoints require admin authentication (S26 AC).

### FR-48.08 — Dead Letter Handling

Jobs that exhaust their retries SHALL be moved to a `tta:jobs:dead` dead-letter
queue key in Redis. A Prometheus alert SHALL fire if the dead-letter count exceeds 5 in a 1-hour window or if any single dead-letter job remains unacknowledged for more than 24 hours. The admin can inspect dead-letter jobs via `GET /admin/jobs/dead`.

---

## 5. Non-Functional Requirements

### NFR-48.01 — Request-path isolation

**Category**: Performance

**Target**: Retention, cleanup, backfill, and erasure jobs do not run inline on player-facing request paths.

### NFR-48.02 — Job observability

**Category**: Operations

**Target**: Every job transition emits structured logs and metrics with job ID, function, status, duration, and sanitized failure details.

### NFR-48.03 — Idempotent recovery

**Category**: Reliability

**Target**: Retryable jobs either complete idempotently or land in dead-letter storage with enough metadata for operator action.

## 6. User Journeys

### Journey 1: Admin enqueues a maintenance job

- **Trigger**: An authenticated admin requests a supported job.
- **Steps**:
  1. API validates the job name and authorization.
  2. Queue abstraction enqueues the ARQ job and returns a job ID.
  3. Worker picks up the job, emits started/completed metrics, and stores the result.
  4. Admin checks job status through the API.
- **Happy path**: Maintenance work completes without blocking user-facing requests.
- **Alternative paths**: Unknown job names, Redis failure, or exhausted retries produce explicit failures.

### Journey 2: Scheduled cleanup runs automatically

- **Trigger**: ARQ cron fires for retention or session cleanup.
- **Steps**:
  1. Worker starts the scheduled job.
  2. Job processes records in bounded batches.
  3. Success/failure metrics are emitted.
- **Happy path**: Cleanup finishes within timeout and leaves an auditable result.

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | Redis is unavailable when enqueueing | Caller receives a clear enqueue failure; no job is reported as accepted. |
| E2 | GDPR job starts for an already-erased player | Job exits successfully with `already_erased`. |
| E3 | Retention sweep hits a transient database error | Job retries according to policy and logs sanitized failure details. |
| E4 | Worker receives SIGTERM during a job | Current job completes within timeout or is safely retried; no partial silent success. |
| E5 | Job exhausts retries | Job moves to dead-letter storage and increments failure metrics. |
| E6 | Admin tries to enqueue an unknown job | API rejects the request with a clear allowed-job list. |
| E7 | Job result contains PII | Logging/result serialization strips or redacts protected values. |

## 8. Acceptance Criteria (Gherkin)

```gherkin
Feature: Async Job Runner

  Scenario: AC-48.01 — GDPR erasure job runs end-to-end
    Given a player with sessions, memory records, and consent records
    When gdpr_delete_player(player_id) is enqueued and runs
    Then all player records are deleted from PostgreSQL
    And all MemoryRecord nodes are deleted from Neo4j
    And all Redis session keys for the player are removed
    And an audit log event player_erased is emitted

  Scenario: AC-48.02 — GDPR job is idempotent
    Given a player has already been erased
    When gdpr_delete_player(player_id) is enqueued again
    Then the job returns already_erased
    And exits with success (no retry)

  Scenario: AC-48.03 — Retention sweep deletes expired records in batches
    Given 1200 records past the retention window exist
    When retention_sweep runs
    Then records are deleted in batches of 500
    And a structured log event records deleted_count = 1200

  Scenario: AC-48.04 — Failed jobs after 3 retries land in dead-letter queue
    Given a job fails 3 times consecutively
    When the worker exhausts retries
    Then the job is added to tta:jobs:dead
    And tta_job_runs_total{status="failed"} is incremented

  Scenario: AC-48.05 — Worker shuts down gracefully on SIGTERM
    Given the worker is processing a job
    When SIGTERM is received
    Then the current job completes before the process exits
    And no job is left in an inconsistent state

  Scenario: AC-48.06 — Admin can enqueue and check job status
    Given an authenticated admin request
    When POST /admin/jobs/session_cleanup/enqueue is called
    Then a job_id is returned
    And GET /admin/jobs/{job_id}/status returns the current state
```

### Criteria Checklist

- [ ] **AC-48.01**: GDPR erasure job runs end-to-end.
- [ ] **AC-48.02**: GDPR job is idempotent.
- [ ] **AC-48.03**: Retention sweep deletes expired records in batches.
- [ ] **AC-48.04**: Failed jobs after 3 retries land in dead-letter queue.
- [ ] **AC-48.05**: Worker shuts down gracefully on SIGTERM.
- [ ] **AC-48.06**: Admin can enqueue and check job status.

---

## 9. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|---|---|---|
| S11 | Sessions | Session cleanup jobs operate on Redis-backed session state. |
| S12 | Persistence | Backfill/retention jobs operate on canonical persistent stores. |
| S17 | Data privacy | GDPR and retention jobs implement privacy lifecycle guarantees. |
| S26 | Admin tooling | Admin endpoints enqueue and inspect supported jobs. |
| S46 | Cloud deployment | Deployment must start API and worker entrypoints from the same image. |
| S49 | Horizontal scaling | Multiple workers require deduplication for scheduled jobs. |

## 10. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-48.01 | ARQ vs Celery vs RQ? | ✅ Resolved | **ARQ** — asyncio-native, Redis-backed (no new infra), minimal dependencies, built-in cron. |
| OQ-48.02 | Worker co-location or separate host? | ✅ Resolved | **Same Fly Machine in v3** (entrypoint process; fits single-unit mandate). S49 review will address scaling the worker separately if needed. |

## 11. Out of Scope

- Distributed job locking across multiple worker instances (S49 concern).
- Priority queues (all jobs share one queue in v3).
- Job scheduling UI (admin API endpoints are sufficient for v3).
- Long-running generative jobs (LLM calls happen on the request path; S08).

---
