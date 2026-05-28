# S46 — Cloud Deployment Target

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v3
> **Implementation Fit**: ❌ Not Started
> **Level**: 4 — Operations
> **Dependencies**: v1 S14 (Deployment — local Docker Compose)
> **Related**: S49 (Horizontal Scaling), v1 S15 (Observability)
> **Last Updated**: 2026-05-28

---

## 1. Purpose

S14 defined Docker Compose on a single host as the v1 deployment target. S46
extends TTA to a cloud-hosted production deployment. At v3 release, S46
supersedes S14's role in the *live system*. S14 remains closed and unchanged;
Docker Compose continues to be the canonical local development environment.

This spec answers:
- Which cloud platform hosts production and staging?
- How are the three data stores (PostgreSQL, Neo4j, Redis) provisioned?
- How are secrets managed across environments?
- What is the zero-downtime deploy procedure?
- How is environment parity enforced across dev, staging, and prod?

---

## 2. User Stories

- **As an** operator, **I want** staging and production to run the same Docker image as local development, **so that** environment differences do not hide deployment defects.
- **As a** developer, **I want** production deploys to be gated by health checks and secret parity, **so that** a bad release fails before it can corrupt live play.
- **As a** playtester, **I want** the hosted game to stay available during deploys, **so that** long-running sessions are not interrupted by routine releases.
- **As an** operator, **I want** backups and restore drills documented for every persistent store, **so that** production data loss has a practiced recovery path.

## 3. Design Decisions

### 3.1 Cloud Platform: Fly.io

**Decision**: TTA deploys to **Fly.io** at v3.

Rationale:
- Native Docker image deployment (same image as local S14 dev)
- Fly Postgres (managed PostgreSQL) is directly integrated
- Fly Volumes support Neo4j and Redis persistence without a third-party service
- Fly Machines API supports rolling deploys with zero-downtime
- Free tier sufficient for staging; pay-as-you-go for production
- No Kubernetes complexity; matches the single-process-per-instance mandate

Alternatives considered:
- **Cloud Run**: Stateless containers only; Neo4j volume persistence is awkward.
- **Railway**: Suitable, but less control over machine sizing and roll-out.
- **VPS (Hetzner/DO)**: Requires manual ops for rolling deploys and certs.

### 3.2 Data Store Provisioning

| Store | Provisioning | Notes |
|---|---|---|
| PostgreSQL | Fly Postgres cluster (1 primary, v3 stage) | Managed backups, HA at v4 if needed |
| Neo4j | Fly Machine + persistent Volume (`/data`) | CE 5.x Docker image |
| Redis | Fly Machine + persistent Volume (`/data`) | Redis 7+ Docker image |

### 3.3 Environments

Three environments are required:

| Environment | Purpose | Auto-deploy |
|---|---|---|
| `development` | Local Docker Compose (S14) | No |
| `staging` | Fly.io; triggers on merge to `main` | Yes |
| `production` | Fly.io; manual promotion from staging | No |

Staging and production use the same checked-in Fly configuration template but separate Fly apps (`tta-staging` and `tta-production`). App name, image tag, and environment are deployment inputs, not hard-coded behavioral contract. Both apps share the same Docker image published per commit or release tag.

---

## 4. Functional Requirements

### FR-46.01 — Single Docker Image for All Environments

