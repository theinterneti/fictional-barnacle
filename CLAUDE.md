# TTA — Claude Code Instructions

Claude Code is the **primary agent** for this repository.

## Project

**Therapeutic Text Adventure (TTA)** — AI-powered narrative game where players make meaningful choices in richly simulated worlds. This is a **clean rebuild** following Spec-Driven Development (SDD).

Multi-stage pipeline: `User Input → Understand → Enrich → Generate → Stream → Player`

## SDD Workflow

All work follows four phases. **Specs are the source of truth** — if code contradicts a spec, the code is wrong.

1. **Specify (What)** → 23 functional specs in `specs/` define behavior, acceptance criteria, and scope fences
2. **Plan (How)** → System plan + 5 component plans in `plans/` define tech stack, architecture, and contracts
3. **Tasks** → GitHub issues: Wave 0 (contracts/interfaces), Wave 1 (bootstrap implementation)
4. **Implement & Validate** → Code against specs, test against ACs, fix deviations

**Before writing any code**, read the relevant spec AND plan.

## Routing Table

| Working on… | Read first |
|---|---|
| Architecture, tech stack, cross-cutting | `plans/system.md` |
| Game loop, narrative, world, characters | `specs/01-06` + `plans/world-and-genesis.md` |
| LLM integration, turn pipeline | `specs/07-08` + `plans/llm-and-pipeline.md` |
| API, sessions, persistence, streaming | `specs/10-12` + `plans/api-and-sessions.md` |
| Prompts, content management | `specs/09` + `plans/prompts.md` |
| Deployment, CI, observability, testing | `specs/14-16` + `plans/ops.md` |
| Privacy, data retention | `specs/17` + `plans/system.md` §5 |
| Project scope, values, philosophy | `specs/00-project-charter.md` |
| Future stubs (therapy, safety, sharing) | `specs/future/18-22` |

## Quality Gate

```bash
make quality        # ruff check + format + pyright
make test           # pytest
make validate-all   # spec + plan validators
```

## Tech Stack (from `plans/system.md`)

| Layer | Technology |
|---|---|
| Language | Python 3.12+, `uv` only (never pip) |
| API | FastAPI ≥ 0.135 (native SSE) |
| LLM | LiteLLM ≥ 1.50 (library mode, not proxy) |
| Relational DB | PostgreSQL 16+ (everywhere, no SQLite) |
| World graph | Neo4j CE 5.x |
| Session cache | Redis 7+ (ephemeral only) |
| ORM | SQLModel ≥ 0.0.38 |
| Observability | Langfuse v4, structlog, OpenTelemetry |
| Linting | Ruff (88-char, py312, select E,W,F,I,B,C4,UP) |
| Types | Pyright `standard` mode |
| Testing | pytest, asyncio_mode="auto", pytest-bdd for ACs |
| Resilience | tenacity ≥ 9.0 (no custom retry logic) |

### Explicit Exclusions

- **No LangGraph** — pipeline is linear 4-stage, plain async orchestrator
- **No LangChain** — LiteLLM direct
- **No SQLite** — Postgres everywhere via Docker
- **No Ink/Twine** — world graph IS the story structure

## Non-Negotiables

- Python 3.12+ | `uv` only | 88-char lines | Pyright `standard`
- Conventional Commits
- Specs are source of truth — code must match spec ACs
- OSS-first (~90% OSS, ~2,200 lines custom) — justify any new custom code
- Single FastAPI process, no microservices
- Safety systems deferred to future releases (S18-S19 are stubs)

## Spec Reference

### Level 0 — Foundation
| ID | Title |
|---|---|
| S00 | Project Charter |

### Level 1 — Core Game Experience
| ID | Title |
|---|---|
| S01 | Gameplay Loop & Progression |
| S02 | Genesis Onboarding |
| S03 | Narrative Engine |
| S04 | World Model |
| S05 | Choice & Consequence |
| S06 | Character System |

### Level 2 — AI & Content
| ID | Title |
|---|---|
| S07 | LLM Integration |
| S08 | Turn Processing Pipeline |
| S09 | Prompt & Content Management |

### Level 3 — Platform
| ID | Title |
|---|---|
| S10 | API & Streaming |
| S11 | Player Identity & Sessions |
| S12 | Persistence Strategy |
| S13 | World Graph Schema |

### Level 4 — Operations
| ID | Title |
|---|---|
| S14 | Deployment & Infrastructure |
| S15 | Observability |
| S16 | Testing Infrastructure |
| S17 | Data Privacy |

### Level 5 — Future (Boundary Stubs Only)
| ID | Title |
|---|---|
| S18 | Therapeutic Framework |
| S19 | Crisis & Content Safety |
| S20 | Story Sharing |
| S21 | Collaborative Writing |
| S22 | Community |

## Plans Reference

| Plan | Covers |
|---|---|
| `plans/system.md` | Cross-cutting: stack, architecture, contracts |
| `plans/world-and-genesis.md` | S02, S04, S13 — world model + onboarding |
| `plans/llm-and-pipeline.md` | S07, S08 — LLM client + turn pipeline |
| `plans/api-and-sessions.md` | S10, S11, S12 — API + auth + persistence |
| `plans/prompts.md` | S03, S07-S09 — prompt management |
| `plans/ops.md` | S14-S16 — deploy, observe, test |

## Agent Roster

| Agent | Config |
|---|---|
| **Claude Code** (primary) | `CLAUDE.md` (this file) |
| GitHub Copilot | `.github/copilot-instructions.md` |
