# S14 — Deployment & Infrastructure

> **Status**: 📝 Draft
> **Level**: 4 — Operations
> **Dependencies**: S01 (Gameplay Loop), S08 (Turn Pipeline), S10 (API)
> **Last Updated**: 2026-04-07

## Overview

This spec defines how TTA is built, packaged, deployed, and run. The v1 deployment target is **Docker Compose on a single host**. There is no orchestrator (no Kubernetes, no ECS). The system must be runnable by a single developer on a laptop and deployable to a single VPS or cloud VM.

This spec describes behavior: what a developer or operator does, and what the system does in response. Implementation choices (which base image, which CI provider) are suggestions, not mandates.

### Out of Scope

- **Kubernetes / container orchestration** — v1 is single-host Docker Compose only — revisit when scaling beyond one VM (§10)
- **Blue-green / canary deployments** — staging is the only deployment target in v1 — future ops maturity
- **Secrets management (Vault, SOPS)** — `.env` files suffice for v1 — future security hardening
- **CDN / edge caching** — no static frontend assets served by TTA in v1 — frontend spec (future)
- **Multi-region / multi-cloud deployment** — single-host constraint makes this irrelevant — §10 (future)
- **Bare-metal production** — documented for local dev (FR-14.28) but not a supported deployment target

---

## 1. Container Architecture

### 1.1 User Stories

- **US-14.1**: As a developer, I can run `docker compose up` and have a fully functional TTA instance running locally within 3 minutes.
- **US-14.2**: As an operator, I can see which containers are running and their health status via `docker compose ps`.
- **US-14.3**: As a developer, I can rebuild a single service without restarting the entire stack.

### 1.2 Functional Requirements

**FR-14.1**: The system SHALL consist of the following containers:

| Container | Purpose | Exposes |
|-----------|---------|---------|
| `tta-api` | FastAPI application server — handles HTTP/SSE | Port 8000 |
| `tta-worker` | Background task worker (turn processing, async jobs) | No external port |

> **Note**: `tta-worker` is deferred to post-v1 per system.md §2.2. V1 runs as a single container.
| `tta-neo4j` | Neo4j graph database (world state, narrative graph) | Ports 7474 (browser), 7687 (bolt) |
| `tta-redis` | Redis (session cache, pub/sub, task queue) | Port 6379 |
| `tta-postgres` | PostgreSQL (player accounts, system config, audit log) | Port 5432 |

**FR-14.2**: The `tta-api` and `tta-worker` containers SHALL be built from the same codebase and image, differentiated only by the entrypoint command.

**FR-14.3**: All containers SHALL be connected via a single Docker network (`tta-net`). No container SHALL expose ports to the host except those explicitly listed above. In production-like deployments, only `tta-api` port 8000 needs host exposure.

**FR-14.4**: Data stores (Neo4j, Redis, PostgreSQL) SHALL use named Docker volumes for persistence. Removing containers SHALL NOT destroy data. Only `docker compose down -v` destroys volumes.

### 1.3 Edge Cases

- **EC-14.1**: If Neo4j takes longer than 30 seconds to start, dependent containers must wait (health check dependency, not sleep).
- **EC-14.2**: If Redis is unavailable at API startup, the API SHALL start in degraded mode (no sessions, returns 503 for game endpoints) rather than crash.

### 1.4 Acceptance Criteria

- [ ] `docker compose up -d` starts all 5 containers and they reach "healthy" within 120 seconds.
- [ ] `docker compose down` stops all containers. `docker compose up -d` restarts with data intact.
- [ ] `docker compose down -v` destroys all data. Subsequent `up` starts fresh.
- [ ] Rebuilding `tta-api` (`docker compose build tta-api`) does not affect data store containers.

---

## 2. Docker Compose Configuration

### 2.1 User Stories

- **US-14.4**: As a developer, I can run TTA with a single `docker compose up` command with no prior setup beyond cloning the repo and having Docker installed.
- **US-14.5**: As a developer, I can override any configuration value via a `.env` file without modifying `docker-compose.yml`.

### 2.2 Functional Requirements

