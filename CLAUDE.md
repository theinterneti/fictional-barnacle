# TTA — Claude Code Instructions

Claude Code is the **primary agent** for this repository.

## Project

**Therapeutic Text Adventure (TTA)** — AI-powered narrative game where players make
meaningful choices in richly simulated worlds. This is a **clean rebuild** following
Spec-Driven Development (SDD).

Multi-stage pipeline: `User Input → Understand → Enrich → Generate → Stream → Player`

## SDD Workflow

All work follows four phases. **Specs are the source of truth** — if code contradicts
a spec, the code is wrong.

1. **Specify (What)** → 29 functional specs in `specs/`
2. **Plan (How)** → 7 technical plans in `plans/`
3. **Tasks** → GitHub issues for PR-sized work items
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
| Error handling, moderation, rate limiting | `specs/23-25` + `plans/resilience-and-safety.md` |
| Admin, save/load, performance | `specs/26-28` + `plans/ops.md` / `api-and-sessions.md` |
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
| Databases | PostgreSQL 16+, Neo4j CE 5.x, Redis 7+ |
| ORM | SQLModel ≥ 0.0.38 |
| Observability | Langfuse v4, structlog, OpenTelemetry |
| Quality | Ruff (88-char, py312), Pyright standard, pytest |
| Resilience | tenacity ≥ 9.0 (no custom retry logic) |

**Excluded**: LangGraph, LangChain, SQLite, Ink/Twine.

## Non-Negotiables

- Python 3.12+ | `uv` only | 88-char lines | Pyright `standard`
- Conventional Commits
- Specs are source of truth — code must match spec ACs
- OSS-first (~90% OSS, ~2,200 lines custom) — justify any new custom code
- Single FastAPI process, no microservices

## Spec & Plan Inventory

29 specs (S00-S28) across 6 levels — full listing: `specs/README.md`
7 technical plans — plan index: `plans/index.md`

| Level | IDs | Topics |
|---|---|---|
| 0 — Foundation | S00 | Project Charter |
| 1 — Core Game | S01-S06, S27 | Gameplay, Genesis, Narrative, World, Choice, Characters, Save/Load |
| 2 — AI & Content | S07-S09, S24 | LLM, Turn Pipeline, Prompts, Content Moderation |
| 3 — Platform | S10-S13, S23, S25 | API, Sessions, Persistence, World Graph, Errors, Rate Limits |
| 4 — Operations | S14-S17, S26, S28 | Deploy, Observe, Test, Privacy, Admin, Performance |
| 5 — Future Stubs | S18-S22 | Therapy, Safety, Sharing, Co-authoring, Community |

## Tool Integrations

See `.github/instructions/` for detailed usage guides. Key MCP tools:
- **Serena** — Symbol-aware code navigation (prefer over grep for code structure)
- **CGC** — Cross-repo dependency analysis, dead code, complexity metrics
- **Hindsight** — Persistent memory across sessions (recall before work, retain after)
- **Context7** — Live library documentation lookup

## Agent Roster

| Agent | Config |
|---|---|
| **Claude Code** (primary) | `CLAUDE.md` (this file) |
| GitHub Copilot | `.github/copilot-instructions.md` |
