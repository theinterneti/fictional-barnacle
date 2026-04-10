# fictional-barnacle Agent Context

Inherits from global `~/.config/opencode/AGENTS.md`. See that for core protocol.

## Session Start

1. Load global: `instructions/session-workflow.md`
2. Hindsight: `adam-global` + `fictional-barnacle`
3. Serena: `check_onboarding_performed` → `get_symbols_overview`
4. Acknowledge loaded context

## SDD Workflow

**Before any code**: Read spec (`specs/XX-*.md`) AND plan (`plans/*.md`).

| Working on | Read first |
|---|---|
| Architecture | `plans/system.md` |
| Game loop | `specs/01-06` + `plans/world-and-genesis.md` |
| LLM pipeline | `specs/07-08` + `plans/llm-and-pipeline.md` |
| API/sessions | `specs/10-12` + `plans/api-and-sessions.md` |

**Rule**: Specs are source of truth — if code contradicts a spec, the code is wrong.

## MCP Tools

| Tool | Use for |
|------|---------|
| Serena | Symbol queries, "what calls X?" |
| CGC | Refactor planning, dead code |
| Hindsight | Decisions, patterns, history |
| Context7 | External lib docs (FastAPI, LiteLLM) |

Full guide: `.github/instructions/mcp-tools.instructions.md`

## Quality Gate

```bash
make quality   # ruff + format + pyright
make test      # pytest
```

## Key Rules

- `uv` only (never pip)
- 88-char lines, Pyright standard
- Conventional commits
- No secrets in Hindsight