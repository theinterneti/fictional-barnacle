# Deployment Runbook

Operational guide for the Therapeutic Text Adventure (TTA) stack.

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- A `.env` file based on `.env.example` with all required secrets filled in
- At minimum: your LLM provider API key (e.g. `OPENAI_API_KEY` env var)
- All TTA-specific settings use the `TTA_` prefix (see Environment Variables below)

## First Deploy

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env with your secrets

# 2. Start the core stack
docker compose up -d

# 3. Verify health
curl -s http://localhost:8000/api/v1/health | python -m json.tool
# Expected: {"status":"healthy","checks":{...},"version":"..."}

# 4. Run database migrations
docker compose exec tta-api uv run alembic upgrade head

# 5. (Optional) Start monitoring
docker compose --profile monitoring up -d
```

## Service Health Checks

| Service     | Check                                          |
|------------|------------------------------------------------|
| tta-api    | `curl http://localhost:8000/api/v1/health`     |
| PostgreSQL | `docker compose exec tta-postgres pg_isready`   |
| Neo4j      | `curl http://localhost:7474`                    |
| Redis      | `docker compose exec tta-redis redis-cli ping`  |
| Prometheus | `curl http://localhost:9090/-/healthy`           |
| Grafana    | `curl http://localhost:3001/api/health`          |

## Monitoring Access

Monitoring services use the `monitoring` Compose profile and are opt-in:

```bash
# Start monitoring alongside core services
docker compose --profile monitoring up -d

# Stop only monitoring services
docker compose --profile monitoring stop
```

- **Prometheus**: http://localhost:9090 — metrics scraping and alerting rules
- **Grafana**: http://localhost:3001 — dashboards
  - **Change the default credentials** on first login. The admin username and
    password are set via `GF_SECURITY_ADMIN_USER` and `GF_SECURITY_ADMIN_PASSWORD`
    environment variables in `docker-compose.yml` — override them in your `.env`.
  - System Health dashboard: request rates, latency, error rates, pool status
  - Turn Pipeline dashboard: processing times, LLM usage, safety flags
  - Cost dashboard: LLM spending by model and over time

### Grafana Provisioning

Dashboards and datasources are auto-provisioned on startup from:
- `monitoring/grafana/provisioning/datasources/` — Prometheus connection
- `monitoring/grafana/provisioning/dashboards/` — dashboard loader config
- `monitoring/grafana/dashboards/` — dashboard JSON definitions

To add a new dashboard, create a JSON file in `monitoring/grafana/dashboards/`
and restart Grafana.

## Alerting Rules

Prometheus evaluates alerting rules from `monitoring/prometheus/alerts.yml`:

| Alert                 | Condition                                        | Severity | Status   |
|-----------------------|--------------------------------------------------|----------|----------|
| HighAPIErrorRate      | >10% 5xx responses over 5 min                   | critical | active   |
| SlowTurnProcessing    | p95 turn latency >30s over 5 min                | warning  | active   |
| HighDailyLLMCost      | 24h LLM cost >$50 (from cost histogram)         | warning  | active   |
| LLMAPIUnreachable     | Zero LLM calls while turns active for 2 min     | critical | disabled |
| DBPoolExhausted       | PG pool >95% utilized over 2 min                | critical | disabled |

> **Note**: Disabled alerts depend on metrics that are not yet instrumented
> (planned for Wave 13). Prometheus evaluates rules only — Alertmanager
> for notification routing is planned for a future wave.

## Common Operations

### View Logs

```bash
# All services
docker compose logs -f

# Single service
docker compose logs -f tta-api

# Last 100 lines
docker compose logs --tail 100 tta-api
```

### Restart a Service

```bash
docker compose restart tta-api
```

### Database Backup

**Targets (from S12 spec):** RPO ≤ 1 hour, RTO ≤ 4 hours.

#### Automated Backup (cron)

```bash
# /etc/cron.d/tta-backup — runs hourly to meet RPO ≤ 1h
0 * * * * root docker compose -f /opt/tta/docker-compose.yml \
  exec -T tta-postgres pg_dump -U tta --format=custom tta \
  | gzip > /opt/tta/backups/tta_$(date +\%Y\%m\%d_\%H\%M).dump.gz
```

#### Manual Backup

```bash
# PostgreSQL custom-format dump (recommended)
docker compose exec tta-postgres \
  pg_dump -U tta --format=custom tta > backup_$(date +%Y%m%d).dump

# Plain SQL (human-readable, larger)
docker compose exec tta-postgres \
  pg_dump -U tta tta > backup_$(date +%Y%m%d).sql
```

#### Neo4j Backup (if enabled)

```bash
# Stop Neo4j, dump, restart
docker compose stop tta-neo4j
docker compose run --rm tta-neo4j \
  neo4j-admin database dump neo4j --to-path=/backups
docker compose start tta-neo4j
```

### Database Restore

#### PostgreSQL Restore

