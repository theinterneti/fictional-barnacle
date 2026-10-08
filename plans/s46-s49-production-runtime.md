# S46-S49 Production Runtime Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.
> **Status**: Draft
> **Scope**: S46, S47, S48, S49
> **Wave**: v2.1 Production Runtime
> **Specs Covered**: S46, S47, S48, S49
> **Last Updated**: 2026-05-28

**Goal:** Convert the production-runtime cluster into an executable, SDD-safe slice: deployable Fly.io artifacts, live Neo4j integration gates, ARQ-backed background jobs, and horizontal-scaling runtime contracts that can be verified locally and in CI.

**Architecture:** The FastAPI application stays the single runtime surface. PostgreSQL remains the durable source of truth. Redis owns ephemeral cross-instance coordination: rate limiting, session/cache handoff, SSE replay/results, ARQ queues, locks, and admin broadcasts. Neo4j remains the world-graph engine and must be exercised by live service tests, not mocks. Fly.io deployment artifacts should be thin wrappers around the existing Docker image and environment/secrets contract.

**Tech Stack:** FastAPI, Uvicorn, SQLModel/SQLAlchemy async sessions, PostgreSQL, Redis/redis.asyncio, ARQ, Neo4j async driver, Prometheus metrics, OpenTelemetry/Langfuse where already wired, Docker, docker-compose.test.yml, GitHub Actions, Fly.io Machines.

---

## Bundle Scope

Included specs:

1. S46 — Cloud Deployment Target
2. S47 — Live Neo4j in CI
3. S48 — Async Job Runner
4. S49 — Horizontal Scaling

Not included:

- Multi-region production operations.
- Enterprise-grade secret rotation automation.
- Full Kubernetes or Terraform platform migration.
- Production load beyond the bounded v3 target in S49.
- Replacing Redis/ARQ with a heavier queue stack.
- Implementing speculative v4/v5 social, therapeutic, or multiverse runtime needs.

## Current-State Anchors

The implementation should build from these existing surfaces rather than invent parallel runtime paths:

- `src/tta/api/app.py` already centralizes FastAPI lifespan wiring for PostgreSQL, Redis, Neo4j, Langfuse, OpenTelemetry, prompt registry, LLM client, repositories, lifecycle cleanup, privacy purge, pool metrics, and Redis TTL monitoring.
- `src/tta/api/health.py` already exposes `/api/v1/health` and `/api/v1/health/ready`, with PostgreSQL critical and Redis/Neo4j/LLM breaker surfaced in readiness.
- `src/tta/api/turn_results.py` already has memory and Redis turn-result stores for cross-instance POST-to-SSE delivery.
- `src/tta/persistence/redis_session.py` already owns the canonical session-cache and SSE replay key templates.
- `tests/integration/test_s28_horizontal_scaling.py` already proves the important local surrogate for two app instances sharing PostgreSQL and Redis.
- `tests/integration/conftest.py` and `docker-compose.test.yml` already provide live PostgreSQL, Redis, and Neo4j test services.
- `.github/workflows/ci.yml` already starts `docker-compose.test.yml` for integration tests, but the S47 live-Neo4j contract needs stronger explicit gating and faster failure diagnostics.
- `pyproject.toml` already includes `arq`, `redis`, `neo4j`, `prometheus-client`, and OpenTelemetry dependencies.

These anchors mean the plan is mostly a hardening/integration plan, not a greenfield runtime rewrite.

## Dependency Ordering

S46-S49 are tightly coupled, but the safest execution order is not numeric:

1. S47 first: make live service tests deterministic and visible, because every later runtime step depends on PostgreSQL/Redis/Neo4j confidence.
2. S49 second: finish cross-instance state and SSE/admin broadcast primitives while still using the existing app process.
3. S48 third: move cleanup/maintenance jobs to ARQ once Redis contracts and integration fixtures are trustworthy.
4. S46 last: wire deploy artifacts and CI/CD promotion once runtime behavior is validated locally and in CI.

## Data Model and Persistence Contracts

