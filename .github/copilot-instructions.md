# TTA — GitHub Copilot Instructions

## Project

**Therapeutic Text Adventure (TTA)** — AI-powered narrative game where players make
meaningful choices in richly simulated worlds.

This is a **clean rebuild** following **Spec-Driven Development (SDD)**. All code is
generated from, reviewed against, and validated by written specifications.

## SDD Methodology

1. **Specify (What)** → 29 functional specs in `specs/` — behavior, ACs, scope fences
2. **Plan (How)** → 7 technical plans in `plans/` — stack, architecture, contracts
3. **Tasks** → GitHub issues for PR-sized work items
4. **Implement & Validate** → Code against specs, test against ACs, fix deviations

**Before writing any code**, read the relevant spec AND plan.

## Rules

- **Specs are source of truth** — if code contradicts a spec, the code is wrong
- **Behavior over implementation** — specs describe *what*, not *how*
- **OSS-first** — use existing frameworks before building custom (~90% OSS, ~2,200 lines custom)
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
| Error handling, moderation, rate limiting | `specs/23-25` + `plans/resilience-and-safety.md` |
| Admin, save/load, performance | `specs/26-28` + `plans/ops.md` / `api-and-sessions.md` |
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
| Quality | Ruff (88-char, py312), Pyright standard, pytest |
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

## Spec & Plan Reference

29 specs (S00-S28) across 6 levels — full inventory: `specs/README.md`
7 technical plans — plan index: `plans/index.md`

| Level | IDs | Topics |
|---|---|---|
| 0 — Foundation | S00 | Project Charter |
| 1 — Core Game | S01-S06 | Gameplay, Genesis, Narrative, World, Choice, Characters |
| 2 — AI & Content | S07-S09, S24 | LLM, Turn Pipeline, Prompts, Content Moderation |
| 3 — Platform | S10-S13, S23, S25 | API, Sessions, Persistence, World Graph, Errors, Rate Limits |
| 4 — Operations | S14-S17, S26, S28 | Deploy, Observe, Test, Privacy, Admin, Performance |
| 5 — Future Stubs | S18-S22 | Therapy, Safety, Sharing, Co-authoring, Community |
| — | S27 | Save/Load & Game Management |

## Conventions

- `str | None` not `Optional[str]`, AAA test pattern, specs follow `specs/TEMPLATE.md`
- Tool guides (Serena, CGC, Hindsight, Context7): see `.github/instructions/`

## Agent Roster

| Agent | Config |
|---|---|
| **Claude Code** (primary) | `CLAUDE.md` |
| GitHub Copilot | `.github/copilot-instructions.md` (this file) |
