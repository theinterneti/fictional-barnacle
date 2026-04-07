# Suggested Commands

## Quality
- `make quality` — ruff check + format + pyright
- `make lint` — ruff check + pyright
- `make format` — ruff format + auto-fix
- `make typecheck` — pyright standalone
- `make check` — lint + test (full CI gate)

## Testing
- `uv run pytest tests/ -v` — all tests
- `uv run pytest tests/unit/ -v` — unit tests only
- `make test-integration` — integration tests (starts Docker services)
- `make test-watch` — continuous test runner (pytest-testmon)

## Development
- `make dev` — start dep services + API with reload
- `make up` / `make down` — Docker infrastructure
- `make migrate` — Alembic migrations
- `make migrate-neo4j` — Neo4j graph migrations

## Spec Validation
- `make validate-all` — validate specs + plans
- `make regen-indexes` — regenerate spec/plan indexes

## System Utilities
- `git`, `uv`, `docker compose`, `ruff`, `pyright`