**FR-14.5**: The project SHALL include a `docker-compose.yml` at the repository root that defines the full stack.

**FR-14.6**: The project SHALL include a `docker-compose.override.yml` for development-specific settings (volume mounts for hot reload, debug ports, verbose logging).

**FR-14.7**: A `.env.example` file SHALL document every required and optional environment variable with safe default values. Copying `.env.example` to `.env` SHALL be sufficient to run the system locally.

**FR-14.8**: The Compose file SHALL define health checks for every container:

| Container | Health Check |
|-----------|-------------|
| `tta-api` | `GET /api/v1/health` returns 200 or 503 per S23 health semantics |
| `tta-worker` | Process is alive and task queue is reachable |
| `tta-neo4j` | Cypher query `RETURN 1` succeeds |
| `tta-redis` | `PING` returns `PONG` |
| `tta-postgres` | `pg_isready` succeeds |

**FR-14.9**: Container startup order SHALL be enforced via `depends_on` with `condition: service_healthy`. The order is: data stores first → worker → API.

### 2.3 Acceptance Criteria

- [ ] A fresh clone + `cp .env.example .env && docker compose up -d` results in a working system.
- [ ] Every environment variable in `docker-compose.yml` has a corresponding entry in `.env.example`.
- [ ] Health checks are defined for all containers and `docker compose ps` shows "healthy" for each.

---

## 3. Environment Configuration

### 3.1 User Stories

- **US-14.6**: As a developer, I can configure LLM API keys without committing them to the repository.
- **US-14.7**: As an operator, I can change the log level or database URL without rebuilding containers.

### 3.2 Functional Requirements

**FR-14.10**: Environment variables SHALL be grouped by category:

| Category | Prefix | Examples |
|----------|--------|----------|
| Application | `TTA_` | `TTA_LOG_LEVEL`, `TTA_DEBUG` |
| Database | `TTA_DB_` | `TTA_DB_POSTGRES_URL`, `TTA_DB_NEO4J_URI` |
| Redis | `TTA_REDIS_` | `TTA_REDIS_URL` |
| LLM | `TTA_LLM_` | `TTA_LLM_API_KEY`, `TTA_LLM_MODEL`, `TTA_LLM_BASE_URL` |
| Observability | `TTA_OBS_` | `TTA_OBS_LANGFUSE_PUBLIC_KEY`, `TTA_OBS_OTEL_ENDPOINT` |
| Auth | `TTA_AUTH_` | `TTA_AUTH_SECRET_KEY`, `TTA_AUTH_TOKEN_EXPIRY` |

**FR-14.11**: The application SHALL validate all required environment variables at startup and fail fast with a clear error message listing every missing variable (not one at a time).

**FR-14.12**: Secrets (API keys, database passwords, auth keys) SHALL NOT have default values in `.env.example`. They SHALL be marked with placeholder text like `CHANGE_ME_BEFORE_RUNNING`.

**FR-14.13**: The application SHALL support a `TTA_ENV` variable with values: `development`, `testing`, `staging`. Behavior differences:

| Setting | development | testing | staging |
|---------|-------------|---------|---------|
| Debug mode | On | Off | Off |
| Log level | DEBUG | WARNING | INFO |
| LLM calls | Real (if key set) | Mocked | Real |
| CORS origins | `*` | N/A | Configured list |

### 3.3 Edge Cases

- **EC-14.3**: If `TTA_LLM_API_KEY` is unset in development mode, the system SHALL start but return a clear error on any LLM-dependent endpoint.
- **EC-14.4**: If a database URL is malformed, the startup error SHALL identify which URL is malformed and what format is expected.

### 3.4 Acceptance Criteria

- [ ] Starting the app with missing required env vars fails with a single error listing all missing vars.
- [ ] `.env.example` contains no real secrets, only placeholders.
- [ ] Changing `TTA_LOG_LEVEL` in `.env` and restarting changes log verbosity without rebuild.

---

## 4. Build Pipeline

### 4.1 User Stories

- **US-14.8**: As a developer, I can build the application image locally with a single command.
- **US-14.9**: As CI, I can build a deterministic, reproducible image from any commit.