The runtime slice should not add a second persistence model. It should clarify ownership of existing stores:

- PostgreSQL: durable players, game sessions, turns, audit logs, privacy deletion state, and job audit records.
- Redis: ephemeral session cache, SSE replay buffers/counters, turn-result handoff keys, ARQ queues, dedupe locks, and admin broadcast channels.
- Neo4j: session-scoped world graph state and live graph fixtures for integration tests.
- Fly.io deployment config: process definitions, health checks, and environment/secrets bindings only; no application data.

Redis key families should be documented next to their owning module. New keys should follow the existing `tta:<domain>:<id>` pattern and include TTLs unless the implementation explicitly documents why they are durable.

## Interface Sketch

Final names may change during implementation, but the slice should converge on these contracts.

```python
class RuntimeHealthSnapshot(TypedDict):
    status: Literal["healthy", "degraded", "unhealthy"]
    checks: dict[str, str]
    version: str

class JobEnvelope(TypedDict):
    job_id: str
    kind: Literal["gdpr_delete_player", "retention_sweep", "session_lifecycle", "privacy_purge"]
    correlation_id: str
    dedupe_key: str | None
    requested_by: str

class BroadcastEvent(TypedDict):
    event_id: str
    event_type: Literal["admin_notice", "maintenance", "session_invalidated"]
    payload: dict[str, object]
    created_at: str
```

Normative constraints for implementation:

- Runtime endpoints must not return raw secrets, raw DSNs, provider keys, prompt text, or unredacted bearer tokens.
- Redis keys must remain namespaced under `tta:` and must include bounded TTLs unless explicitly durable.
- Background jobs must be idempotent and safe to retry after worker crash.
- CI live-service tests may skip locally when services are unavailable, but CI must fail loudly when services fail to start.
- Horizontal scaling must prefer Redis-backed delivery over sticky sessions. Fly instance pinning headers may be a compatibility fallback only, not the core correctness mechanism.

## Build Order

### Task 1: Stabilize live service integration gates (S47)

**Objective:** Make PostgreSQL, Redis, and Neo4j service readiness deterministic for local and CI execution.

**Files:**

- Modify: `.github/workflows/ci.yml`
- Modify: `docker-compose.test.yml`
- Modify: `tests/integration/conftest.py`
- Add or modify: `scripts/wait_for_test_services.py` or equivalent lightweight readiness helper
- Add tests if helper logic becomes non-trivial

**Steps:**

1. Replace the CI `docker compose ... up -d --wait || echo warning` pattern with fail-loud startup for integration-test jobs.
2. Add explicit service diagnostics on failure: container status, healthcheck logs, Neo4j logs tail, Redis ping output, and PostgreSQL readiness output.
3. Ensure `tests/integration/conftest.py` fixture skips stay local-developer friendly while CI treats missing services as an infrastructure failure.
4. Keep Neo4j auth disabled only for test services; production/staging settings must keep explicit credentials.
5. Confirm fixture loading order: constraints/indexes first, small world fixtures second, large performance fixture only when performance gates opt in.

**Verification:**

- `docker compose -f docker-compose.test.yml up -d --wait`
- `uv run pytest tests/integration/test_s13_neo4j_integration.py -v --tb=short`
- CI integration job fails if any required test service cannot start.

### Task 2: Pin production configuration contracts (S46 + S49)

**Objective:** Define deploy-time settings so staging/production cannot accidentally run in unsafe development mode.

**Files:**

- Modify: `src/tta/config.py`
- Modify: `src/tta/api/app.py`
- Add or modify: `tests/unit/test_config.py` or closest existing config test module
- Add: deployment config artifacts chosen by the implementation (`fly.toml`, `fly.staging.toml`, or documented templates)
- Add or modify: `docs/deployment.md` if no deployment doc exists

**Steps:**

