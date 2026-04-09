# Deployment Runbook

Operational guide for the Therapeutic Text Adventure (TTA) stack.

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- A `.env` file based on `.env.example` with all required secrets filled in
- At minimum: `LITELLM_API_KEY` for LLM access

## First Deploy

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env with your secrets

# 2. Start the core stack
docker compose up -d

# 3. Verify health
curl -s http://localhost:8000/health
# Expected: {"status":"ok"}

# 4. Run database migrations
docker compose exec tta-api uv run alembic upgrade head

# 5. (Optional) Start monitoring
docker compose --profile monitoring up -d
```

## Service Health Checks

| Service     | Check                                          |
|------------|------------------------------------------------|
| tta-api    | `curl http://localhost:8000/health`             |
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
- **Grafana**: http://localhost:3001 — dashboards (default login: admin/admin)
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

| Alert                 | Condition                          | Severity |
|-----------------------|------------------------------------|----------|
| HighAPIErrorRate      | >10% 5xx responses over 5 min     | critical |
| LLMAPIUnreachable     | LLM errors >50% over 2 min        | critical |
| SlowTurnProcessing    | p95 turn latency >30s over 5 min  | warning  |
| HighDailyLLMCost      | Daily LLM cost >$50               | warning  |
| DBPoolExhausted       | PG pool >90% utilized over 2 min  | critical |

> **Note**: This wave ships rule evaluation only. Alertmanager for
> notification routing/deduplication is planned for a future wave.

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

```bash
# PostgreSQL dump
docker compose exec tta-postgres \
  pg_dump -U tta tta > backup_$(date +%Y%m%d).sql
```

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

See `.env.example` for the complete list. Key variables:

| Variable            | Required | Description                       |
|--------------------|----------|-----------------------------------|
| `LITELLM_API_KEY`  | Yes      | API key for LLM provider          |
| `DATABASE_URL`     | Yes      | PostgreSQL connection string       |
| `NEO4J_PASSWORD`   | Yes      | Neo4j database password            |
| `REDIS_URL`        | No       | Redis connection (default: local)  |
| `CORS_ORIGINS`     | No       | Comma-separated allowed origins    |
| `ADMIN_TOKEN`      | No       | Admin API authentication token     |