### 4.2 Functional Requirements

**FR-14.14**: The Dockerfile SHALL use a multi-stage build:
1. **Stage 1 (builder)**: Install dependencies via `uv`, compile any native extensions.
2. **Stage 2 (runtime)**: Copy only the virtual environment and application code. No build tools in the final image.

**FR-14.15**: The final image SHALL be based on a slim Python 3.12+ base image. Image size SHOULD be under 500MB.

**FR-14.16**: The image SHALL include a non-root user (`tta`) that the application runs as.

**FR-14.17**: The build SHALL be cache-friendly: dependency installation (from `pyproject.toml` + `uv.lock`) SHALL be a separate layer from application code copying. Changing application code SHALL NOT trigger a full dependency reinstall.

**FR-14.18**: The image SHALL embed version metadata as labels:
- `org.opencontainers.image.version` — git tag or `dev`
- `org.opencontainers.image.revision` — git commit SHA
- `org.opencontainers.image.created` — build timestamp

### 4.3 Acceptance Criteria

- [ ] `docker build -t tta .` succeeds from the repo root.
- [ ] The built image runs as a non-root user.
- [ ] Changing only a Python source file and rebuilding reuses the dependency layer (build completes in < 30 seconds).
- [ ] `docker inspect tta` shows version/revision labels.

---

## 5. CI/CD Pipeline

### 5.1 User Stories

- **US-14.10**: As a developer, I get feedback on my PR within 10 minutes.
- **US-14.11**: As a maintainer, merging to `main` automatically builds and tags a release image.

### 5.2 Functional Requirements

**FR-14.19**: On every pull request, CI SHALL run the following checks in order:

| Step | Tool | Fail condition |
|------|------|----------------|
| Lint | `ruff check` | Any error |
| Format | `ruff format --check` | Any file unformatted |
| Type check | `pyright` | Any error |
| Unit tests | `pytest -m "not integration and not e2e"` | Any failure or coverage < threshold |
| Integration tests | `pytest -m integration` | Any failure |
| Build | `docker build` | Build failure |

**FR-14.20**: On merge to `main`, CI SHALL additionally:
1. Build the Docker image with version labels.
2. Tag the image with the commit SHA and `latest`.
3. Push the image to the configured container registry (GitHub Container Registry for OSS).

**FR-14.21**: CI SHALL cache the following between runs:
- `uv` dependency cache (keyed on `uv.lock` hash)
- Docker layer cache
- pytest cache (`.pytest_cache`)

**FR-14.22**: CI SHALL run integration tests that require Neo4j and Redis using Docker service containers within the CI environment.

### 5.3 Edge Cases

- **EC-14.5**: If integration test infrastructure (Neo4j service container) fails to start, those tests SHALL be marked as infrastructure failures, not test failures.
- **EC-14.6**: If the container registry is unreachable on merge to main, the pipeline SHALL retry 3 times before failing.

### 5.4 Acceptance Criteria

- [ ] A PR with a ruff error fails CI before tests run.
- [ ] A PR with all checks passing shows a green status.
- [ ] Merging to `main` produces a tagged image in the container registry.
- [ ] CI completes in under 10 minutes for a typical PR.

---

## 6. Environments

### 6.1 Functional Requirements

**FR-14.23**: The project SHALL support three environments:

| Environment | Purpose | LLM calls | Infra |
|-------------|---------|-----------|-------|
| `development` | Local developer workstation | Optional (real or mocked) | Docker Compose |
| `testing` | CI pipeline | Mocked (deterministic) | Service containers |
| `staging` | Pre-release validation | Real | Docker Compose on VM |

**FR-14.24**: There SHALL NOT be a "production" environment in v1. Staging IS the deployment target. The spec acknowledges this is not production-grade and does not pretend otherwise.

**FR-14.25**: Each environment SHALL have its own `.env` template (`.env.example` for dev, `.env.ci` for testing, `.env.staging` for staging).

### 6.2 Acceptance Criteria

- [ ] The development environment runs entirely on a developer laptop with Docker.
- [ ] The testing environment runs in CI with no external service dependencies.
- [ ] The staging environment is documented with a deployment runbook.