```bash
# 1. Stop the API to prevent writes
docker compose stop tta-api

# 2. Drop and recreate the database
docker compose exec tta-postgres \
  psql -U tta -c "DROP DATABASE IF EXISTS tta;"
docker compose exec tta-postgres \
  psql -U tta -c "CREATE DATABASE tta;"

# 3a. Restore from custom-format dump (recommended)
docker compose exec -T tta-postgres \
  pg_restore -U tta -d tta < backup_20250101.dump

# 3b. OR restore from plain SQL
docker compose exec -T tta-postgres \
  psql -U tta tta < backup_20250101.sql

# 4. Run pending migrations
docker compose exec tta-api uv run alembic upgrade head

# 5. Restart the API
docker compose start tta-api

# 6. Verify: check game count matches expectations
docker compose exec tta-postgres \
  psql -U tta -c "SELECT COUNT(*) FROM game_sessions;"
```

#### Neo4j Restore (if enabled)

```bash
docker compose stop tta-neo4j
docker compose run --rm tta-neo4j \
  neo4j-admin database load neo4j --from-path=/backups --overwrite-destination
docker compose start tta-neo4j
```

#### Redis Cache

Redis is ephemeral. After restoring PostgreSQL, the cache self-populates on
first access. If needed, restart Redis to flush stale data:

```bash
docker compose restart tta-redis
```

#### Verification Checklist

1. API health endpoint responds: `curl http://localhost:8000/api/v1/health`
2. Game count matches pre-backup count
3. Recent turns are present for active sessions
4. Prometheus metrics are being collected: `curl http://localhost:8000/metrics`

### Database Migration

```bash
docker compose exec tta-api uv run alembic upgrade head
```

### View Metrics

```bash
# Raw Prometheus metrics from the API
curl -s http://localhost:8000/metrics | head -50

# Check a specific metric
curl -s http://localhost:8000/metrics | grep tta_http_requests_total
```

## Troubleshooting

### API Won't Start

1. Check logs: `docker compose logs tta-api`
2. Verify `.env` exists and has required variables
3. Ensure PostgreSQL, Neo4j, and Redis are healthy
4. Check port 8000 isn't already in use

### Database Connection Errors

1. Verify service is running: `docker compose ps`
2. Check the connection string in `.env` matches the Docker service
3. For PostgreSQL: default port is 5433 (mapped from container 5432)

### Monitoring Shows No Data

1. Verify tta-api is running and `/metrics` returns data
2. Check Prometheus targets: http://localhost:9090/targets
3. Ensure Prometheus can reach `tta-api:8000` on the Docker network
4. Some metrics (turn pipeline, sessions, cost) are defined but only
   emit data during active gameplay — empty panels are expected if
   no games are running

## Environment Variables

All TTA application settings use the `TTA_` prefix (set in `.env` or
exported in the shell). Your LLM provider key is **not** prefixed — it
follows the provider's convention (e.g. `OPENAI_API_KEY`).

See `.env.example` for the complete list. Key variables:

| Variable                | Required | Description                            |
|------------------------|----------|----------------------------------------|
| `OPENAI_API_KEY`       | Yes*     | API key for your LLM provider          |
| `TTA_DATABASE_URL`     | Yes      | PostgreSQL connection string            |
| `TTA_NEO4J_PASSWORD`   | Yes      | Neo4j database password                 |
| `TTA_REDIS_URL`        | No       | Redis connection (default: localhost)   |
| `TTA_CORS_ORIGINS`     | No       | JSON list of allowed origins            |
| `TTA_ADMIN_TOKEN`      | No       | Admin API authentication token          |
| `TTA_LITELLM_MODEL`    | No       | Primary LLM model (default: openai/gpt-4o-mini) |

*Or whichever env var your LLM provider requires (e.g. `ANTHROPIC_API_KEY`).

---

## Langfuse Self-Hosted Deployment (S17 FR-17.31)

> **Why self-host?** Self-hosted Langfuse keeps all observability data (traces,
> prompts, scores) within your infrastructure, satisfying FR-17.31's requirement
> that LLM observability data never leaves operator-controlled systems.

### Quick Start (Docker Compose)

```bash
# Clone Langfuse
git clone https://github.com/langfuse/langfuse.git
cd langfuse

# Start with Docker Compose
docker compose up -d
```

Langfuse will be available at `http://localhost:3000`.

### TTA Integration

Set these environment variables in your TTA deployment:

```bash
TTA_LANGFUSE_ENABLED=true
LANGFUSE_HOST=http://langfuse:3000   # Internal Docker network URL
LANGFUSE_PUBLIC_KEY=pk-lf-...        # From Langfuse UI → Settings → API Keys
LANGFUSE_SECRET_KEY=sk-lf-...        # From Langfuse UI → Settings → API Keys
```

### Data Retention

Configure Langfuse data retention to match your privacy policy:

1. **Trace retention** — Set via Langfuse UI → Settings → Data Retention
2. **Score retention** — Follows trace retention by default
3. **Prompt management** — Prompts are retained until manually deleted

### Production Recommendations

1. Use PostgreSQL (not SQLite) for Langfuse's backing store.
2. Enable HTTPS via reverse proxy (nginx, Caddy, or cloud LB).
3. Restrict network access — Langfuse should only be reachable from TTA
   application servers, not the public internet.
4. Back up Langfuse's PostgreSQL database on the same schedule as TTA's.
5. Monitor Langfuse health at `/api/public/health`.

For full self-hosting documentation, see:
https://langfuse.com/docs/deployment/self-host
