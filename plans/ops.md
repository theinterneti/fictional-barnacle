# Operations Technical Plan — Deployment, Observability, Testing

> **Phase**: SDD Phase 2 — Component Technical Plan
> **Scope**: DevOps, CI/CD, observability wiring, test infrastructure, database migrations
> **Input specs**: S14 (Deployment), S15 (Observability), S16 (Testing Infrastructure)
> **Parent plan**: `plans/system.md`
> **Status**: 📝 Draft
> **Last Updated**: 2026-04-07

---

## Spec Alignment Notes

This plan implements S14, S15, and S16 subject to system.md overrides:

| Conflict | Resolution |
|----------|------------|
| S14 includes a `tta-worker` container | **Omitted.** System.md §2.2 is authoritative: single process, single container. Turn processing is in-process within `tta-api`. A worker process is a future scaling concern. |
| S16 marks pytest-bdd as out-of-scope | **Overridden.** System.md §1.3 includes pytest-bdd, §7.2 includes `make test-bdd`, and the project charter requires Gherkin ACs. BDD tests are in scope. |
| S15 marks Grafana dashboards as optional | **Included as optional.** Dashboard JSON definitions are provisioned but Grafana is not a required service for v1. |

---

## 1. Docker Configuration

### 1.1 — Dockerfile (Multi-Stage Build)

Two stages: `builder` (install deps) and `runtime` (lean image). Target final image size: < 500 MB.

```dockerfile
# ──────────────────────────────────────────────
# Stage 1: Builder — install dependencies
# ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first (cache-friendly layer ordering)
COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code (separate layer — code changes don't reinstall deps)
COPY src/ src/

# Install the project itself
RUN uv sync --frozen --no-dev

# ──────────────────────────────────────────────
# Stage 2: Runtime — lean image
# ──────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Create non-root user
RUN groupadd --system tta && useradd --system --gid tta tta

WORKDIR /app

# Copy virtual environment and application from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# OCI image labels (overridden at build time via --build-arg)
ARG GIT_SHA="dev"
ARG GIT_TAG="dev"
ARG BUILD_DATE="unknown"
LABEL org.opencontainers.image.version="${GIT_TAG}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="https://github.com/fictional-barnacle/tta"

# Ensure the venv python is on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Run as non-root
USER tta

EXPOSE 8000

# Health check
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import httpx; r = httpx.get('http://localhost:8000/api/v1/health'); r.raise_for_status()"]

ENTRYPOINT ["uvicorn", "tta.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

**Cache behavior**: Changing a file in `src/` reuses the dependency layer. Full rebuild only happens when `pyproject.toml` or `uv.lock` changes.

### 1.2 — docker-compose.yml (Production-Like Stack)

Extends system.md §8 with complete port mapping, health checks, volume definitions, and Langfuse.

```yaml
# docker-compose.yml — production-like service definitions
version: "3.9"

services:
  tta-api:
    build:
      context: .
      args:
        GIT_SHA: "${GIT_SHA:-dev}"
        GIT_TAG: "${GIT_TAG:-dev}"
        BUILD_DATE: "${BUILD_DATE:-unknown}"
    ports:
      - "${TTA_API_PORT:-8000}:8000"
    env_file: .env
    environment:
      TTA_ENV: "${TTA_ENV:-development}"
    depends_on:
      tta-postgres:
        condition: service_healthy
      tta-neo4j:
        condition: service_healthy
      tta-redis:
        condition: service_healthy
    networks:
      - tta-net
    restart: unless-stopped

  tta-postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: "${TTA_DB_POSTGRES_USER:-tta}"
      POSTGRES_PASSWORD: "${TTA_DB_POSTGRES_PASSWORD:-tta}"
      POSTGRES_DB: "${TTA_DB_POSTGRES_DB:-tta}"
    volumes:
      - pg-data:/var/lib/postgresql/data
      - ./docker/postgres/init:/docker-entrypoint-initdb.d:ro
    ports:
      - "${TTA_DB_POSTGRES_PORT:-5432}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${TTA_DB_POSTGRES_USER:-tta}"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
    networks:
      - tta-net

  tta-neo4j:
    image: neo4j:5-community
    environment:
      NEO4J_AUTH: "${TTA_DB_NEO4J_AUTH:-neo4j/password}"
      NEO4J_PLUGINS: '["apoc"]'
    volumes:
      - neo4j-data:/data
    ports:
      - "${TTA_DB_NEO4J_HTTP_PORT:-7474}:7474"
      - "${TTA_DB_NEO4J_BOLT_PORT:-7687}:7687"
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - tta-net

  tta-redis:
    image: redis:7-alpine
    ports:
      - "${TTA_REDIS_PORT:-6379}:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks:
      - tta-net

  tta-langfuse:
    image: langfuse/langfuse:latest
    ports:
      - "${TTA_OBS_LANGFUSE_PORT:-3001}:3000"
    environment:
      DATABASE_URL: "postgresql://${TTA_DB_POSTGRES_USER:-tta}:${TTA_DB_POSTGRES_PASSWORD:-tta}@tta-postgres:5432/langfuse"
      NEXTAUTH_SECRET: "${TTA_OBS_LANGFUSE_NEXTAUTH_SECRET:-dev-secret-change-in-prod}"
      NEXTAUTH_URL: "http://localhost:${TTA_OBS_LANGFUSE_PORT:-3001}"
      SALT: "${TTA_OBS_LANGFUSE_SALT:-dev-salt-change-in-prod}"
    depends_on:
      tta-postgres:
        condition: service_healthy
    networks:
      - tta-net
    restart: unless-stopped

volumes:
  pg-data:
  neo4j-data:

networks:
  tta-net:
    driver: bridge
```

### 1.3 — Postgres Init Script (Langfuse Database)

Langfuse needs its own database on the shared Postgres server. A Docker entrypoint init script handles first-boot creation.

**File**: `docker/postgres/init/01-create-langfuse-db.sql`

```sql
-- Create Langfuse database if it doesn't exist.
-- This script runs ONLY on first Postgres initialization (empty volume).
-- For existing volumes, use `make db-init-langfuse`.
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
```

For existing volumes where the init script won't re-run, `make db-init-langfuse` handles it (see §3).

### 1.4 — docker-compose.override.yml (Development)

Applied automatically by Docker Compose in development. Adds hot reload, debug ports, and source mounts.

```yaml
# docker-compose.override.yml — development overrides
# Applied automatically when running `docker compose up`
services:
  tta-api:
    build:
      target: runtime
    volumes:
      - ./src:/app/src:ro          # Hot reload: source code mount
    entrypoint:
      - uvicorn
      - tta.api.app:create_app
      - --factory
      - --host=0.0.0.0
      - --port=8000
      - --reload                    # Watch for file changes
      - --reload-dir=/app/src
    environment:
      TTA_ENV: development
      TTA_LOG_LEVEL: DEBUG
```

### 1.5 — docker-compose.test.yml (Test Infrastructure)

Standalone test services matching CI service containers, used by `make test-integration` locally.

```yaml
# docker-compose.test.yml — ephemeral test infrastructure
# Usage: docker compose -f docker-compose.test.yml up -d
services:
  test-postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: tta_test
      POSTGRES_PASSWORD: tta_test
      POSTGRES_DB: tta_test
    ports:
      - "5433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tta_test"]
      interval: 3s
      retries: 5
    tmpfs:
      - /var/lib/postgresql/data      # No persistence — fast, disposable

  test-neo4j:
    image: neo4j:5-community
    environment:
      NEO4J_AUTH: none                 # No auth for tests
    ports:
      - "7475:7474"
      - "7688:7687"
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 5s
      retries: 5
      start_period: 20s
    tmpfs:
      - /data                          # No persistence

  test-redis:
    image: redis:7-alpine
    ports:
      - "6380:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 3s
      retries: 5

