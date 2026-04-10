# AGENTS.md — Universal Agent Context

Shared entry point for all AI agents working in the TTA rebuild repository.

## What This Repo Is

**Therapeutic Text Adventure (TTA)** — AI-powered narrative game where players make
meaningful choices in richly simulated worlds. This is a **clean rebuild** using
Spec-Driven Development (SDD). All code is generated from, reviewed against, and
validated by written specifications.

## Repository Structure

```
specs/          29 functional specifications (source of truth)
  future/       5 boundary stubs for post-v1 features (S18-S22)
plans/          System plan + 6 component technical plans
src/            Application source code
tests/          Unit, integration, and BDD tests
static/         Web playtest client
.github/        CI, issue templates, Copilot instructions
```

## SDD Phases

1. **Specify (What)** → Behavior-focused specs with acceptance criteria
2. **Plan (How)** → Technical plans with stack, architecture, contracts
3. **Tasks** → GitHub issues for PR-sized work items
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
| Error handling, moderation, rate limiting | `specs/23-25` + `plans/resilience-and-safety.md` |
| Admin, save/load, performance | `specs/26-28` + `plans/ops.md` / `api-and-sessions.md` |
| Privacy | `specs/17` |
| Project scope, values | `specs/00-project-charter.md` |

## Spec & Plan Inventory

29 specs (S00-S28) across 6 levels — full listing in `specs/README.md`
7 technical plans — plan index in `plans/index.md`

## Tool Integrations

See `.github/instructions/` for detailed usage guides:
- **Serena** — Symbol-aware code navigation
- **CGC** — Dependency analysis and code graph
- **Hindsight** — Persistent memory across sessions
- **Context7** — Live external documentation

## External Dependencies

External packages and services used by TTA:

| Dependency | Purpose | Integration |
|---|---|---|
| **LiteLLM** | LLM client for provider abstraction | Direct import from `tta.llm` |
| **1Password** | Secret management | Use `op run --env-file=.env` for secret injection |

## Running with 1Password

```bash
# First time: copy template and add your keys
cp .env.template .env

# Run with secret injection:
op run --env-file=.env -- python -m tta
```

The `.env.template` file uses 1Password URIs (e.g., `op://TTA/Groq/credential`)
that get resolved at runtime — no actual keys committed to version control.

LLM integration uses LiteLLM in library mode (not proxy). The client is at
`src/tta/llm/litellm_client.py`. See `specs/07-llm-integration.md` and
`plans/llm-and-pipeline.md` for architecture details.

## Agent Roster

| Agent | Role | Config |
|---|---|---|
| **Claude Code** | Primary — main decision maker | `CLAUDE.md` |
| GitHub Copilot | AI coding assistant | `.github/copilot-instructions.md` |
