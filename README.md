# Therapeutic Text Adventure (TTA)

An AI-powered narrative game where players make meaningful choices in richly simulated worlds. Stories that are fun to play, compelling to read, and — eventually — worth sharing.

## What This Repo Is

This is a **specification-first** repository. Before a single line of game code is written, every feature, boundary, and behavior is documented in a formal spec. Code will be generated from these specs, reviewed against them, and validated by them.

This is **not** the old TTA repo. It's a clean rebuild that questions every assumption from the original, keeps only what earned its place, and uses battle-tested open-source solutions instead of custom infrastructure.

## Spec-Driven Development (SDD)

We follow a four-phase workflow:

### Phase 1: Specify (What to build)
Write functional specifications focused on **user journeys, behavior, and success criteria** — not implementation details. Each spec answers: *What does success look like from the player's perspective?*

### Phase 2: Plan (How to build it)
Define the technical direction: stack, architecture, constraints. The plan bridges "what" and "how" without bleeding into code. Architecture Decision Records (ADRs) capture *why* choices were made.

### Phase 3: Tasks (Decomposition)
Break specs and plans into small, actionable, reviewable chunks. Each task can be implemented and tested in isolation.

### Phase 4: Implement & Validate
Generate code task-by-task. Review incremental changes against the spec. If code deviates → fix the code. If the spec was incomplete → update the spec first, then fix the code.

## Design Principles

1. **OSS-first** — Use existing frameworks (LangGraph, FastAPI, LiteLLM, etc.). Custom code is domain-specific only.
2. **Game first** — This is a game, not a therapy app with a game skin. Fun stories, awesome simulations, satisfying progression.
3. **Question every assumption** — If the old TTA did it, this repo asks *why* before inheriting it.
4. **Sleek implementation** — Minimal custom surface area. If it exists in OSS, use it.
5. **Shareable by design** — Stories worth reading. Architecture supports sharing from day one, even if the feature ships later.

## Spec Index

See [`specs/README.md`](specs/README.md) for the complete spec index with status tracking.

## Getting Started

This repo is currently in the **Specify** phase. To contribute:

1. Read the [Project Charter](specs/00-project-charter.md) first
2. Review the [Spec Template](specs/TEMPLATE.md) for format conventions
3. Pick a spec, read it, and open issues for gaps or questions
4. See the [spec index](specs/README.md) for current status

## License

TBD — to be decided during the Plan phase.