The same Docker image (built by S14's Dockerfile) SHALL be deployed to local
dev, staging, and production. Environment-specific behavior is controlled
entirely by environment variables. No image variant builds are permitted.

### FR-46.02 — Fly.io App Configuration

A `fly.toml` or generated Fly configuration artifact at the repository root SHALL configure the TTA API machine. The following is the required shape; concrete app/image values are deployment-specific and MUST be parameterized by CI or Fly app context rather than hard-coded to production:

```toml
app = "${FLY_APP_NAME}"
primary_region = "iad"

[build]
  image = "registry.fly.io/tta:${IMAGE_TAG}"

[env]
  TTA_ENV = "${TTA_ENV}"
  PORT = "8000"

[[services]]
  internal_port = 8000
  protocol = "tcp"
  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]
  [[services.ports]]
    port = 80
    handlers = ["http"]
    force_https = true

[deploy]
  release_command = "uv run alembic upgrade head"
  strategy = "rolling"

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

### FR-46.03 — Secrets Management

All secrets SHALL be stored as Fly secrets (`fly secrets set KEY=VALUE`).
Secrets are never stored in `fly.toml`, source code, or CI environment
variable logs.

Required secrets in every Fly environment:
- `DATABASE_URL` — PostgreSQL connection string
- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`
- `REDIS_URL`
- `TTA_API_SECRET_KEY`
- `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY` (or the canonical `TTA_LANGFUSE_*` aliases if S71/shared Langfuse integration standardizes on those names; the production config must expose the names consumed by the runtime settings layer)
- `LITELLM_API_KEY` (or provider-specific key)

The `.env.example` (S14) continues to serve as the canonical list of required
variables. It is the source of truth for which secrets must exist in each
Fly environment.

### FR-46.04 — Zero-Downtime Deployments

Deployments SHALL use Fly's `rolling` strategy: new machines start and pass
health checks before old machines are stopped. The `release_command` runs
Alembic migrations before any machine is replaced. Migrations MUST be
backward-compatible with the previous running version (expand/contract pattern).

### FR-46.05 — Neo4j and Redis Machines

Neo4j and Redis SHALL run as dedicated Fly Machines in the same Fly
organization. Each SHALL have a Fly Volume mounted at `/data` (10 GB minimum).
These machines are NOT auto-replaced on deploy; they are persistent state
nodes. Fly Volumes provide AZ-local persistence.

### FR-46.06 — CI/CD Pipeline Extension

The existing CI pipeline (S14 FR-14.19, FR-14.20) SHALL be extended with:
1. `fly deploy --app tta-staging --image registry.fly.io/tta:$SHA` — on merge
   to `main`, after all tests pass
2. `fly deploy --app tta-production --image registry.fly.io/tta:$TAG` — on
   manual tag push (`v*`), after staging smoke tests pass

The CI job requires `FLY_API_TOKEN` stored as a GitHub Actions secret.

### FR-46.07 — Environment Parity Audit

Before every production deploy, a parity check script SHALL verify that the staging and production Fly secrets have the same *key set* (values differ; keys must match) and that required production values are present, non-empty, and not known placeholders such as `CHANGE_ME`. Any key present in staging but absent in production, or any required production value that is empty/placeholder, SHALL block the deploy before rollout.

### FR-46.08 — TTA_ENV = "production" Constraints

When `TTA_ENV=production`, the application MUST:
- Disable debug endpoints
- Emit structured JSON logs (no human-readable dev format)
- Reject startup if any `CHANGE_ME` placeholder remains in loaded config

### FR-46.09 — Backup and Recovery

PostgreSQL: Fly Postgres provides daily snapshots. A weekly manual restore
drill is required before v3 launch.

Neo4j: A daily backup script SHALL run `neo4j-admin database dump` and upload the dump to the configured cloud object store. The v3 default target is Tigris/S3-compatible storage, but bucket/provider/credentials are deployment configuration, not normative source constants. Retention: 14 days.

Redis: Redis is ephemeral session/cache storage; durability is provided by
`appendonly yes` (AOF). If AOF is lost, sessions are invalidated gracefully.

---

## 5. Non-Functional Requirements

### NFR-46.01 — Deployment availability

**Category**: Reliability

**Target**: Staging and production deploys use health-gated rolling replacement so existing healthy machines continue serving when a new release fails startup or health checks. If the environment runs only one API machine (`min = 1`), this target means failed new releases do not replace the healthy old machine; it does not promise uninterrupted responses during every machine restart. True no-interruption deploys require `min >= 2`.

### NFR-46.02 — Secret hygiene

**Category**: Security

**Target**: Production startup fails closed on placeholder secrets, and CI/deploy logs do not expose secret values.

### NFR-46.03 — Recovery readiness

**Category**: Operations

**Target**: Every persistent store has a documented backup source and a restore drill requirement before v3 launch.

## 6. User Journeys

### Journey 1: Staging deploy after main merge

- **Trigger**: A PR merges to `main` after CI passes.
- **Steps**:
  1. CI builds/publishes the single Docker image for the commit.
  2. Fly deploy runs against staging using that image.
  3. Release migrations run before machine replacement.
  4. New machine health checks pass before old machines stop.
- **Happy path**: Staging serves `/api/v1/health` within the deploy budget.
- **Alternative paths**: If migration or health checks fail, the previous staging version remains active and the failure is visible in CI logs.

### Journey 2: Manual production promotion

- **Trigger**: A release tag is pushed after staging smoke tests pass.
- **Steps**:
  1. Secret parity check compares staging and production key sets.
  2. Production deploy uses the tagged image.
  3. Production startup rejects debug settings and placeholders.
  4. Health checks confirm the promoted version before traffic shift completes.
- **Happy path**: Production serves the tagged release; with `min >= 2`, routine deploys avoid user-visible interruption, while `min = 1` environments may briefly reconnect long-lived streams.
- **Alternative paths**: Missing secrets, placeholder values, migration failure, or failed health checks block promotion.

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | Staging has a secret key missing from production | Production deploy is blocked before image rollout. |
| E2 | Alembic migration fails during release command | New machines are not promoted and old machines continue serving. |
| E3 | Health check never turns green on new machine | Rolling deploy aborts and the previous version remains active. |
| E4 | Neo4j or Redis Fly volume is unavailable | Readiness check fails; app does not accept player traffic. |
| E5 | Production config contains a `CHANGE_ME` placeholder | Startup fails with a clear variable-specific error. |
| E6 | Backup upload fails | Deploy can continue only if the failure is outside the deployment path, but alerting records the missed backup and restore drill status. |
| E7 | Fly region has transient outage | Runbook identifies manual rollback/region response; multi-region failover remains out of scope. |

## 8. Acceptance Criteria (Gherkin)

```gherkin
Feature: Cloud Deployment

  Scenario: AC-46.01 — Staging auto-deploys on main merge
    Given a PR is merged to main
    And all CI checks pass
    When the deploy job runs
    Then fly deploy runs for tta-staging with the new image SHA
    And the Alembic migration runs before machines are replaced
    And the staging app responds 200 to GET /api/v1/health within 120s

  Scenario: AC-46.02 — Production deploys only on manual tag
    Given a git tag matching v* is pushed
    When the production deploy job runs
    Then parity check confirms staging and prod have the same secret key set
    And fly deploy runs for tta-production with the tagged image

  Scenario: AC-46.03 — Secrets never in source or logs
    Given CI workflow logs for a staging deploy
    When the logs are scanned for secret values
    Then no DATABASE_URL, API keys, or passwords are present in any log line

  Scenario: AC-46.04 — Zero-downtime rolling deploy
    Given a staging deploy is in progress (rolling strategy)
    When a new machine starts
    Then health check passes before old machine stops
    And requests to staging return 200 throughout the deploy

  Scenario: AC-46.05 — TTA_ENV=production rejects CHANGE_ME placeholders
    Given TTA_ENV=production
    And TTA_API_SECRET_KEY = "CHANGE_ME_BEFORE_RUNNING"
    When the application starts
    Then startup fails with a clear error identifying the variable
```

### Criteria Checklist

- [ ] **AC-46.01**: Staging auto-deploys on main merge.
- [ ] **AC-46.02**: Production deploys only on manual tag.
- [ ] **AC-46.03**: Secrets never in source or logs.
- [ ] **AC-46.04**: Zero-downtime rolling deploy.
- [ ] **AC-46.05**: TTA_ENV=production rejects CHANGE_ME placeholders.

---

## 9. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|---|---|---|
| S14 | Local deployment baseline | S46 reuses the same Docker image and keeps Docker Compose as local dev. |
| S15 | Observability | Production readiness and deploy health rely on structured logs and health metrics. |
| S17 | Data privacy | Backup/restore behavior must preserve privacy and retention constraints. |
| S48 | Async job runner | Production deployment must include the worker process/runtime entrypoint. |
| S49 | Horizontal scaling | Multi-instance production behavior extends the single-region Fly deployment. |

## 10. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-46.01 | Cloud target — Fly.io vs Cloud Run vs other | ✅ Resolved | **Fly.io** — native Docker deployment, volume persistence for Neo4j/Redis, rolling deploy, managed Postgres, minimal ops overhead. |

## 11. Out of Scope

- Multi-region deployments (v4+, depends on S49 horizontal scaling).
- Kubernetes or ECS (single-process mandate; Fly Machines are sufficient for v3).
- CDN or edge caching (static asset serving not a v3 requirement).
- Database high-availability (single Fly Postgres machine is sufficient for v3
  scale; HA upgrade deferred to v4+).

---