networks:
  default:
    name: tta-test-net
```

**Port separation**: Test services use offset ports (5433, 7475/7688, 6380) to avoid conflicts with the dev stack.

### 1.6 — Environment Variable Management

**File**: `.env.example` — committed to git, documents all variables.

```bash
# ──────────────────────────────────────────────
# TTA Environment Configuration
# Copy to .env and edit: cp .env.example .env
# ──────────────────────────────────────────────

# ── Application ──────────────────────────────
TTA_ENV=development                    # development | testing | staging
TTA_LOG_LEVEL=INFO                     # DEBUG | INFO | WARNING | ERROR
TTA_API_PORT=8000

# ── PostgreSQL ───────────────────────────────
TTA_DB_POSTGRES_URL=postgresql+asyncpg://tta:tta@localhost:5432/tta
TTA_DB_POSTGRES_USER=tta
TTA_DB_POSTGRES_PASSWORD=tta
TTA_DB_POSTGRES_DB=tta
TTA_DB_POSTGRES_PORT=5432

# ── Neo4j ────────────────────────────────────
TTA_DB_NEO4J_URI=bolt://localhost:7687
TTA_DB_NEO4J_USER=neo4j
TTA_DB_NEO4J_PASSWORD=CHANGE_ME_BEFORE_RUNNING
TTA_DB_NEO4J_AUTH=neo4j/CHANGE_ME_BEFORE_RUNNING
TTA_DB_NEO4J_HTTP_PORT=7474
TTA_DB_NEO4J_BOLT_PORT=7687

# ── Redis ────────────────────────────────────
TTA_REDIS_URL=redis://localhost:6379/0
TTA_REDIS_PORT=6379

# ── LLM ──────────────────────────────────────
TTA_LLM_API_KEY=CHANGE_ME_BEFORE_RUNNING
TTA_LLM_PRIMARY_MODEL=claude-sonnet-4-20250514
TTA_LLM_FALLBACK_MODEL=claude-haiku-4-20250514
TTA_LLM_CLASSIFICATION_MODEL=claude-haiku-4-20250514

# ── Observability ────────────────────────────
TTA_OBS_LANGFUSE_PUBLIC_KEY=            # Empty = Langfuse disabled
TTA_OBS_LANGFUSE_SECRET_KEY=
TTA_OBS_LANGFUSE_HOST=http://localhost:3001
TTA_OBS_LANGFUSE_PORT=3001
TTA_OBS_OTEL_ENDPOINT=http://localhost:4317
TTA_OBS_OTEL_ENABLED=true
TTA_LOG_SENSITIVE=false                 # true = log raw player input (dev only)

# ── Auth (v1: minimal) ──────────────────────
TTA_AUTH_SECRET_KEY=CHANGE_ME_BEFORE_RUNNING

# ── Game ─────────────────────────────────────
TTA_MAX_INPUT_LENGTH=2000
TTA_TURN_RATE_LIMIT=10
TTA_SESSION_TTL_SECONDS=3600

# ── Langfuse Internal ────────────────────────
TTA_OBS_LANGFUSE_NEXTAUTH_SECRET=dev-secret-change-in-prod
TTA_OBS_LANGFUSE_SALT=dev-salt-change-in-prod
```

**Rules**:
- Secrets use `CHANGE_ME_BEFORE_RUNNING` — never a real default value.
- Non-secret defaults are functional for local development.
- `.env` is in `.gitignore`.

---

## 2. CI/CD Pipeline (GitHub Actions)

### 2.1 — Complete Workflow Specification

**File**: `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

env:
  PYTHON_VERSION: "3.12"
  UV_CACHE_DIR: /tmp/uv-cache

