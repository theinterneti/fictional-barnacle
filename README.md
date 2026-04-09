# Therapeutic Text Adventure (TTA)

An AI-powered narrative game where players make meaningful choices in richly
simulated worlds. Stories that are fun to play, compelling to read, and —
eventually — worth sharing.

## Quick Start

```bash
# 1. Clone and enter the repo
git clone https://github.com/<org>/fictional-barnacle.git
cd fictional-barnacle

# 2. Copy the environment template and fill in secrets
cp .env.example .env
# Edit .env — set your LLM provider key (e.g. OPENAI_API_KEY)
# and any passwords you want to change.
#
# NOTE: .env.example uses localhost URLs for local development.
# For Docker, the compose services override connection URLs
# automatically via service DNS names (tta-postgres, tta-redis, etc.).

# 3. Start the core stack
docker compose up -d

# 4. (Optional) Start the monitoring stack
docker compose --profile monitoring up -d
```

The API is ready when `curl http://localhost:8000/api/v1/health` returns
a JSON response with `"status": "healthy"` (or `"degraded"` if optional
services like Neo4j or Redis are still starting).

## Architecture

```
┌──────────────┐      ┌─────────────┐
│  Web Client  │─────▶│  FastAPI API │:8000
│  (static/)   │      │  (tta-api)   │
└──────────────┘      └──────┬───────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                   ▼
   ┌────────────┐    ┌────────────┐     ┌────────────┐
   │ PostgreSQL │    │   Neo4j    │     │   Redis    │
   │  :5433     │    │  :7474     │     │  :6379     │
   └────────────┘    └────────────┘     └────────────┘

Optional services:
  Langfuse  :3000     Jaeger  :16686
  Prometheus :9090    Grafana :3001
```

## Service Ports

| Service      | Port  | Purpose                        |
|-------------|-------|--------------------------------|
| tta-api     | 8000  | Game API + /metrics endpoint   |
| PostgreSQL  | 5433  | Player, session, game state    |
| Neo4j       | 7474  | World graph (browser)          |
| Neo4j Bolt  | 7687  | World graph (driver)           |
| Redis       | 6379  | Rate limiting, caching         |
| Langfuse    | 3000  | LLM observability              |
| Jaeger      | 16686 | Distributed tracing UI         |
| Prometheus  | 9090  | Metrics scraping (monitoring)  |
| Grafana     | 3001  | Dashboards (monitoring)        |

## Development

```bash
# Install dependencies (uses uv, not pip)
uv sync

# Run the quality gate
make quality          # ruff check + format + pyright

# Run tests
make test             # pytest (1300+ tests)

# Run everything
make validate-all     # quality + test + spec validators
```

## Tech Stack

| Layer         | Technology                              |
|--------------|------------------------------------------|
| Language     | Python 3.12+, uv                         |
| API          | FastAPI ≥ 0.135 (native SSE)             |
| LLM          | LiteLLM ≥ 1.50 (library mode)            |
| Databases    | PostgreSQL 16+, Neo4j CE 5.x, Redis 7+   |
| ORM          | SQLModel ≥ 0.0.38                         |
| Observability| Langfuse v4, structlog, OpenTelemetry     |
| Quality      | Ruff (88-char), Pyright standard, pytest  |

## Spec-Driven Development

All code is written against formal specifications in `specs/`. See
[specs/README.md](specs/README.md) for the full inventory of 29 specs across
6 levels. Technical plans live in `plans/`.

## License

TBD

