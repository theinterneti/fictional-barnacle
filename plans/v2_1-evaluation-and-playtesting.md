# v2.1 Evaluation & Playtesting — Component Technical Plan

> **Phase**: SDD Phase 2 — Component Technical Plan (Stub)
> **Scope**: Scenario Seed Library, LLM Playtester Harness, Human Playtester
>   Program, Narrative Quality Evaluation, Evaluation Pipeline
> **Input specs**: S41, S42, S43, S44, S45
> **Parent plan**: `plans/system.md` (authoritative)
> **Depends on**: `plans/v2-universe-and-simulation.md` (v2.0 must ship first)
> **Status**: 📝 Stub — detailed design deferred until v2.0 lands
> **Last Updated**: 2026-04-22

---

## 0. Why This Plan Is A Stub

v2.1 is the **validation half** of the v2 release: "prove it's fun." It is
structurally decoupled from v2.0 — none of the v2.0 waves depend on v2.1
being designed. Writing the full component plan now would freeze choices
(evaluation rubric weights, playtester intake form schema, CI thresholds)
that are cheaper to defer until v2.0 is in-hand and we have real transcripts
to reason about.

This stub exists to:

1. Lock the **spec boundary** (S41–S45) and non-goals.
2. Record **cross-cutting decisions** that v2.0 work needs to respect.
3. Name the **open questions** that full drafting must answer.
4. Outline the likely **wave order** so v2.0 waves don't accidentally
   foreclose options.

A full component plan will be drafted after v2-Wave-12 (Genesis v2) is
merged, at which point real session transcripts exist to inform the
rubric and pipeline design.

---

## 1. Spec Boundary

| Spec | Role | Notes |
|------|------|-------|
| **S41** Scenario Seed Library | Content — curated starting points | 4 canonical seeds locked by S41: `bus-stop-shimmer`, `cafe-with-strange-symbols`, `library-forbidden-book`, `dirty-frodo` (display: "City of Thorns"). YAML format + `data/seeds/` filesystem scan. |
| **S42** LLM Playtester Agent Harness | Automated end-to-end session runs | Uses v1 S07 LLM client. Produces transcript + agent commentary. |
| **S43** Human Playtester Program | Recruitment, consent, intake | 10–30 participants; structured feedback form; consent & compensation policy. |
| **S44** Narrative Quality Evaluation | Scoring rubric | Merges automated (S42) + human (S43) signals into `NarrativeQualityReport`. |
| **S45** Evaluation Pipeline | Orchestration & CI verdict | Parallel S42 runs; ingests S43 records; aggregates S44 reports; emits release-level verdict; ships to Langfuse. |

### Non-Goals

- Production-grade social features (v4+ territory — S63).
- Crowdsourced human playtesting (v2.1 limits to recruited cohort).
- Real-money incentives — compensation model is a v2.1 open question,
  resolved before S43 deployment.
- Therapeutic evaluation (v5+ — gated by S60, scored by S61 instruments).

---

## 2. Cross-Cutting Decisions Required Before v2.0 Ships

These are the items v2.0 work **must** leave room for. They are not settled
here — they are flagged so nothing in v2.0 forecloses them.

### 2.1 Session Transcript Fidelity

S42/S44 need the full `(player_input, narrative_output, TurnState snapshot)`
triple for each turn. v2.0's `NarrativeTransport` (§4.5 of the v2 plan) is
the production path; for playtesting, S42 calls the same API surface a real
client would. **Constraint on v2.0**: the SSE/WS protocol must be consumable
by a headless Python client — no browser-specific framing.

### 2.2 Langfuse Trace Correlation

S45 ships aggregate verdicts to Langfuse. Each playtester session must emit
a Langfuse trace with a `playtester_run_id` tag so S45 can correlate
post-hoc. **Constraint on v2.0**: Langfuse session tagging in the turn
pipeline must accept caller-supplied tags (already true per v1 ops plan;
reaffirmed here).

### 2.3 Universe Reproducibility

