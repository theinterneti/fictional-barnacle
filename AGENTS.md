# AGENTS.md — Universal Agent Context

Shared entry point for all AI agents working in the TTA rebuild repository.

## What This Repo Is

**Therapeutic Text Adventure (TTA)** — AI-powered narrative game where players make meaningful choices in richly simulated worlds. This is a **clean rebuild** using Spec-Driven Development (SDD).

All code is generated from, reviewed against, and validated by written specifications.

## Repository Structure

```
specs/          23 functional specifications (source of truth)
  future/       5 boundary stubs for post-v1 features (S18-S22)
plans/          System plan + 5 component technical plans
.github/        CI, issue templates, Copilot config
(src/)          Will be created during Wave 1 implementation
(tests/)        Will be created during Wave 1 implementation
```

## SDD Phases

1. **Specify (What)** → Behavior-focused specs with acceptance criteria
2. **Plan (How)** → Technical plans with stack, architecture, contracts
3. **Tasks** → GitHub issues (Wave 0: contracts, Wave 1: bootstrap)
4. **Implement & Validate** → Code against specs, test against ACs

**Rule**: Read the relevant spec AND plan before writing any code.

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+, `uv` (never pip) |
| API | FastAPI ≥ 0.135 (native SSE) |
| LLM | LiteLLM ≥ 1.50 (library mode) |
| Databases | PostgreSQL 16+, Neo4j CE 5.x, Redis 7+ |
| ORM | SQLModel ≥ 0.0.38 |
| Observability | Langfuse v4, structlog, OpenTelemetry |
| Quality | Ruff (88-char), Pyright standard, pytest |

**Excluded**: LangGraph, LangChain, SQLite, Ink/Twine.

## Non-Negotiables

- Python 3.12+ | `uv` only | 88-char lines | Pyright `standard`
- Conventional Commits
- Specs are source of truth — if code contradicts a spec, the code is wrong
- OSS-first — justify any new custom code
- Single FastAPI process, no microservices

## Quality Gate

```bash
make quality        # ruff check + format + pyright
make test           # pytest
make validate-all   # spec + plan validators
```

## How to Navigate

| Working on… | Read first |
|---|---|
| Architecture, tech stack | `plans/system.md` |
| Game loop, narrative, world | `specs/01-06` + `plans/world-and-genesis.md` |
| LLM integration, pipeline | `specs/07-08` + `plans/llm-and-pipeline.md` |
| API, sessions, streaming | `specs/10-12` + `plans/api-and-sessions.md` |
| Prompts, content | `specs/09` + `plans/prompts.md` |
| Deployment, CI, observability | `specs/14-16` + `plans/ops.md` |
| Privacy | `specs/17` |
| Project scope, values | `specs/00-project-charter.md` |

## Spec Inventory (23 specs)

| Level | IDs | Topics |
|---|---|---|
| 0 — Foundation | S00 | Project Charter |
| 1 — Core Game | S01-S06 | Gameplay, Genesis, Narrative, World, Choice, Characters |
| 2 — AI & Content | S07-S09 | LLM Integration, Turn Pipeline, Prompts |
| 3 — Platform | S10-S13 | API/Streaming, Identity/Sessions, Persistence, World Graph |
| 4 — Operations | S14-S17 | Deployment, Observability, Testing, Privacy |
| 5 — Future Stubs | S18-S22 | Therapy, Safety, Sharing, Co-authoring, Community |

Full inventory: `specs/README.md` | Spec index: `specs/index.md`

## Plans Inventory (6 plans)

| Plan | Specs Covered |
|---|---|
| `plans/system.md` | Cross-cutting (all) |
| `plans/world-and-genesis.md` | S02, S04, S13 |
| `plans/llm-and-pipeline.md` | S07, S08 |
| `plans/api-and-sessions.md` | S10, S11, S12 |
| `plans/prompts.md` | S03, S07-S09 |
| `plans/ops.md` | S14-S16 |

## Agent Roster

| Agent | Role | Config |
|---|---|---|
| **Claude Code** | Primary — main decision maker | `CLAUDE.md` |
| GitHub Copilot | AI coding assistant | `.github/copilot-instructions.md` |