---

## 7. Local Development

### 7.1 User Stories

- **US-14.12**: As a new contributor, I can go from `git clone` to a running system in under 10 minutes following the README.
- **US-14.13**: As a developer, I can edit Python code and see changes reflected without restarting containers.
- **US-14.14**: As a developer, I can run tests locally against the same infrastructure the CI uses.

### 7.2 Functional Requirements

**FR-14.26**: The development `docker-compose.override.yml` SHALL mount the source code directory into the `tta-api` and `tta-worker` containers, enabling hot reload via `uvicorn --reload` or equivalent.

**FR-14.27**: The project SHALL include a `Makefile` (or `justfile`) with at least these targets:

| Target | Action |
|--------|--------|
| `make up` | Start the full stack |
| `make down` | Stop the full stack |
| `make test` | Run the full test suite locally |
| `make test-unit` | Run unit tests only |
| `make lint` | Run ruff check + format check + pyright |
| `make fmt` | Auto-format code |
| `make logs` | Tail logs for all containers |
| `make shell` | Open a shell in the API container |
| `make db-reset` | Reset all databases to a clean state |

**FR-14.28**: The project SHALL support running without Docker for developers who prefer native Python. This means `uv run` for the API and local installs of Neo4j/Redis/PostgreSQL. This path is documented but not the primary recommendation.

### 7.3 Acceptance Criteria

- [ ] A new developer can follow the README and have TTA running within 10 minutes.
- [ ] Editing a Python file in `src/` is reflected in the running API within 5 seconds.
- [ ] `make test` runs the same tests that CI runs.

---

## 8. Database Provisioning

### 8.1 Functional Requirements

**FR-14.29**: On first start, the system SHALL automatically:
1. Run PostgreSQL migrations to create the schema.
2. Apply Neo4j constraints and indexes.
3. Verify Redis connectivity.

**FR-14.30**: Migrations SHALL be idempotent. Running them against an already-migrated database SHALL be a no-op.

**FR-14.31**: The system SHALL include a seed data mechanism for development:
- A default world graph in Neo4j.
- A test player account in PostgreSQL.
- This seed data SHALL NOT run in staging unless explicitly invoked.

**FR-14.32**: Database schema versions SHALL be tracked. The application SHALL refuse to start if the database schema is older than what the code expects, with a clear error message directing the operator to run migrations.

### 8.2 Edge Cases

- **EC-14.7**: If Neo4j is empty (first run), the system SHALL create the base schema and optionally seed data. It SHALL NOT fail silently and serve empty responses.
- **EC-14.8**: If a migration fails halfway, the system SHALL report which migration failed and leave the database in a state that allows re-running the migration after fixing the issue.

### 8.3 Acceptance Criteria

- [ ] First `docker compose up` creates all database schemas automatically.
- [ ] Subsequent `docker compose up` after a code update applies pending migrations.
- [ ] `make db-reset` destroys and recreates all databases from scratch.
- [ ] Running migrations twice is idempotent.

---

## 9. Health Checks

### 9.1 Functional Requirements

**FR-14.33**: The API SHALL expose the following health endpoints:

| Endpoint | Purpose | Response |
|----------|---------|----------|
| `GET /api/v1/health` | Health check (tri-state) | `200` or `503` with status/checks/version (per S23 FR-23.23/24) |
| `GET /api/v1/health/ready` | Deep readiness check (all dependencies) | `200` or `503` with details |

**FR-14.34**: The readiness check SHALL verify:
- PostgreSQL is reachable and schema is current.
- Neo4j is reachable and constraints exist.
- Redis is reachable.
- At least one LLM provider is configured (key present, not necessarily reachable).

**FR-14.35**: The readiness check SHALL return a JSON body listing each dependency and
its status:

```json
{
  "status": "not_ready",
  "checks": {
    "postgres": "ok",
    "neo4j": "ok",
    "redis": "unavailable",
    "llm": "ok"
  }
}
```

**FR-14.36**: The readiness status SHALL be `ready` when all required checks are
available. Otherwise it SHALL be `not_ready` and the endpoint SHALL return HTTP 503.

