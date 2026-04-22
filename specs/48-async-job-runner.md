# S48 — Async Job Runner

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v3
> **Implementation Fit**: ❌ Not Started
> **Level**: 4 — Operations
> **Dependencies**: v1 S17 (Data Privacy / GDPR), v1 S26 (Admin Tooling)
> **Related**: S46 (Cloud Deployment), v1 S15 (Observability)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

In v1, operations that should run asynchronously (GDPR deletion requests,
data-retention sweeps, backfill jobs) are either handled inline on the
request path (causing latency spikes) or simply deferred. S48 introduces a
minimal async job runner: a persistent worker process that consumes jobs from
a Redis queue, runs them, and reports results.

The worker process is explicitly **not a microservice**. It shares the same
codebase and image as the FastAPI process; it is started with a different
entrypoint. Both processes run within a single Fly Machine (or on the same
host in local dev). The single-process-per-deployment-unit mandate from the
project charter applies per-instance; a worker co-located on the same machine
is a separate process, not a separate service.

---

## 2. Design Decisions

### 2.1 Job Runner Library: ARQ

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

### 2.2 Worker Entrypoint

The worker is started via:
```bash
uv run arq tta.jobs.worker.WorkerSettings
```

In Docker Compose, a `tta-worker` service (already defined in S14 FR-14.2)
runs this command. In Fly.io (S46), a second Machine in the same app runs
the worker entrypoint.

### 2.3 Job Catalog

The following job types are defined in v3:

| Job ID | Trigger | Description | Timeout |
|---|---|---|---|
| `gdpr_delete_player` | API: POST /admin/players/{id}/delete | Full GDPR erasure (S17 FR-17.09) | 120s |
| `retention_sweep` | Cron: daily 03:00 UTC | Delete data past retention window (S17 FR-17.07) | 600s |
| `session_cleanup` | Cron: hourly | Remove expired Redis session keys (S11) | 60s |
| `game_backfill` | Admin: POST /admin/jobs/game-backfill | Rebuild derived data from event log | 1800s |

---

## 3. Functional Requirements

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

The ARQ worker SHALL handle `SIGTERM` by completing the current job (up to
its individual timeout) and then exiting. In-flight jobs are not interrupted
mid-execution on graceful shutdown. A `SIGKILL` fallback occurs after the
deployment max stop timeout (configurable; default 30s in Fly).

### FR-48.07 — Admin Job Enqueueing

The existing admin API (S26) SHALL gain two endpoints:
- `POST /admin/jobs/{job_id}/enqueue` — enqueues a named job on demand
- `GET /admin/jobs/{job_id}/status` — returns current status from ARQ result store

These endpoints require admin authentication (S26 AC).

### FR-48.08 — Dead Letter Handling

Jobs that exhaust their retries SHALL be moved to a `tta:jobs:dead` dead-letter
queue key in Redis. A Prometheus alert SHALL fire if the dead-letter count
exceeds 5. The admin can inspect dead-letter jobs via `GET /admin/jobs/dead`.

---

## 4. Acceptance Criteria (Gherkin)

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

---

## 5. Out of Scope

- Distributed job locking across multiple worker instances (S49 concern).
- Priority queues (all jobs share one queue in v3).
- Job scheduling UI (admin API endpoints are sufficient for v3).
- Long-running generative jobs (LLM calls happen on the request path; S08).

---

## 6. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-48.01 | ARQ vs Celery vs RQ? | ✅ Resolved | **ARQ** — asyncio-native, Redis-backed (no new infra), minimal dependencies, built-in cron. |
| OQ-48.02 | Worker co-location or separate host? | ✅ Resolved | **Same Fly Machine in v3** (entrypoint process; fits single-unit mandate). S49 review will address scaling the worker separately if needed. |