jobs:
  # ────────────────────────────────────────────
  # Job 1: Quality Gate (lint, format, typecheck)
  # Runs in parallel as a single job group.
  # ────────────────────────────────────────────
  quality:
    name: Quality Gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python
        run: uv python install ${{ env.PYTHON_VERSION }}

      - name: Install dependencies
        run: uv sync --frozen

      - name: Lint (ruff check)
        run: uv run ruff check src/ tests/

      - name: Format (ruff format)
        run: uv run ruff format --check src/ tests/

      - name: Type check (pyright)
        run: uv run pyright src/

  # ────────────────────────────────────────────
  # Job 2: Unit tests + coverage
  # Runs after quality passes.
  # ────────────────────────────────────────────
  test-unit:
    name: Unit Tests
    runs-on: ubuntu-latest
    needs: quality
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python
        run: uv python install ${{ env.PYTHON_VERSION }}

      - name: Install dependencies
        run: uv sync --frozen

      - name: Run unit tests with coverage
        run: |
          uv run pytest tests/unit/ \
            -m "not integration and not e2e and not llm_live" \
            --cov=src \
            --cov-branch \
            --cov-report=term-missing \
            --cov-report=html:artifacts/coverage \
            --cov-report=xml:artifacts/coverage.xml \
            --junitxml=artifacts/junit-unit.xml \
            -ra --tb=short

      - name: Upload coverage report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: artifacts/coverage/
          retention-days: 14

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: junit-unit
          path: artifacts/junit-unit.xml
          retention-days: 14

  # ────────────────────────────────────────────
  # Job 3: Integration tests (with service containers)
  # Runs after quality passes. Parallel with unit tests.
  # ────────────────────────────────────────────
  test-integration:
    name: Integration Tests
    runs-on: ubuntu-latest
    needs: quality

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: tta_test
          POSTGRES_PASSWORD: tta_test
          POSTGRES_DB: tta_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U tta_test"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5

      neo4j:
        image: neo4j:5-community
        env:
          NEO4J_AUTH: none
        ports:
          - 7687:7687
          - 7474:7474
        options: >-
          --health-cmd "neo4j status || exit 1"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 10
          --health-start-period 30s

      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python
        run: uv python install ${{ env.PYTHON_VERSION }}

      - name: Install dependencies
        run: uv sync --frozen

      - name: Run integration tests
        env:
          TTA_ENV: testing
          TTA_DB_POSTGRES_URL: postgresql+asyncpg://tta_test:tta_test@localhost:5432/tta_test
          TTA_DB_NEO4J_URI: bolt://localhost:7687
          TTA_REDIS_URL: redis://localhost:6379/0
        run: |
          uv run pytest tests/integration/ \
            -m integration \
            --junitxml=artifacts/junit-integration.xml \
            -ra --tb=short

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: junit-integration
          path: artifacts/junit-integration.xml
          retention-days: 14

  # ────────────────────────────────────────────
  # Job 4: BDD tests
  # Runs after quality passes. Parallel with unit/integration.
  # ────────────────────────────────────────────
  test-bdd:
    name: BDD Tests
    runs-on: ubuntu-latest
    needs: quality

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: tta_test
          POSTGRES_PASSWORD: tta_test
          POSTGRES_DB: tta_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U tta_test"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5

      neo4j:
        image: neo4j:5-community
        env:
          NEO4J_AUTH: none
        ports:
          - 7687:7687
        options: >-
          --health-cmd "neo4j status || exit 1"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 10
          --health-start-period 30s

      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python
        run: uv python install ${{ env.PYTHON_VERSION }}

      - name: Install dependencies
        run: uv sync --frozen

      - name: Run BDD tests
        env:
          TTA_ENV: testing
          TTA_DB_POSTGRES_URL: postgresql+asyncpg://tta_test:tta_test@localhost:5432/tta_test
          TTA_DB_NEO4J_URI: bolt://localhost:7687
          TTA_REDIS_URL: redis://localhost:6379/0
        run: |
          uv run pytest tests/bdd/ \
            --junitxml=artifacts/junit-bdd.xml \
            -ra --tb=short

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: junit-bdd
          path: artifacts/junit-bdd.xml
          retention-days: 14

  # ────────────────────────────────────────────
  # Job 5: Docker build
  # Runs after all test jobs pass.
  # ────────────────────────────────────────────
  build:
    name: Docker Build
    runs-on: ubuntu-latest
    needs: [test-unit, test-integration, test-bdd]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build image
        uses: docker/build-push-action@v6
        with:
          context: .
          push: false
          load: true
          tags: tta:${{ github.sha }}
          build-args: |
            GIT_SHA=${{ github.sha }}
            GIT_TAG=${{ github.ref_name }}
            BUILD_DATE=${{ github.event.head_commit.timestamp }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Validate Compose file
        run: docker compose config --quiet

  # ────────────────────────────────────────────
  # Job 6: Push to GHCR (main branch only)
  # ────────────────────────────────────────────
  push:
    name: Push Image
    runs-on: ubuntu-latest
    needs: build
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    permissions:
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            ghcr.io/${{ github.repository }}:${{ github.sha }}
            ghcr.io/${{ github.repository }}:latest
          build-args: |
            GIT_SHA=${{ github.sha }}
            GIT_TAG=${{ github.ref_name }}
            BUILD_DATE=${{ github.event.head_commit.timestamp }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  # ────────────────────────────────────────────
  # Job 7: Conventional commit check
  # Runs on PRs only.
  # ────────────────────────────────────────────
  commit-lint:
    name: Commit Lint
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Check conventional commits
        uses: wagoid/commitlint-github-action@v6
        with:
          configFile: .commitlintrc.yml
```

### 2.2 — CI Job Dependency Graph

```
PR Push / Main Push
  │
  ├── quality (lint + format + typecheck)
  │   │
  │   ├── test-unit ──────────┐
  │   ├── test-integration ───┤── build ── push (main only)
  │   └── test-bdd ───────────┘
  │
  └── commit-lint (PR only, independent)
```

### 2.3 — Caching Strategy

| Cache target | Key | Scope |
|-------------|-----|-------|
| uv packages | `uv.lock` hash | Shared across branches via `setup-uv` |
| Docker layers | `type=gha` (GitHub Actions cache backend) | Shared across workflow runs |
| pytest cache | Not cached in CI — fast enough without it | — |

### 2.4 — Commitlint Configuration

**File**: `.commitlintrc.yml`

```yaml
extends:
  - "@commitlint/config-conventional"
rules:
  type-enum:
    - 2
    - always
    - [feat, fix, refactor, docs, test, chore, ci, perf, style, build, revert]
  subject-case:
    - 2
    - never
    - [upper-case, pascal-case, start-case]
```

---

## 3. Makefile Commands

**File**: `Makefile`

```makefile
.DEFAULT_GOAL := help

# ── Infrastructure ────────────────────────────
.PHONY: up down logs ps

up:                            ## Start the full dev stack (Docker Compose)
	docker compose up -d

down:                          ## Stop the full dev stack
	docker compose down

logs:                          ## Tail logs for all containers
	docker compose logs -f

ps:                            ## Show running container status
	docker compose ps

# ── Development ───────────────────────────────
.PHONY: dev shell

dev:                           ## Run API with hot reload (native, no Docker)
	uv run uvicorn tta.api.app:create_app --factory --reload --reload-dir src --host 0.0.0.0 --port 8000

shell:                         ## Open a shell in the API container
	docker compose exec tta-api bash

# ── Quality ───────────────────────────────────
.PHONY: lint fmt typecheck check

lint:                          ## Run ruff lint + format check
	uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/

fmt:                           ## Auto-format code (ruff)
	uv run ruff check --fix src/ tests/ && uv run ruff format src/ tests/

typecheck:                     ## Run pyright type checker
	uv run pyright src/

check: lint typecheck test     ## Full quality gate (same as CI)

# ── Testing ───────────────────────────────────
.PHONY: test test-unit test-integration test-bdd test-cov

test:                          ## Run all tests
	uv run pytest

test-unit:                     ## Run unit tests only
	uv run pytest tests/unit/ -m "not integration and not e2e"

test-integration: test-infra-up ## Run integration tests (starts test services)
	TTA_ENV=testing \
	TTA_DB_POSTGRES_URL=postgresql+asyncpg://tta_test:tta_test@localhost:5433/tta_test \
	TTA_DB_NEO4J_URI=bolt://localhost:7688 \
	TTA_REDIS_URL=redis://localhost:6380/0 \
	uv run pytest tests/integration/ -m integration

test-bdd: test-infra-up        ## Run BDD (Gherkin) tests
	TTA_ENV=testing \
	TTA_DB_POSTGRES_URL=postgresql+asyncpg://tta_test:tta_test@localhost:5433/tta_test \
	TTA_DB_NEO4J_URI=bolt://localhost:7688 \
	TTA_REDIS_URL=redis://localhost:6380/0 \
	uv run pytest tests/bdd/

test-cov:                      ## Run unit tests with coverage report
	uv run pytest tests/unit/ \
		--cov=src --cov-branch \
		--cov-report=term-missing \
		--cov-report=html:artifacts/coverage

# ── Test Infrastructure ───────────────────────
.PHONY: test-infra-up test-infra-down

test-infra-up:                 ## Start ephemeral test databases
	docker compose -f docker-compose.test.yml up -d --wait

test-infra-down:               ## Stop ephemeral test databases
	docker compose -f docker-compose.test.yml down

# ── Database ──────────────────────────────────
.PHONY: db-migrate db-reset db-seed db-init-langfuse

db-migrate:                    ## Run Alembic migrations (Postgres)
	uv run alembic upgrade head

db-reset:                      ## Destroy all data and recreate databases
	docker compose down -v
	docker compose up -d --wait
	$(MAKE) db-migrate
	$(MAKE) db-seed

db-seed:                       ## Seed development data (player, world)
	uv run python -m tta.persistence.seed

db-init-langfuse:              ## Create Langfuse database (for existing volumes)
	docker compose exec tta-postgres psql -U tta -c "SELECT 1 FROM pg_database WHERE datname = 'langfuse'" | grep -q 1 \
		|| docker compose exec tta-postgres psql -U tta -c "CREATE DATABASE langfuse"

# ── Playtesting ───────────────────────────────
.PHONY: playtest

playtest:                      ## Start interactive playtest session with transcript recording
	uv run python -m tta.playtest

# ── Cleanup ───────────────────────────────────
.PHONY: clean

clean:                         ## Remove build artifacts, caches, coverage reports
	rm -rf artifacts/ .pytest_cache/ .ruff_cache/ htmlcov/ .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ── Help ──────────────────────────────────────
.PHONY: help

help:                          ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'
```

### 3.1 — Target Dependency Graph

```
check ──→ lint ──→ (ruff check, ruff format --check)
      ──→ typecheck ──→ (pyright)
      ──→ test ──→ (pytest all)

test-integration ──→ test-infra-up ──→ (docker-compose.test.yml)
test-bdd ──→ test-infra-up

db-reset ──→ down -v → up → db-migrate → db-seed
```

---

## 4. Observability Wiring

### 4.1 — structlog Configuration

**File**: `src/tta/observability/logging.py`

structlog produces structured JSON to stdout. All log routing is the deployment environment's responsibility.

```python
import logging
import os

import structlog


def configure_logging() -> None:
    """Configure structlog for structured JSON output.

    Call once at application startup (in create_app()).
    """
    log_level = os.getenv("TTA_LOG_LEVEL", "INFO").upper()
    is_dev = os.getenv("TTA_ENV", "development") == "development"

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if is_dev:
        # Human-readable in development
        renderer = structlog.dev.ConsoleRenderer()
    else:
        # JSON in testing/staging
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            foreign_pre_chain=shared_processors,
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level))
```

### 4.2 — Context Binding (Correlation IDs)

Every request binds `trace_id`, `session_id`, `turn_id`, and `player_id` into structlog's context vars. These appear on every log line within that request.

```python
# In FastAPI middleware (src/tta/api/middleware.py)
import structlog
from opentelemetry import trace