### 9.2 Acceptance Criteria

- [ ] `GET /api/v1/health` returns 200 with status `degraded` when Neo4j is temporarily slow.
- [ ] `GET /api/v1/health/ready` returns 503 when PostgreSQL is down.
- [ ] `GET /api/v1/health/ready` returns 503 with status `not_ready` when Redis is down but PostgreSQL and Neo4j are up.
- [ ] Health check response includes latency for each dependency.

---

## 10. Scaling Considerations (Future)

### 10.1 Discussion

This section documents what would need to change to support more than a handful of concurrent users. None of this is in scope for v1.

**FR-14.37 (FUTURE)**: To scale beyond a single host:
- The `tta-api` container is stateless and can be horizontally scaled behind a load balancer.
- The `tta-worker` container can be scaled to multiple instances with Redis as the task queue broker.
- Neo4j would need to move to a cluster or managed service (Aura).
- PostgreSQL would need connection pooling (PgBouncer) and possibly read replicas.
- Redis would need to move to a cluster or managed service (ElastiCache, Upstash).

**FR-14.38 (FUTURE)**: Session affinity is NOT required. All session state lives in Redis, so any API instance can serve any player.

**FR-14.39 (FUTURE)**: LLM API rate limits may require request queuing or multiple API keys. This is the most likely scaling bottleneck before infrastructure becomes the issue.

### 10.2 Acceptance Criteria (Future)

- [ ] Documentation exists describing the path from single-host to multi-host deployment.
- [ ] No application code assumes a single API instance (no in-memory session state, no local file storage for game data).

---

## Key Scenarios (Gherkin)

```gherkin
Scenario: Fresh stack starts from clone
  Given a fresh clone of the repository
  And Docker is installed
  And the developer runs "cp .env.example .env"
  When the developer runs "docker compose up -d"
  Then all 5 containers reach "healthy" status within 120 seconds
  And "GET /api/v1/health" returns 200 with status "healthy"

Scenario: Stack restart preserves data
  Given the full stack is running with player data in PostgreSQL and Neo4j
  When the operator runs "docker compose down"
  And the operator runs "docker compose up -d"
  Then all previously stored player data is still present
  And no data migration errors are logged

Scenario: Missing required env var fails fast
  Given the .env file is missing TTA_DB_POSTGRES_URL and TTA_LLM_API_KEY
  When the application starts
  Then it exits with a non-zero status within 5 seconds
  And the error message lists both TTA_DB_POSTGRES_URL and TTA_LLM_API_KEY as missing

Scenario: Health readiness degrades when Redis is down
  Given the full stack is running and healthy
  When Redis becomes unreachable
  Then "GET /api/v1/health" still returns 200 with status "degraded"
  And "GET /api/v1/health/ready" returns 503 with status "not_ready"
  And the response body shows redis status as "fail"
  And postgres and neo4j statuses remain "ok"
```

---

## Appendix A: Container Dependency Graph

```
tta-postgres ──┐
tta-neo4j   ───┤── tta-worker ── tta-api
tta-redis   ───┘
```

## Appendix B: Port Map

| Service | Internal Port | Host Port (dev) | Host Port (staging) |
|---------|--------------|-----------------|---------------------|
| API | 8000 | 8000 | 8000 |
| Neo4j Browser | 7474 | 7474 | Not exposed |
| Neo4j Bolt | 7687 | 7687 | 7687 |
| Redis | 6379 | 6379 | Not exposed |
| PostgreSQL | 5432 | 5432 | Not exposed |

## Appendix C: Makefile Quick Reference

```makefile
.PHONY: up down test lint fmt logs shell db-reset

up:
	docker compose up -d

down:
	docker compose down

test:
	uv run pytest

test-unit:
	uv run pytest -m "not integration and not e2e"

lint:
	uv run ruff check src/ && uv run ruff format --check src/ && uv run pyright src/

fmt:
	uv run ruff check --fix src/ && uv run ruff format src/

logs:
	docker compose logs -f

shell:
	docker compose exec tta-api bash

db-reset:
	docker compose down -v && docker compose up -d
```
