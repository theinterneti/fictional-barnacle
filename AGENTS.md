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

## AC Traceability Standard

Every test function that validates a spec AC **must** carry a `@pytest.mark.spec` marker:

```python
@pytest.mark.spec("AC-29.01", "AC-29.02")
def test_universe_creation_sets_dormant_status(...):
    ...
```

Rules:
- Format: `AC-NN.MM` (zero-padded, e.g. `AC-07.04` not `AC-7.4`)
- Multiple ACs per test are allowed and encouraged
- Inline `# AC-NN.MM` comments alone are **not sufficient** — the marker is required
- `make trace` reports coverage; `make trace-html` generates the dashboard
- The `spec` marker is registered in `pyproject.toml`; no `PytestUnknownMarkWarning` will fire
- See `spec/tool-ac-traceability.md` for the full traceability standard

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
| **1Password** | Secret management | Generate a local `.env` from `.env.example` via `op inject`, then run normally |

## Running with 1Password

```bash
# First time: create a local working file
cp .env.example .env

# Replace selected values with op:// references, then materialize them once
op inject -i .env -o .env.resolved
mv .env.resolved .env

# Run normally — the app loads .env directly
python -m tta
```

The committed `.env.example` is the canonical template. You may keep `op://...`
references in the working `.env` temporarily while preparing it, then use
`op inject` to write a resolved `.env` with actual values for local runtime.
The resolved `.env` stays gitignored and must never be committed.

LLM integration uses LiteLLM in library mode (not proxy). The client is at
`src/tta/llm/litellm_client.py`. See `specs/07-llm-integration.md` and
`plans/llm-and-pipeline.md` for architecture details.

## Agent Roster

| Agent | Role | Config |
|---|---|---|
| **Claude Code** | Primary — main decision maker | `CLAUDE.md` |
| GitHub Copilot | AI coding assistant | `.github/copilot-instructions.md` |

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **fictional-barnacle** (17926 symbols, 29034 relationships, 159 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/fictional-barnacle/context` | Codebase overview, check index freshness |
| `gitnexus://repo/fictional-barnacle/clusters` | All functional areas |
| `gitnexus://repo/fictional-barnacle/processes` | All execution flows |
| `gitnexus://repo/fictional-barnacle/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