1. Add production-mode validation for critical settings: `TTA_ENVIRONMENT=production`, non-default JWT secret, PostgreSQL URL, Redis URL, Neo4j URI/user/password, CORS origins, admin API key policy, and LLM backend settings.
2. Ensure configuration validation redacts secrets in error/log messages.
3. Document required Fly secrets without committing secret values.
4. Add a small environment parity checklist for staging vs production variables.
5. Confirm Docker image entrypoint runs the existing FastAPI app without special-case code paths.

**Verification:**

- Unit tests for production config rejection of default/insecure values.
- `uv run python -c "from tta.config import Settings; print(Settings.model_fields.keys())"` or equivalent targeted import smoke test.
- `docker build .` or CI build job remains green.

### Task 3: Finish Redis-backed horizontal scaling primitives (S49)

**Objective:** Ensure game state, turn-result streaming, reconnects, and admin broadcasts work across independent app instances without process affinity.

**Files:**

- Modify: `src/tta/api/turn_results.py`
- Modify: `src/tta/persistence/redis_session.py`
- Modify: `src/tta/api/routes/games_stream.py`
- Modify or add: `src/tta/api/broadcasts.py`
- Modify or add: integration tests under `tests/integration/`

**Steps:**

1. Audit all in-memory runtime state in app lifespan and route handlers. Keep in-memory implementations only for explicit development/test fallback.
2. Confirm `turn_result_backend=redis` is the production default when `llm_mock=False`.
3. Expand cross-instance integration tests beyond narrative delivery to cover reconnect with `Last-Event-ID`, session-cache rehydration, and Redis TTL behavior.
4. Add Redis Pub/Sub or Redis Streams admin broadcast support only for narrow operational messages required by S49.
5. Ensure Redis pub/sub failures degrade explicitly: health/readiness should report Redis unavailable and affected endpoints should fail with bounded, typed errors.
6. Add a bounded local load-test script or pytest-marked integration test for the v3 target in S49, keeping it opt-in if too slow for default CI.

**Verification:**

- `uv run pytest tests/integration/test_s28_horizontal_scaling.py -v --tb=short`
- New cross-instance reconnect/admin-broadcast tests pass with two independent `create_app(settings)` instances.
- `uv run pytest tests/unit/api -k "sse or turn_result or redis" -v` after selecting/adding exact test names.

### Task 4: Introduce ARQ worker infrastructure (S48)

**Objective:** Move maintenance/background work behind a Redis-backed ARQ worker while preserving request-path isolation and idempotent cleanup behavior.

**Files:**

- Add: `src/tta/jobs/__init__.py`
- Add: `src/tta/jobs/worker.py`
- Add: `src/tta/jobs/enqueue.py`
- Add: `src/tta/jobs/tasks.py`
- Modify: `src/tta/api/app.py`
- Modify: `src/tta/api/routes/admin_operations.py`
- Modify or add: unit/integration tests under `tests/unit/jobs/` and `tests/integration/`

**Steps:**

1. Define ARQ `WorkerSettings` using the existing `Settings.redis_url` and safe retry/shutdown defaults.
2. Add an enqueue API that returns a stable `job_id`, logs a correlation ID, and supports dedupe keys for jobs where duplicates are harmful.
3. Implement job functions for GDPR deletion, retention sweep, and any existing lifecycle/purge loops that should become worker-owned.
4. Keep existing in-process loops behind a compatibility switch until ARQ worker operation is proven; production should prefer worker-owned jobs.
5. Expose narrow admin enqueue/status endpoints for allowed maintenance jobs only.
6. Add metrics for enqueued, started, succeeded, failed, retried, and dead-lettered jobs.
7. Add dead-letter handling that preserves sanitized failure metadata without storing raw player content.

**Verification:**

- Unit tests for job envelope construction, dedupe key behavior, idempotent retry, and redacted failure logging.
- Integration test against Redis for enqueue-to-worker execution using a fast no-op or fixture job.
- Privacy/GDPR tests still pass after moving deletion/purge work out of request path.

### Task 5: Wire Fly.io deployment artifacts and CI/CD promotion (S46)

**Objective:** Provide reproducible staging deployment and manual production promotion without adding a second application architecture.