@app.middleware("http")
async def bind_log_context(request: Request, call_next):
    span = trace.get_current_span()
    trace_id = format(span.get_span_context().trace_id, "032x") if span else ""

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        trace_id=trace_id,
        request_id=request.headers.get("X-Request-ID", ""),
    )

    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response
```

Session-level and turn-level context is bound deeper in the pipeline:

```python
structlog.contextvars.bind_contextvars(
    session_id=turn_state.session_id,
    turn_id=str(turn_id),
    player_id=pseudonymize(player_id),
)
```

### 4.3 — Log Level Configuration

| Environment | Default level | Override |
|-------------|--------------|---------|
| `development` | `DEBUG` | `TTA_LOG_LEVEL` env var |
| `testing` | `WARNING` | `TTA_LOG_LEVEL` env var |
| `staging` | `INFO` | `TTA_LOG_LEVEL` env var, runtime `POST /admin/log-level` |

Runtime log level change (staging and development only):

```python
@router.post("/admin/log-level")
async def set_log_level(level: str, settings: Settings = Depends(get_settings)):
    if settings.tta_env not in ("development", "staging"):
        raise HTTPException(403, "Log level change not allowed in this environment")
    logging.getLogger().setLevel(getattr(logging, level.upper()))
    return {"log_level": level.upper()}
```

### 4.4 — Logging Privacy Rules

Per S15 §1.3 and §8, the following data MUST NOT appear in application logs:

| Forbidden in logs | What to log instead |
|---|---|
| Raw player input text | Input length, intent classification, or SHA-256 hash |
| Full LLM prompts | Prompt template name and version |
| Full LLM responses | Response length, safety classification |
| API keys / secrets | Never |
| Database connection strings with passwords | Host and port only |
| Player IP addresses | Anonymized region (if needed) |

Exception: `TTA_LOG_SENSITIVE=true` in `development` mode relaxes input/prompt restrictions for debugging. This flag MUST NOT be settable in staging.

### 4.5 — Langfuse Integration

Langfuse is the ONLY system that stores full prompt/completion text. Integration via the Langfuse Python SDK.

```python
# src/tta/observability/langfuse.py
from langfuse import Langfuse

_langfuse: Langfuse | None = None

