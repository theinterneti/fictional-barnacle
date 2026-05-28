# Foundation & Process Specs — Coverage Plan

> **Status:** Coverage note — these specs are implemented but lack individual plans.
> **Scope:** S00-S09 (Foundation + Core Game Experience), S65 (Local CI Gate), S67 (Autonomous Queue Readiness Gate)
> **Last Updated**: 2026-05-28

---

## Purpose

S00-S09, S65, and S67 are Approved specs that are already implemented. They do not need dedicated implementation plans because:

- **S00-S09** define the foundation and core game loop. They were implemented during v1 development before the formal plan-authoring workflow existed. The `system.md` system technical plan covers their cross-cutting decisions and architecture.
- **S65 (Local CI Gate)** and **S67 (Autonomous Queue Readiness Gate)** are process/tooling specs implemented via `scripts/` and `Makefile` targets, not application code. Their implementation is verified by `make gate` and `scripts/queue_readiness_gate.py`.

If any of these specs receive new ACs in a future version, a dedicated implementation plan should be written for that delta.

## Technology & Framework

This is a coverage document, not an implementation plan. Technology and testing are covered by the existing system plan (`plans/system.md`) for S00-S09 and by the Makefile/scripts themselves for S65/S67. No new framework decisions are introduced here.

---

## Spec-by-Spec Implementation Status

| Spec | Title | Implementation | Verified By |
|---|---|---|---|
| S00 | Project Charter | `AGENTS.md`, `CLAUDE.md`, `docs/vision/` | N/A (governance doc) |
| S01 | Gameplay Loop & Progression | `src/tta/api/routes/turns.py`, `src/tta/pipeline/` | `make test-unit` |
| S02 | Genesis Onboarding | `src/tta/api/routes/genesis.py`, `src/tta/world/` | `make test-unit` |
| S03 | Narrative Engine | `src/tta/llm/`, `src/tta/prompts/` | `make trace` |
| S04 | World Model | `src/tta/models/world.py` | `make test-unit` |
| S05 | Choice & Consequence | `src/tta/pipeline/`, `src/tta/api/routes/turns.py` | `make test-unit` |
| S06 | Character System | `src/tta/models/character.py` | `make test-unit` |
| S07 | LLM Integration | `src/tta/llm/litellm_client.py` | `make test-unit` |
| S08 | Turn Processing Pipeline | `src/tta/pipeline/` | `make trace` |
| S09 | Prompt & Content Management | `src/tta/prompts/` | `make trace` |
| S65 | Local CI Gate | `Makefile`, `scripts/dev_workflow.py`, `scripts/changed_tests.py` | `make gate` |
| S67 | Autonomous Queue Readiness Gate | `scripts/queue_readiness_gate.py` | `uv run python scripts/queue_readiness_gate.py --check` |

---

## Future Delta Plans

If any of these specs are extended with new ACs, write a plan scoped to only the new ACs. Do not re-plan the entire spec.

Example:
```
Plan: S01 — v2.1 Gameplay Loop extensions
Scope: AC-01.11 through AC-01.15 (new v2.1 ACs only)
```