**Files:**

- Add or modify: `fly.toml` and optional staging/prod variants
- Modify: `.github/workflows/ci.yml`
- Add: `.github/workflows/deploy.yml` if deployment should be separate from CI
- Add or modify: deployment docs

**Steps:**

1. Add Fly app configuration for the API process and, if needed, separate worker process group for ARQ.
2. Define health checks against `/api/v1/health/ready` with enough startup grace for PostgreSQL/Redis/Neo4j connection setup.
3. Document and/or script provisioning for Fly Postgres, Upstash/Fly Redis, and Neo4j target service. If Neo4j is external, state that explicitly.
4. Add GitHub Actions deploy workflow with staging on main or manual dispatch, and production via manual promotion only.
5. Ensure deploy workflow references secrets by name only and never echoes secret values.
6. Add rollback runbook: previous image redeploy, worker rollback, DB migration caveats, and expected smoke checks.

**Verification:**

- `docker build .` succeeds.
- Deployment workflow lints structurally.
- Staging deploy smoke sequence is documented and, when credentials exist, runnable:
  - `/api/v1/health`
  - `/api/v1/health/ready`
  - `/privacy`
  - one no-spend mock-LLM game/session smoke if staging supports mock mode.

### Task 6: Bundle gate and documentation lock

**Objective:** Prove S46-S49 are not just individually green but operationally coherent.

**Files:**

- Regenerate the plan index files via `plans/index_plans.py`
- Regenerate the spec index files via `specs/index_specs.py` only if spec references change
- Add or modify: docs/runbooks produced by Tasks 2 and 5

**Verification commands:**

```bash
uv run python specs/index_specs.py --validate
uv run python plans/index_plans.py --validate
uv run ruff check
uv run pyright
uv run pytest tests/unit -v
uv run pytest tests/integration/test_s13_neo4j_integration.py tests/integration/test_s28_horizontal_scaling.py -v --tb=short
```

If service containers are unavailable locally, record that as a local-environment skip only. CI must not silently pass service startup failures.

## Testing Strategy

Minimum test coverage for this implementation cluster:

- Config unit tests for production safety constraints and redaction.
- Live Neo4j integration tests using real `neo4j` driver sessions.
- Redis integration tests for turn-result store, SSE replay/reconnect, session cache TTL, admin broadcast delivery, and ARQ enqueue/worker execution.
- Request-path isolation tests proving long-running cleanup is queued, not awaited in user-facing routes.
- CI workflow smoke validation for service startup and diagnostics.
- Optional load test for S49 v3 scale target, gated behind an explicit env var if too slow for default CI.

## Risk Controls

- Do not make production correctness depend on Fly sticky sessions. Cross-instance correctness must pass locally with two app objects sharing Redis/PostgreSQL.
- Do not silently downgrade production to in-memory stores. In-memory fallbacks are acceptable for tests/development only.
- Do not let ARQ jobs own irreversible privacy deletion without idempotent checkpoints and audit logging.
- Do not introduce a second queue or scheduler while ARQ is already selected by S48 and present in dependencies.
- Do not add deployment secrets or real connection strings to repository files.
- Do not turn speculative future runtime needs into current implementation work.

## Open Decisions for Implementation

These should be resolved at task start, not by broad architecture redesign:

1. Whether Fly deployment config should be one `fly.toml` with process groups or separate staging/prod files.
2. Whether lifecycle and privacy purge loops should be removed immediately after ARQ lands or kept behind a temporary compatibility flag for one release.
3. Whether admin broadcasts use Redis Pub/Sub only or Redis Streams with replay. Prefer Pub/Sub unless S49 reconnect requirements explicitly need replay for admin events.
4. Whether local load testing lives as pytest, a standalone script, or both. Prefer a script plus one small test assertion to keep CI bounded.

## Implementation Handoff

Recommended subagent split:

- Agent A: S47 live-service CI hardening and fixture diagnostics.
- Agent B: S49 Redis/SSE cross-instance hardening.
- Agent C: S48 ARQ worker and admin enqueue surface.
- Agent D: S46 Fly deployment artifacts and production config validation.

