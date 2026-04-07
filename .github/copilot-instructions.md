# TTA — GitHub Copilot Instructions

## Project

**Therapeutic Text Adventure (TTA)** — AI-powered narrative game where players make
meaningful choices in richly simulated worlds.

This is a **clean rebuild** following **Spec-Driven Development (SDD)**. All code is
generated from, reviewed against, and validated by written specifications.

## SDD Methodology

1. **Specify (What)** → 23 functional specs in `specs/` — behavior, ACs, scope fences
2. **Plan (How)** → System plan + 5 component plans in `plans/` — stack, architecture, contracts
3. **Tasks** → GitHub issues: Wave 0 (contracts), Wave 1 (bootstrap)
4. **Implement & Validate** → Code against specs, test against ACs, fix deviations

**Before writing any code**, read the relevant spec AND plan.

## Rules

- **Specs are source of truth** — if code contradicts a spec, the code is wrong
- **Behavior over implementation** — specs describe *what*, not *how*
- **OSS-first** — use existing frameworks before building custom (~90% OSS, ~2,200 lines custom)
- **Sleek** — minimal custom implementation surface area
- Read the relevant spec before working on any feature
- Reference spec acceptance criteria when writing tests

## Routing Table

| Working on… | Read first |
|---|---|
| Architecture, tech stack | `plans/system.md` |
| Game loop, narrative, world, characters | `specs/01-06` + `plans/world-and-genesis.md` |
| LLM integration, turn pipeline | `specs/07-08` + `plans/llm-and-pipeline.md` |
| API, sessions, persistence, streaming | `specs/10-12` + `plans/api-and-sessions.md` |
| Prompts, content management | `specs/09` + `plans/prompts.md` |
| Deployment, CI, observability, testing | `specs/14-16` + `plans/ops.md` |
| Privacy, data retention | `specs/17` |
| Project scope, values | `specs/00-project-charter.md` |

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+, `uv` (never pip) |
| API | FastAPI ≥ 0.135 (native SSE) |
| LLM | LiteLLM ≥ 1.50 (library mode, not proxy) |
| Databases | PostgreSQL 16+, Neo4j CE 5.x, Redis 7+ |
| ORM | SQLModel ≥ 0.0.38 |
| Observability | Langfuse v4, structlog, OpenTelemetry |
| Linting | Ruff (88-char, py312) |
| Types | Pyright `standard` mode |
| Testing | pytest, asyncio_mode="auto" |
| Resilience | tenacity ≥ 9.0 |

**Excluded**: LangGraph, LangChain, SQLite, Ink/Twine.

## Quality Gate

```bash
make quality        # ruff check + format + pyright
make test           # pytest
make validate-all   # spec + plan validators
```

## Non-Negotiables

- Python 3.12+ | `uv` only | 88-char lines | Pyright `standard`
- Conventional Commits
- Specs are source of truth — code must match spec ACs
- OSS-first — justify any new custom code
- Single FastAPI process, no microservices

## Spec Reference

| Level | IDs | Topics |
|---|---|---|
| 0 — Foundation | S00 | Project Charter |
| 1 — Core Game | S01-S06 | Gameplay Loop, Genesis, Narrative, World, Choice, Characters |
| 2 — AI & Content | S07-S09 | LLM Integration, Turn Pipeline, Prompts |
| 3 — Platform | S10-S13 | API/Streaming, Identity/Sessions, Persistence, World Graph |
| 4 — Operations | S14-S17 | Deployment, Observability, Testing, Privacy |
| 5 — Future Stubs | S18-S22 | Therapy, Safety, Sharing, Co-authoring, Community |

Full inventory: `specs/README.md` | Dependency graph: `specs/index.md`

## Conventions

- Python 3.12+, `str | None` not `Optional[str]`
- Conventional Commits
- Specs use the template at `specs/TEMPLATE.md`
- 88-char line length (Ruff)
- AAA test pattern (Arrange-Act-Assert)

## Agent Roster

| Agent | Config |
|---|---|
| **Claude Code** (primary) | `CLAUDE.md` |
| GitHub Copilot | `.github/copilot-instructions.md` (this file) |
