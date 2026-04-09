---
description: 'MCP tool usage directives for CGC, Serena, Hindsight, and Context7 in the TTA repository'
applyTo: '**'
---

# MCP Tool Usage

These tools are available via MCP servers and should be used **proactively**, not only
when the user explicitly requests them. Each tool has specific trigger conditions below.

## Serena — Symbol-Aware Code Navigation

**Use freely** for structural code questions. Prefer over grep/text search.

| Task | Tool |
|---|---|
| What calls X? | `find_referencing_symbols` |
| What's in module Y? | `get_symbols_overview` |
| Show the body of Z | `find_symbol` |

- At session start: call `check_onboarding_performed` to confirm orientation
- Before any refactor: map all references to the target symbol before editing
- Fall back to grep/search only if Serena is unavailable

## CGC — Code Graph Context

**Use before** large refactors, for impact analysis, and for dependency mapping.

| Task | Tool |
|---|---|
| What depends on X? | `analyze_code_relationships` |
| Unused code | `find_dead_code` |
| Hotspots | `find_most_complex_functions` |
| Semantic search | `find_code` |

- Runs via `~/.local/bin/cgc mcp start`
- Worktree note: orientation hook may block writes in git worktrees — if blocked,
  create `/tmp/tta_hooks/<session-id>/cgc_oriented` manually
- If unavailable, state so and continue without it

## Hindsight — Persistent Memory

**Use deliberately** in every meaningful session when the MCP server is available.

| Bank | Purpose |
|---|---|
| `adam-global` | Cross-project preferences, workflow habits, reusable patterns |
| `fictional-barnacle` | Repo-specific architecture, conventions, decisions, commands |

Workflow:
- **Recall** from relevant banks at the start of non-trivial work
- **Retain** decisions, patterns, failures, and preferences before finishing significant work
- Use stable `document_id` for evolving notes to avoid duplicates
- Never retain secrets, tokens, or credentials
- If unavailable, say so and continue without pretending recall happened

## Context7 — External Documentation

**Use proactively** when the task depends on authoritative, current, version-specific
external documentation not present in the workspace.

See `.github/instructions/context7.instructions.md` for full usage protocol.

Trigger when:
- Framework/library API details are needed (FastAPI, LiteLLM, SQLModel, etc.)
- Version-sensitive guidance is required (breaking changes, deprecations)
- Security or correctness patterns matter (auth flows, crypto, serialization)
- Unfamiliar error messages appear from third-party tools

## When NOT to Use These Tools

- Simple file edits with no symbol relationships: skip Serena
- Trivial single-file changes: skip CGC
- Purely local logic with no external APIs: skip Context7
- Quick throwaway tasks: skip Hindsight retain (still recall at start)