Integration owner must merge in the dependency order above and run the bundle gate after each agent lands. Do not let deployment artifacts merge before S47/S49/S48 runtime tests are green.

## Appendix A: Implementation-Ready Sub-Tasks

Each high-level task above is expanded here into 2-5 minute sub-tasks with exact file paths, code, and verification commands. Implementers should work through these sub-tasks sequentially within each parent task.

---

### A1. S47 Sub-Tasks: Live Service Integration Gates

#### A1.1: Make CI fail loud on service startup failure

**File:** `.github/workflows/ci.yml`

Replace the silent-failure pattern:

```yaml
# BEFORE (line ~45 in integration job):
- run: docker compose -f docker-compose.test.yml up -d --wait || echo "warning: services unavailable"

# AFTER:
- run: docker compose -f docker-compose.test.yml up -d --wait
```

```bash
git add .github/workflows/ci.yml
git commit -m "fix(ci): fail loud on test service startup failure"
```

#### A1.2: Add service diagnostics on failure

**File:** Create `scripts/wait_for_test_services.py`

```python
#!/usr/bin/env python3
"""Wait for test services with diagnostic output on failure."""
import subprocess, sys, time

SERVICES = {
    "postgres": ["pg_isready", "-h", "localhost", "-p", "5432"],
    "redis": ["redis-cli", "-h", "localhost", "-p", "6379", "ping"],
    "neo4j": ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:7474"],
}

TIMEOUT = 60
failed = []
for name, cmd in SERVICES.items():
    start = time.time()
    while time.time() - start < TIMEOUT:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 or (name == "neo4j" and result.stdout.strip() == "200"):
            print(f"  {name}: ready ({time.time() - start:.1f}s)")
            break
        time.sleep(2)
    else:
        print(f"  {name}: FAILED after {TIMEOUT}s")
        failed.append(name)

if failed:
    print(f"\nDiagnostics:", file=sys.stderr)
    subprocess.run(["docker", "compose", "-f", "docker-compose.test.yml", "ps"], check=False)
    subprocess.run(["docker", "compose", "-f", "docker-compose.test.yml", "logs", "--tail=20", "neo4j"], check=False)
    sys.exit(1)
print("All services ready.")
```

```bash
chmod +x scripts/wait_for_test_services.py
uv run python scripts/wait_for_test_services.py
git add scripts/wait_for_test_services.py
git commit -m "feat(s47): add test service readiness script with diagnostics"
```

#### A1.3: Verify Neo4j integration tests pass

```bash
docker compose -f docker-compose.test.yml up -d --wait
uv run pytest tests/integration/test_s13_neo4j_integration.py -v --tb=short
# Expected: all tests pass, Neo4j fixtures load correctly
```

---

### A2. S46+S49 Sub-Tasks: Production Config Validation

#### A2.1: Add production-mode config guard

**File:** `src/tta/config.py`

```python
@field_validator("tta_environment")
@classmethod
def _validate_production_safety(cls, v: str, info: ValidationInfo) -> str:
    if v == "production":
        data = info.data
        if data.get("jwt_secret", "") in ("", "change-me", "dev-secret"):
            raise ValueError("JWT secret must not be default in production")
        if data.get("cors_origins") == ["*"]:
            raise ValueError("CORS origins must be explicit in production")
    return v
```

**TDD:** Write failing test in `tests/unit/test_config.py` first.

```bash
uv run pytest tests/unit/test_config.py::test_production_rejects_default_secrets -v
# Expected: FAIL (test doesn't exist yet)
# Then: implement, verify PASS
git commit -m "feat(s46): add production-mode config safety validation"
```

#### A2.2: Create Fly deployment config

**File:** Create `fly.toml`

```toml
app = "tta-staging"
primary_region = "iad"

[build]
  image = "tta:latest"

[env]
  TTA_ENVIRONMENT = "production"
  PORT = "8000"

[[services]]
  protocol = "tcp"
  internal_port = 8000
  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]
  [services.concurrency]
    type = "connections"
    hard_limit = 25
```