def init_langfuse() -> Langfuse | None:
    """Initialize Langfuse client. Returns None if keys are not configured."""
    global _langfuse
    pk = os.getenv("TTA_OBS_LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("TTA_OBS_LANGFUSE_SECRET_KEY", "")
    if not pk or not sk:
        logger.warning("langfuse_disabled", reason="Missing public/secret key")
        return None

    _langfuse = Langfuse(
        public_key=pk,
        secret_key=sk,
        host=os.getenv("TTA_OBS_LANGFUSE_HOST", "http://localhost:3001"),
    )
    return _langfuse
```

**Trace hierarchy** (per S15 §4.2):

| Langfuse concept | Maps to |
|---|---|
| Session | Player game session (`session_id`) |
| Trace | Single turn (`turn_id`) |
| Generation | Single LLM call (IPA, WBA, or NGA step within a turn) |

Each LLM call records: prompt template name/version, rendered prompt, model, completion, token counts (prompt + completion), latency (TTFT + total), estimated cost in USD, and the shared `trace_id`.

**Langfuse unavailability**: If Langfuse is unreachable at runtime, LLM calls proceed normally. A throttled warning is logged (once per minute, not per call). Gameplay MUST NOT be affected.

**Privacy / erasure**: Player IDs in Langfuse are pseudonymized hashes. A `make langfuse-purge-player PLAYER_ID=xxx` target (future) provides GDPR erasure.

### 4.6 — OpenTelemetry Setup

OTel provides distributed tracing for non-LLM operations. The OTLP exporter sends to Jaeger (dev) or Grafana Tempo (staging).

```python
# src/tta/observability/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

def init_tracing() -> None:
    """Initialize OpenTelemetry tracing. Degrades silently if endpoint unreachable."""
    enabled = os.getenv("TTA_OBS_OTEL_ENABLED", "true").lower() == "true"
    if not enabled:
        return

    resource = Resource.create({"service.name": "tta-api", "service.version": "v1"})
    provider = TracerProvider(resource=resource)

    endpoint = os.getenv("TTA_OBS_OTEL_ENDPOINT", "http://localhost:4317")
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
```

**Span tree for a turn** (per S15 §3.2):

```
HTTP POST /api/v1/games/{id}/turns
├── input_validation
├── session_load (Redis)
├── turn_pipeline
│   ├── ipa_processing
│   │   └── llm_call [llm.model, llm.tokens.prompt, llm.tokens.completion, llm.cost_usd]
│   ├── wba_processing
│   │   ├── neo4j_query [db.system=neo4j, db.operation=read]
│   │   └── llm_call
│   ├── nga_processing
│   │   └── llm_call
│   └── safety_check
├── session_save (Redis)
└── sse_stream_start
```

**Span attributes**:

| Span type | Required attributes |
|---|---|
| LLM call | `llm.model`, `llm.provider`, `llm.tokens.prompt`, `llm.tokens.completion`, `llm.cost_usd` |
| Database query | `db.system` (`postgres`/`neo4j`/`redis`), `db.operation`, `db.statement` (sanitized) |
| Pipeline stage | `turn.id`, `session.id`, `player.id` (pseudonymized) |

**Degradation**: If the trace backend is unreachable, tracing degrades silently. Application functionality is unaffected. Missing span names default to `unknown`.

### 4.7 — Prometheus Metrics

Metrics exposed via `/metrics` endpoint using `prometheus_client`.

**HTTP metrics**:

| Metric | Type | Labels |
|---|---|---|
| `tta_http_requests_total` | Counter | `method`, `route`, `status` |
| `tta_http_request_duration_seconds` | Histogram | `method`, `route` |
| `tta_http_requests_in_flight` | Gauge | — |

**Turn pipeline metrics**:

| Metric | Type | Labels |
|---|---|---|
| `tta_turn_processing_duration_seconds` | Histogram | `stage` |
| `tta_turn_total` | Counter | `status` (`success`/`failure`) |
| `tta_turn_llm_calls_total` | Counter | `model`, `provider` |
| `tta_turn_llm_duration_seconds` | Histogram | `model` |
| `tta_turn_llm_tokens_total` | Counter | `model`, `direction` (`prompt`/`completion`) |
| `tta_turn_llm_cost_usd` | Histogram | `model` |
| `tta_turn_safety_flags_total` | Counter | `level` |

**Session metrics**:

| Metric | Type | Labels |
|---|---|---|
| `tta_sessions_active` | Gauge | — |
| `tta_session_duration_seconds` | Histogram | — |
| `tta_session_turns_total` | Histogram | — |

**Infrastructure metrics**:

| Metric | Type | Labels |
|---|---|---|
| `tta_db_query_duration_seconds` | Histogram | `database`, `operation` |
| `tta_db_connections_active` | Gauge | `database` |
| `tta_redis_operations_total` | Counter | `operation` |

**Histogram buckets**: `0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0` seconds.

**Low cardinality rule**: Path labels use route patterns (`/api/v1/games/{id}/turns`), never actual IDs. No metric label may have unbounded cardinality.

### 4.8 — Health Endpoints

Two endpoints per S14 §9:

**`GET /api/v1/health`** — Shallow liveness check. Always returns `200 {"status": "ok"}` if the process is alive. No dependency checks.

**`GET /api/v1/health/ready`** — Deep readiness check. Verifies all dependencies.

```python
@router.get("/health")
async def health():
    return {"status": "ok"}

@router.get("/health/ready")
async def health_ready(
    postgres: AsyncSession = Depends(get_db),
    neo4j: AsyncDriver = Depends(get_neo4j),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    checks = {}
    overall = "ok"

    # PostgreSQL: reachable + schema current
    try:
        t0 = time.monotonic()
        await postgres.execute(text("SELECT 1"))
        checks["postgres"] = {"status": "ok", "latency_ms": _elapsed(t0)}
    except Exception as e:
        checks["postgres"] = {"status": "fail", "error": str(e)}
        overall = "fail"  # Critical

    # Neo4j: reachable + constraints exist
    try:
        t0 = time.monotonic()
        async with neo4j.session() as s:
            await s.run("RETURN 1")
        checks["neo4j"] = {"status": "ok", "latency_ms": _elapsed(t0)}
    except Exception as e:
        checks["neo4j"] = {"status": "fail", "error": str(e)}
        overall = "fail"  # Critical

    # Redis: reachable
    try:
        t0 = time.monotonic()
        await redis.ping()
        checks["redis"] = {"status": "ok", "latency_ms": _elapsed(t0)}
    except Exception as e:
        checks["redis"] = {"status": "fail", "error": str(e)}
        if overall != "fail":
            overall = "degraded"  # Non-critical for health, critical for gameplay

    # LLM config: at least one key configured
    llm_configured = bool(settings.llm_api_key)
    checks["llm_config"] = {"status": "ok" if llm_configured else "warn"}

    status_code = 200 if overall == "ok" else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": overall, "checks": checks},
    )
```

**Classification**: Postgres and Neo4j are critical (fail → 503). Redis is critical for gameplay but not for health (fail → `degraded`). LLM config is informational.

### 4.9 — Cost Tracking

LLM cost is calculated per call using configurable model pricing.

**File**: `config/llm_pricing.yml`

```yaml
llm_pricing:
  claude-sonnet-4-20250514:
    prompt_per_1k_tokens: 0.003
    completion_per_1k_tokens: 0.015
  claude-haiku-4-20250514:
    prompt_per_1k_tokens: 0.00025
    completion_per_1k_tokens: 0.00125
  gpt-4o-mini:
    prompt_per_1k_tokens: 0.00015
    completion_per_1k_tokens: 0.0006
```

Cost is recorded to: Prometheus metric (`tta_turn_llm_cost_usd`), Langfuse generation attribute, and OTel span attribute. A daily summary is logged at INFO level at midnight UTC.

---

## 5. Test Infrastructure

### 5.1 — pytest Configuration

**In `pyproject.toml`**:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = [
    "-ra",
    "--strict-markers",
    "--tb=short",
]
filterwarnings = [
    "error",
    "ignore::DeprecationWarning:langfuse.*",
]
markers = [
    "integration: requires external services (Neo4j, Redis, PostgreSQL)",
    "e2e: end-to-end tests requiring full stack",
    "bdd: BDD / Gherkin scenario tests",
    "golden: golden/snapshot comparison tests",
    "flaky: known flaky test (with reruns via pytest-rerunfailures)",
    "llm_live: requires real LLM API key (skipped in CI by default)",
    "slow: takes more than 5 seconds",
    "neo4j: requires Neo4j service",
    "redis: requires Redis service",
]
```

### 5.2 — Coverage Configuration

```toml
[tool.coverage.run]
source = ["src"]
omit = [
    "src/**/migrations/*",
    "src/**/test_*",
    "src/tta/playtest.py",
]
branch = true

[tool.coverage.report]
fail_under = 70              # Global minimum
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    'if __name__ == "__main__"',
    "raise NotImplementedError",
    "\\.\\.\\.",
]
```

**Coverage targets by component** (per S16 §6.2 and system.md §7.2):

| Component path | Target | Rationale |
|---|---|---|
| `src/tta/pipeline/` | ≥ 80% | Game-critical: turn processing |
| `src/tta/safety/` | ≥ 80% | Game-critical: safety hooks |
| `src/tta/llm/` | ≥ 80% | Game-critical: LLM client |
| `src/tta/api/` | ≥ 70% | Platform: API routes, middleware |
| `src/tta/persistence/` | ≥ 60% | Infrastructure: DB repos |
| `src/tta/world/` | ≥ 70% | Platform: world service |
| `src/tta/genesis/` | ≥ 70% | Platform: onboarding flow |
| `src/tta/config.py` | ≥ 60% | Infrastructure: settings |
| `src/tta/observability/` | ≥ 60% | Infrastructure: logging/tracing |

CI enforces the global 70% floor. Per-component targets are documented and enforced via code review until a per-directory coverage tool is configured.

### 5.3 — Test Directory Structure

Mirrors source (per S16 §10.1):

```
tests/
├── conftest.py                  # Shared fixtures, DB setup, environment detection
├── unit/
│   ├── conftest.py              # Unit-specific fixtures (mock_llm, etc.)
│   ├── pipeline/
│   │   ├── test_orchestrator.py
│   │   ├── test_input_understanding.py
│   │   ├── test_context_assembly.py
│   │   ├── test_generation.py
│   │   └── test_delivery.py
│   ├── llm/
│   │   ├── test_client.py
│   │   └── test_roles.py
│   ├── world/
│   │   └── test_service.py
│   ├── models/
│   │   ├── test_turn.py
│   │   └── test_game.py
│   └── safety/
│       └── test_hooks.py
├── integration/
│   ├── conftest.py              # Integration fixtures (real DB connections)
│   ├── test_pipeline_e2e.py
│   ├── test_neo4j.py
│   ├── test_postgres.py
│   └── test_redis_session.py
├── bdd/
│   ├── features/                # .feature files (Gherkin scenarios from specs)
│   │   ├── gameplay_loop.feature
│   │   ├── turn_pipeline.feature
│   │   └── session_management.feature
│   └── step_defs/               # Step implementations
│       ├── conftest.py
│       ├── test_gameplay_steps.py
│       └── test_turn_steps.py
└── fixtures/
    ├── worlds/                  # JSON/Cypher world graphs for tests
    ├── sessions/                # JSON session histories
    └── golden/                  # Golden test snapshot files
```

### 5.4 — Fixture Strategy

**Shared fixtures** (in `tests/conftest.py`):

```python
import pytest
from uuid import uuid4
from datetime import datetime, timezone


# ── Data Factories ─────────────────────────────

def make_player(**overrides) -> dict:
    defaults = {
        "id": f"player_{uuid4().hex[:8]}",
        "handle": f"tester_{uuid4().hex[:6]}",
        "created_at": datetime.now(timezone.utc),
    }
    return {**defaults, **overrides}


def make_session(player_id: str | None = None, **overrides) -> dict:
    defaults = {
        "id": f"sess_{uuid4().hex[:8]}",
        "player_id": player_id or make_player()["id"],
        "status": "active",
        "created_at": datetime.now(timezone.utc),
    }
    return {**defaults, **overrides}


def make_turn(session_id: str | None = None, turn_number: int = 1, **overrides) -> dict:
    defaults = {
        "session_id": session_id or make_session()["id"],
        "turn_number": turn_number,
        "player_input": "look around",
        "status": "processing",
    }
    return {**defaults, **overrides}


# ── pytest Fixtures ────────────────────────────

@pytest.fixture
def player_data():
    """A valid player profile dict."""
    return make_player()


@pytest.fixture
def session_data(player_data):
    """A valid session with linked player."""
    return make_session(player_id=player_data["id"])


@pytest.fixture
def turn_context(session_data):
    """A complete turn processing context."""
    return make_turn(session_id=session_data["id"])
```

**Integration fixtures** (in `tests/integration/conftest.py`):

```python
import os
import pytest
import pytest_asyncio

_SKIP_MSG = "Integration services not available (set TTA_ENV=testing or start test-infra)"


def _services_available() -> bool:
    return os.getenv("TTA_ENV") == "testing" or _can_connect()


def _can_connect() -> bool:
    """Quick check if any integration service is reachable."""
    try:
        import socket
        s = socket.create_connection(("localhost", int(os.getenv("TTA_REDIS_PORT", "6380"))), timeout=1)
        s.close()
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _services_available(),
    reason=_SKIP_MSG,
)


@pytest_asyncio.fixture(scope="module")
async def pg_session():
    """Async Postgres session — creates schema, yields session, cleans up."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    url = os.getenv("TTA_DB_POSTGRES_URL")
    engine = create_async_engine(url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Run migrations or create tables
    async with engine.begin() as conn:
        # Apply schema via Alembic or metadata.create_all
        pass

    async with async_session() as session:
        yield session

    # Teardown: drop test-specific data
    async with engine.begin() as conn:
        pass  # Clean up
    await engine.dispose()


@pytest_asyncio.fixture(scope="module")
async def neo4j_session():
    """Neo4j async session — cleans up after test module."""
    from neo4j import AsyncGraphDatabase

    uri = os.getenv("TTA_DB_NEO4J_URI", "bolt://localhost:7688")
    driver = AsyncGraphDatabase.driver(uri)

    async with driver.session() as session:
        yield session

    # Teardown: clear all test data
    async with driver.session() as session:
        await session.run("MATCH (n) DETACH DELETE n")
    await driver.close()


@pytest_asyncio.fixture
async def redis_client():
    """Redis client for tests — flushes DB after each test."""
    import redis.asyncio as aioredis

    url = os.getenv("TTA_REDIS_URL", "redis://localhost:6380/0")
    client = aioredis.from_url(url)
    yield client
    await client.flushdb()
    await client.aclose()
```

**Fixture scope rules**:
- Database connections: `module` scope (expensive to create).
- Data within databases: cleaned per test function via factory pattern.
- Mocks: `function` scope (fresh for every test).

### 5.5 — MockLLMClient

Deterministic LLM mock for CI. Lives at `src/tta/llm/testing.py`.

```python
from dataclasses import dataclass, field
from typing import AsyncIterator
import math


@dataclass
class RecordedCall:
    role: str
    messages: list[dict]
    params: dict | None
    response: str


class MockLLMClient:
    """Deterministic LLM client for testing.

    Supports fixed responses, pattern matching, error simulation,
    and call recording for assertions.
    """

    def __init__(self):
        self._default_response = "The world is quiet."
        self._patterns: list[tuple[str, str]] = []
        self._errors: dict[int, Exception] = {}      # call_number → error
        self._pattern_errors: list[tuple[str, Exception]] = []
        self._calls: list[RecordedCall] = []
        self._token_overrides: dict[str, int] = {}

    # ── Configuration API ──────────────────────

    def set_default_response(self, text: str) -> "MockLLMClient":
        self._default_response = text
        return self

    def when_prompt_contains(self, pattern: str) -> "_WhenBuilder":
        return _WhenBuilder(self, pattern)

    def when_call_number(self, n: int) -> "_ErrorBuilder":
        return _ErrorBuilder(self, n)

    def set_response(self, text: str, *, token_count: int | None = None) -> None:
        self._default_response = text
        if token_count is not None:
            self._token_overrides[text] = token_count

    # ── LLMClient Protocol ─────────────────────

    async def generate(self, role, messages, params=None) -> str:
        return await self._dispatch(role, messages, params)

    async def stream(self, role, messages, params=None) -> AsyncIterator[str]:
        text = await self._dispatch(role, messages, params)
        for word in text.split():
            yield word + " "

    # ── Assertions ─────────────────────────────

    @property
    def calls(self) -> list[RecordedCall]:
        return list(self._calls)

    @property
    def call_count(self) -> int:
        return len(self._calls)

    def assert_prompt_contains(self, text: str) -> None:
        prompts = [str(c.messages) for c in self._calls]
        assert any(text in p for p in prompts), (
            f"No prompt contained '{text}'. Prompts: {prompts}"
        )

    def estimate_tokens(self, text: str) -> int:
        if text in self._token_overrides:
            return self._token_overrides[text]
        return math.ceil(len(text.split()) * 1.3)

    # ── Internal ───────────────────────────────

    async def _dispatch(self, role, messages, params) -> str:
        call_num = len(self._calls)

        # Check call-number errors
        if call_num in self._errors:
            raise self._errors[call_num]

        prompt_text = str(messages)

        # Check pattern errors
        for pattern, error in self._pattern_errors:
            if pattern in prompt_text:
                raise error

        # Check pattern matches
        for pattern, response in self._patterns:
            if pattern in prompt_text:
                self._calls.append(RecordedCall(str(role), messages, params, response))
                return response

        self._calls.append(
            RecordedCall(str(role), messages, params, self._default_response)
        )
        return self._default_response


@dataclass
class _WhenBuilder:
    _mock: MockLLMClient
    _pattern: str

    def respond(self, text: str) -> MockLLMClient:
        self._mock._patterns.append((self._pattern, text))
        return self._mock

    def raise_error(self, error: Exception) -> MockLLMClient:
        self._mock._pattern_errors.append((self._pattern, error))
        return self._mock


@dataclass
class _ErrorBuilder:
    _mock: MockLLMClient
    _call_number: int

    def raise_error(self, error: Exception) -> MockLLMClient:
        self._mock._errors[self._call_number] = error
        return self._mock
```

**pytest fixture**:

```python
@pytest.fixture
def mock_llm():
    """Pre-configured MockLLMClient for unit tests."""
    return MockLLMClient()
```

### 5.6 — BDD Test Organization (pytest-bdd)

Feature files live in `tests/bdd/features/`. Step definitions in `tests/bdd/step_defs/`.

```gherkin
# tests/bdd/features/turn_pipeline.feature
Feature: Turn Processing Pipeline

  Scenario: Successful turn processing
    Given a player has an active game session
    And the LLM client returns "The forest stirs around you."
    When the player submits "look around"
    Then the turn is processed successfully
    And the narrative output contains "forest"
    And the turn is recorded in the transcript
```

```python
# tests/bdd/step_defs/test_turn_steps.py
from pytest_bdd import scenarios, given, when, then, parsers

scenarios("../features/turn_pipeline.feature")

@given("a player has an active game session")
def active_session(session_data):
    return session_data

@given(parsers.parse('the LLM client returns "{response}"'))
def configure_mock(mock_llm, response):
    mock_llm.set_default_response(response)

@when(parsers.parse('the player submits "{input_text}"'))
def submit_turn(active_session, input_text):
    # Drive turn through pipeline with mock LLM
    pass

@then(parsers.parse('the narrative output contains "{fragment}"'))
def check_narrative(fragment):
    pass
```

### 5.7 — Flaky Test Handling

Uses `pytest-rerunfailures`. A test marked `@pytest.mark.flaky(reruns=2)` retries up to 2 times.

Rules:
- Mark flaky as a temporary measure only. Tests flaky for > 30 days: fix or delete.
- CI logs report how many tests were retried and which ones.
- Tests MUST NOT use `time.sleep()` for synchronization — use proper async waiting.
- Timing-sensitive tests use `freezegun` to control time.

### 5.8 — Golden Tests

Golden tests compare deterministic mock output against approved snapshots in `tests/fixtures/golden/`.

- Mock tests: exact match (deterministic output).
- Live LLM tests (nightly): structural similarity (same schema, similar length ±20%).
- Update snapshots: `uv run pytest -m golden --update-golden`.
- Golden files are tracked in git and reviewed in PRs.

---

## 6. Database Migrations

### 6.1 — PostgreSQL: Alembic

Alembic manages Postgres schema versioning. It integrates naturally with SQLModel/SQLAlchemy.

**Directory**: `src/tta/migrations/`

```
src/tta/migrations/
├── alembic.ini              # Alembic config (or section in pyproject.toml)
├── env.py                   # Migration environment (async engine setup)
├── script.py.mako           # Template for new migration files
└── versions/
    ├── 001_initial_schema.py # Core tables (players, sessions, turns, world_events)
    └── ...
```

**Alembic configuration** (in `pyproject.toml` or standalone `alembic.ini`):

```ini
[alembic]
script_location = src/tta/migrations
sqlalchemy.url = %(TTA_DB_POSTGRES_URL)s

[alembic:exclude]
tables = alembic_version
```

**Workflow**:

| Operation | Command | Notes |
|---|---|---|
| Create migration | `uv run alembic revision --autogenerate -m "description"` | Review auto-generated SQL |
| Apply migrations | `uv run alembic upgrade head` (or `make db-migrate`) | Idempotent — safe to run repeatedly |
| Rollback one step | `uv run alembic downgrade -1` | Test rollback before merging |
| Check current version | `uv run alembic current` | Shows applied migration |
| Show pending | `uv run alembic history --indicate-current` | Diff between code and DB |

**Startup check**: The application verifies at startup that the database schema matches the latest Alembic revision. If the schema is behind, it refuses to start with a clear error:

```
FATAL: Database schema is at revision 001 but code expects 003.
Run `make db-migrate` or `uv run alembic upgrade head` to apply pending migrations.
```

### 6.2 — Neo4j: Versioned Cypher Scripts

Neo4j has no formal migration tool. Use idempotent Cypher scripts applied at startup.

**Directory**: `src/tta/world/schema/`

```
src/tta/world/schema/
├── 001_constraints.cypher
├── 002_indexes.cypher
└── apply.py                 # Script to run all .cypher files in order
```

**Example** (`001_constraints.cypher`):

```cypher
CREATE CONSTRAINT location_id IF NOT EXISTS FOR (l:Location) REQUIRE l.id IS UNIQUE;
CREATE CONSTRAINT npc_id IF NOT EXISTS FOR (n:NPC) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT item_id IF NOT EXISTS FOR (i:Item) REQUIRE i.id IS UNIQUE;
CREATE CONSTRAINT player_session IF NOT EXISTS FOR (p:Player) REQUIRE p.session_id IS UNIQUE;
```

**Example** (`002_indexes.cypher`):

```cypher
CREATE INDEX location_name IF NOT EXISTS FOR (l:Location) ON (l.name);
CREATE INDEX npc_location IF NOT EXISTS FOR ()-[r:IS_AT]-() ON (r.location_id);
```

**Application**: `apply.py` runs scripts in filename order. Each script uses `IF NOT EXISTS` so repeated runs are safe (idempotent). A `_schema_version` node tracks the last applied script number.

```python
async def apply_neo4j_schema(driver: AsyncDriver) -> None:
    """Apply all pending Neo4j schema scripts. Idempotent."""
    schema_dir = Path(__file__).parent
    scripts = sorted(schema_dir.glob("*.cypher"))

    async with driver.session() as session:
        # Get current version
        result = await session.run(
            "MERGE (v:_SchemaVersion {key: 'current'}) RETURN v.version AS version"
        )
        record = await result.single()
        current = record["version"] if record and record["version"] else 0

        for script in scripts:
            version = int(script.stem.split("_")[0])
            if version <= current:
                continue
            cypher = script.read_text()
            for statement in cypher.strip().split(";"):
                stmt = statement.strip()
                if stmt:
                    await session.run(stmt)
            await session.run(
                "MERGE (v:_SchemaVersion {key: 'current'}) SET v.version = $v",
                v=version,
            )
```

### 6.3 — Migration Workflow Summary

| Database | Tool | Migration files | Idempotent | Version tracking |
|---|---|---|---|---|
| PostgreSQL | Alembic | `src/tta/migrations/versions/` | Yes (Alembic handles) | `alembic_version` table |
| Neo4j | Custom Cypher scripts | `src/tta/world/schema/*.cypher` | Yes (`IF NOT EXISTS`) | `_SchemaVersion` node |
| Redis | N/A | N/A (schemaless, ephemeral) | N/A | N/A |

---

## 7. Development Environment Setup

### 7.1 — Prerequisites

| Requirement | Version | Check command |
|---|---|---|
| Python | ≥ 3.12 | `python --version` |
| uv | latest | `uv --version` |
| Docker + Compose | Docker ≥ 24, Compose v2 | `docker compose version` |
| Git | any recent | `git --version` |

### 7.2 — First-Time Setup (Step-by-Step)

```bash
# 1. Clone the repository
git clone https://github.com/fictional-barnacle/tta.git
cd tta

# 2. Set up environment variables
cp .env.example .env
# Edit .env: set TTA_DB_NEO4J_PASSWORD and TTA_LLM_API_KEY at minimum

# 3. Start infrastructure
make up                          # docker compose up -d
# Wait for health checks (~60 seconds for Neo4j)

# 4. Install Python dependencies
uv sync                         # Installs from uv.lock

# 5. Run database migrations
make db-migrate                  # Alembic migrations for Postgres
# Neo4j schema is applied automatically on first API startup

# 6. (Optional) Seed development data
make db-seed                     # Creates test player + sample world

# 7. Start the API in development mode
make dev                         # uvicorn with --reload

# 8. Verify
curl http://localhost:8000/api/v1/health
# Expected: {"status": "ok"}

curl http://localhost:8000/api/v1/health/ready
# Expected: {"status": "ok", "checks": {...}}
```

**Target**: Clone to running system in under 10 minutes.

### 7.3 — Native Python (Without Docker for App)

For developers who prefer running the Python app natively while using Docker for databases only:

```bash
make up                          # Start Postgres, Neo4j, Redis via Docker
uv sync                         # Install Python deps
make dev                         # Run uvicorn natively with hot reload
```

This is the recommended workflow. The `tta-api` container is only needed for staging-like testing.

### 7.4 — IDE Configuration (VS Code)

Recommended extensions:

| Extension | Purpose |
|---|---|
| `ms-python.python` | Python language support |
| `ms-python.vscode-pylance` | Pyright-based type checking |
| `charliermarsh.ruff` | Ruff linting + formatting |
| `ms-python.debugpy` | Python debugging |

**Recommended settings** (`.vscode/settings.json`):

```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  },
  "python.analysis.typeCheckingMode": "standard",
  "ruff.lineLength": 88
}
```

### 7.5 — Pre-Commit Hooks (Recommended)

Optional but recommended for catching issues before push.

**File**: `.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/RobertCraiwordie/pyright-python
    rev: v1.1.390
    hooks:
      - id: pyright
        args: [src/]
```

Install: `uv run pre-commit install`.

---

## 8. Monitoring and Alerting (v1)

### 8.1 — What to Monitor

v1 monitoring is simple but sufficient. No PagerDuty, no on-call rotation.

| What | How | Where to see it |
|---|---|---|
| Request rate + error rate | Prometheus metrics | `/metrics` endpoint (or Grafana if enabled) |
| Turn latency by pipeline stage | Prometheus histogram | `/metrics` |
| LLM cost per day | Daily log summary + Langfuse | Application logs + Langfuse UI |
| Active sessions | Prometheus gauge | `/metrics` |
| Container health | Docker health checks | `docker compose ps` |
| Database reachability | `/health/ready` endpoint | curl or monitoring script |
| Full LLM call details | Langfuse traces | Langfuse web UI (port 3001) |

### 8.2 — Log Aggregation (v1)

stdout + `docker compose logs`. No ELK, no Loki for v1.

```bash
# Tail all logs
make logs

# Filter by component
docker compose logs tta-api -f

# Search logs (JSON, so grep works)
docker compose logs tta-api 2>&1 | grep '"level":"error"'
docker compose logs tta-api 2>&1 | grep '"session_id":"sess_abc"'
```

### 8.3 — Alert Conditions

Per S15 §5, the following conditions generate log-based alerts:

| Condition | Severity | Detection |
|---|---|---|
| API error rate > 10% over 5 minutes | Critical | Prometheus alerting rule (if Grafana) or log pattern |
| LLM API unreachable for > 2 minutes | Critical | Failed LLM call counter |
| Turn processing > 30s (p95) | Warning | Prometheus histogram |
| Daily LLM cost exceeds threshold | Warning | Daily cost log summary |
| Database connection pool exhausted | Critical | `tta_db_connections_active` gauge |
| Disk usage > 80% | Warning | Host-level monitoring (out of TTA scope) |

**Alert idempotency**: The same condition does not fire more than once per 15 minutes. Thresholds are configurable via environment variables (`TTA_ALERT_ERROR_RATE_THRESHOLD`, etc.).

### 8.4 — Grafana Dashboards (Optional)

If Grafana is included in the stack (optional for v1), pre-built dashboard JSON is provisioned automatically via Grafana provisioning.

Three dashboards:

1. **System Health**: Request rate, error rate, p50/p95/p99 latency, active sessions, container health.
2. **Turn Pipeline**: Turn processing time by stage, LLM latency by model, token usage, safety flags.
3. **Cost**: LLM cost per hour/day, cost per model, cost per turn, projected monthly cost.

Dashboard definitions live in `monitoring/grafana/dashboards/` and are mounted into Grafana's provisioning directory.

---

## Appendix A: Observability Data Flow

```
TTA Application
  │
  ├── structlog → stdout (JSON) → docker compose logs
  │
  ├── prometheus_client → /metrics → Prometheus (scrape) → Grafana (optional)
  │
  ├── OpenTelemetry SDK → OTLP exporter → Jaeger (dev) / Tempo (staging)
  │
  └── Langfuse SDK → Langfuse server → Langfuse DB (Postgres)
```

## Appendix B: Sensitive Data Classification

| Data | Logs | Metrics | Traces (OTel) | Langfuse |
|---|---|---|---|---|
| Player input text | ❌ (hash only) | ❌ | ❌ | ✅ (with consent) |
| LLM prompt (full) | ❌ | ❌ | ❌ | ✅ (with consent) |
| LLM response (full) | ❌ | ❌ | ❌ | ✅ (with consent) |
| Token counts | ✅ | ✅ | ✅ | ✅ |
| Model name | ✅ | ✅ | ✅ | ✅ |
| Cost (USD) | ✅ | ✅ | ✅ | ✅ |
| Player ID (pseudonymized) | ✅ | ❌ | ✅ | ✅ |
| Session ID | ✅ | ❌ | ✅ | ✅ |
| API keys | ❌ | ❌ | ❌ | ❌ |
| DB passwords | ❌ | ❌ | ❌ | ❌ |

## Appendix C: Complete File Inventory

Files this plan introduces or modifies:

| File | Purpose | New/Modified |
|---|---|---|
| `Dockerfile` | Multi-stage build | New |
| `docker-compose.yml` | Production-like stack | New |
| `docker-compose.override.yml` | Dev overrides (hot reload) | New |
| `docker-compose.test.yml` | Ephemeral test infrastructure | New |
| `docker/postgres/init/01-create-langfuse-db.sql` | Langfuse DB init | New |
| `.env.example` | Environment variable documentation | New |
| `.github/workflows/ci.yml` | CI/CD pipeline | New |
| `.commitlintrc.yml` | Conventional commit config | New |
| `Makefile` | Developer commands | New |
| `.pre-commit-config.yaml` | Pre-commit hooks (optional) | New |
| `.vscode/settings.json` | IDE settings (recommended) | New |
| `config/llm_pricing.yml` | LLM cost configuration | New |
| `src/tta/observability/logging.py` | structlog configuration | New |
| `src/tta/observability/tracing.py` | OpenTelemetry setup | New |
| `src/tta/observability/langfuse.py` | Langfuse integration | New |
| `src/tta/llm/testing.py` | MockLLMClient | New |
| `src/tta/migrations/` | Alembic migration directory | New |
| `src/tta/world/schema/` | Neo4j Cypher migration scripts | New |
| `tests/conftest.py` | Shared test fixtures | New |
| `tests/integration/conftest.py` | Integration fixtures | New |
| `tests/bdd/features/` | Gherkin feature files | New |
| `tests/bdd/step_defs/` | BDD step implementations | New |
| `tests/fixtures/` | Test data (worlds, sessions, golden) | New |
| `monitoring/grafana/dashboards/` | Dashboard JSON (optional) | New |
| `pyproject.toml` | pytest + coverage config sections | Modified |
