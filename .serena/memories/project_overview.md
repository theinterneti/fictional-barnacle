# TTA — Therapeutic Text Adventure

AI-powered narrative game where players make meaningful choices in richly simulated worlds.
Clean rebuild following Spec-Driven Development (SDD).

## Tech Stack
- Python 3.12+, uv (never pip), FastAPI >= 0.135, LiteLLM >= 1.83
- PostgreSQL 16+, Neo4j CE 5.x, Redis 7+
- SQLModel >= 0.0.38, structlog, Langfuse v4, tenacity >= 9.0
- Ruff (88-char, py312), Pyright standard, pytest asyncio_mode="auto"

## Structure
```
specs/          23 functional specifications (source of truth)
plans/          System plan + 5 component technical plans
src/tta/        Main package: api, models, llm, pipeline, world, genesis, persistence, safety, prompts, observability, logging, config
tests/          unit/, integration/, bdd/
migrations/     postgres/ (Alembic), neo4j/
```

## Key Constraints
- Specs are source of truth — code must match spec ACs
- Single FastAPI process, no microservices
- OSS-first (~90% OSS, ~2,200 lines custom)
- Conventional Commits