```bash
git add fly.toml
git commit -m "feat(s46): add Fly.io deployment config"
```

---

### A3. S49 Sub-Tasks: Redis-Backed Horizontal Scaling

#### A3.1: Audit in-memory state and enforce Redis backing

**File:** `src/tta/api/app.py`

Ensure lifespan startup wires Redis for turn results:

```python
# In create_app():
turn_result_store = RedisTurnResultStore(redis_client)
app.dependency_overrides[TurnResultStore] = lambda: turn_result_store
```

**TDD:**

```python
# tests/unit/api/test_app.py
def test_default_app_uses_redis_turn_result_store():
    app = create_app(Settings(redis_url="redis://localhost:6379"))
    # Verify TurnResultStore dependency is Redis-backed
```

```bash
uv run pytest tests/unit/api/test_app.py -k "redis_turn_result" -v
git commit -m "feat(s49): enforce Redis-backed turn result store in production"
```

#### A3.2: Add cross-instance SSE reconnect test

**File:** `tests/integration/test_s28_horizontal_scaling.py`

```python
@pytest.mark.spec("AC-49.03")
@pytest.mark.asyncio
async def test_sse_reconnect_across_instances():
    """Two app instances sharing Redis — reconnect from instance B after turn on instance A."""
    app_a = create_app(settings)
    app_b = create_app(settings)  # same Redis, different app object
    # Submit turn on A, reconnect SSE on B with Last-Event-ID
    # Assert turn result streamed from B
```

```bash
uv run pytest tests/integration/test_s28_horizontal_scaling.py::test_sse_reconnect_across_instances -v
git commit -m "test(s49): add cross-instance SSE reconnect test"
```

---

### A4. S48 Sub-Tasks: ARQ Worker Infrastructure

#### A4.1: Create ARQ worker module

**File:** Create `src/tta/jobs/worker.py`

```python
"""ARQ worker with Redis-backed job queue."""
from arq import create_pool
from arq.worker import func
from tta.config import Settings

@func
async def gdpr_delete_player(ctx, player_id: str) -> dict:
    """GDPR-compliant player data deletion."""
    # Pseudocode — bind to actual privacy purge logic
    return {"status": "deleted", "player_id": player_id}

class ArqWorker:
    def __init__(self, settings: Settings):
        self.redis_url = settings.redis_url

    async def start(self):
        self.pool = await create_pool(self.redis_url)
```

**TDD:**

```python
# tests/unit/jobs/test_worker.py
def test_worker_settings_use_configured_redis():
    settings = Settings(redis_url="redis://test:6379")
    worker = ArqWorker(settings)
    assert worker.redis_url == "redis://test:6379"
```

```bash
uv run pytest tests/unit/jobs/test_worker.py -v
git commit -m "feat(s48): add ARQ worker module with GDPR job stub"
```

#### A4.2: Enqueue endpoint

**File:** Modify `src/tta/api/routes/admin_operations.py`

```python
@router.post("/admin/jobs/gdpr-delete/{player_id}")
async def enqueue_gdpr_delete(player_id: str, job_ctx: ArqWorker = Depends()):
    job = await job_ctx.pool.enqueue_job("gdpr_delete_player", player_id)
    return {"job_id": job.job_id}
```

---

### A5. Bundle Gate Sub-Tasks

Run in order after all implementation sub-tasks:

```bash
# 1. Spec/plan validation
uv run python specs/index_specs.py --validate
uv run python plans/index_plans.py --validate

# 2. Code quality
uv run ruff check
uv run pyright

# 3. Unit tests
uv run pytest tests/unit -v

# 4. Integration tests (requires test services)
docker compose -f docker-compose.test.yml up -d --wait
uv run pytest tests/integration/test_s13_neo4j_integration.py tests/integration/test_s28_horizontal_scaling.py -v --tb=short

# 5. Trace
make trace
```