S42 needs to replay a scenario seed deterministically enough that regression
trends are meaningful. S41 seeds + S39 composition + v2 universe snapshots
(S33) give us the surface to stabilize this — but the **LLM non-determinism**
inside generation is not removed, only bounded. The v2.1 pipeline must treat
per-session variance as signal, not noise.

### 2.4 PII Boundary for S43

Human playtester feedback is PII-adjacent (contact info, consent records,
qualitative text). **Constraint**: S43 intake storage is separate from the
game session database; it lives in its own schema with v1 S17 data retention
policy applied. v2.0 does not touch this.

---

## 3. Anticipated Wave Order

Drafted for reference only — final wave assignment happens at full plan time.

| Wave | Specs | Output |
|------|-------|--------|
| v2.1-Wave-01 | S41 | `data/seeds/` directory; YAML schema; loader module; 4 canonical seeds committed |
| v2.1-Wave-02 | S42 | `PlaytesterAgent` class; taste-profile sampler; session runner; transcript writer |
| v2.1-Wave-03 | S44 | Rubric evaluators (automated signals only, for now); `NarrativeQualityReport` dataclass |
| v2.1-Wave-04 | S45 | Pipeline orchestrator (CI mode first); parallel S42 execution; Langfuse integration |
| v2.1-Wave-05 | S43 | Intake form; consent/NDA templates; storage schema; coordinator tooling |
| v2.1-Wave-06 | S44 (extend) | Human-signal evaluators; rubric weighting between LLM and human |
| v2.1-Wave-07 | S45 (extend) | Release mode; human-signal ingestion; release-level verdict logic |

Rationale for ordering: S43 is slower to start (needs recruitment, legal
review of consent text) so the S42-first sequence gets automated signal
flowing while S43 spools up in parallel.

---

## 4. Open Questions

Collected from the referenced specs; these must be closed during full
plan drafting.

| ID | Question | Owner | Blocks |
|----|----------|-------|--------|
| OQ-v2.1-01 | Rubric category weights — how are S44's quality dimensions weighted into a single score? | Full plan | S44 implementation |
| OQ-v2.1-02 | CI threshold — what score triggers a CI failure vs. a soft warning? | Full plan + v2.0 data | S45 CI mode |
| OQ-v2.1-03 | Human playtester compensation model (paid, credits, none) | Legal + coordinator | S43 deployment |
| OQ-v2.1-04 | Taste-profile distribution — random, stratified, or genre-aligned? | Full plan | S42 harness v1 |
| OQ-v2.1-05 | Does S45 CI mode gate deployment, or only flag? | v3 release process | S45 + v3 plan |
| OQ-v2.1-06 | Should S43 intake be a separate FastAPI service or a module in the main app? | Full plan | S43 deployment |

---

## 5. Compatibility With v1 And v2.0

| Source | Interaction |
|--------|------------|
| v1 `plans/system.md` | No conflicts. v2.1 adds new tables (intake, playtester runs) under v1 migration conventions. |
| v1 `plans/ops.md` | Langfuse already integrated; S45 adds new tagged traces, no infra changes. |
| v1 `plans/llm-and-pipeline.md` | S42 consumes the public turn API, not the pipeline internals. No changes to TurnState. |
| v2 `plans/v2-universe-and-simulation.md` | S41 consumes S39 composition schema (locked by v2 §0.8). S42 consumes S40 Genesis flow (v2-Wave-12). No overlap in locked sections. |

---

## 6. Handoff To Full Plan

When v2.0 has landed and full drafting begins, this stub is superseded by
a full component plan at the same path. The full plan must:

1. Keep or explicitly revise each cross-cutting decision in §2.
2. Close each open question in §4, with a decision row.
3. Populate the sections that a normal component plan carries (schemas,
   interfaces, test strategy, wave breakdown with line estimates).
4. Update `plans/index.md` via `index_plans.py` so discovery catches it.

Until then, no code under `src/tta/evaluation/` or `src/tta/playtesting/`
should be written — v2.1 is out of scope for implementation until v2.0
ships.
