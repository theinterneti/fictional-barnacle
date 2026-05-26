# S67 — Autonomous Queue Readiness Gate

> **Status**: 🔍 Review
> **Level**: Process — Autonomous Pipeline Governance
> **Dependencies**: S65 (Local CI Gate), spec/plan indexes, `.hermes/pipeline/queue/FB-*.json`
> **Last Updated**: 2026-05-26

---

## 1. Purpose

Autonomous executors must not consume discovery output as a flat implementation queue. Queue items need explicit readiness classification before any agent starts coding, because the queue can contain draft specs, duplicate spec IDs, operational drills, eval/live-run gates, and missing-substrate work. This spec defines the metadata and gate behavior required to route each item into the correct lane.

## 2. User Stories

- **As an** orchestrator, **I want** queue items classified before execution, **so that** draft or blocked work cannot be accidentally implemented.
- **As a** developer, **I want** each queue item to include its lane, readiness, validation command, and evidence, **so that** agents do not guess the task type.
- **As a** reviewer, **I want** ambiguous governance states to fail closed, **so that** duplicate spec IDs and unknown dependencies are fixed before implementation begins.

## 3. Functional Requirements

### FR-1: Queue item classification

**Description**: A queue readiness gate classifies every `.hermes/pipeline/queue/FB-*.json` item.

**Behavior**: Classification uses the referenced spec status, plan existence, AC IDs, duplicate spec numbers, and known non-implementation categories.

**Constraints**: Unknown or ambiguous items must not default to IMPLEMENT.

### FR-2: Lane metadata

**Description**: Each classified item exposes explicit lane metadata.

**Behavior**: The gate emits `recommended_lane`, `readiness`, `readiness_reason`, `spec_status`, `plan_exists`, `human_gate_required`, and `validation_command`.

**Constraints**: The metadata may be emitted by a generated report or by a validation script; queue executors must consume only this explicit metadata, not infer from titles.

### FR-3: Implement-ready filtering

**Description**: Only bounded, approved, planned AC gaps are eligible for IMPLEMENT.

**Behavior**: IMPLEMENT candidates must have an approved spec, a current plan, non-deferred ACs, clear dependencies, and a concrete validation command.

**Constraints**: Draft specs, duplicate IDs, ops drills, quality/eval gates, live-run-only work, and substrate prerequisites are blocked from IMPLEMENT.

### FR-4: Fail-closed execution guard

**Description**: The gate can be run before an autonomous executor starts.

**Behavior**: When invoked with a strict mode, the gate exits non-zero if no implement-ready items exist or if blocking governance errors exist.

**Constraints**: A missing queue directory is not an implementation-ready state; it must produce an explicit empty/no-queue result.

## 4. Non-Functional Requirements

### NFR-1: Conservative by default

**Category**: Safety

**Target**: Ambiguous items route to `PLAN_REVIEW`, `SPEC_POLISH`, `SUBSTRATE_REQUIRED`, `TRACE_OR_OPS_DRILL`, `EVAL_OR_LIVE_RUN_GATE`, or `INVALID_UNTIL_SPEC_ID_FIXED`, never IMPLEMENT.

### NFR-2: Machine-readable output

**Category**: Automation

**Target**: The gate supports JSON output suitable for downstream managers and dashboards.

## 5. User Journeys

### Journey 1: Executor startup

- **Trigger**: An autonomous executor is about to consume queue items.
- **Steps**:
  1. Executor runs the readiness gate in strict mode.
  2. Gate classifies every queue item.
  3. Executor receives only IMPLEMENT items with validation commands.
- **Happy path**: Executor starts on a bounded implementation candidate.
- **Alternative paths**: If only draft/blocked items exist, executor does not start implementation work.

### Journey 2: Governance cleanup

- **Trigger**: Gate reports `INVALID_UNTIL_SPEC_ID_FIXED`.
- **Steps**:
  1. Developer reviews the duplicate or ambiguous spec references.
  2. Developer renumbers or clarifies specs/ACs.
  3. Developer reruns spec validation and the readiness gate.
- **Happy path**: The item moves from invalid to a specific non-ambiguous lane.

## 6. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | Queue item references a draft spec | Gate returns `SPEC_POLISH_REQUIRED` / `SPEC_POLISH` |
| E2 | Two specs share one spec number | Gate returns `INVALID_UNTIL_SPEC_ID_FIXED` |
| E3 | Queue item references an approved spec without a plan | Gate returns `PLAN_WRITE_REQUIRED` |
| E4 | Queue item targets restore drill evidence | Gate returns `TRACE_OR_OPS_DRILL_REQUIRED` |
| E5 | Queue item targets LLM quality or timing evidence | Gate returns `EVAL_OR_LIVE_RUN_GATE_REQUIRED` |
| E6 | Queue directory is absent or empty | Gate reports zero items and no IMPLEMENT work |
| E7 | Queue item does not match a known safe category | Gate returns `PLAN_REVIEW_REQUIRED` |

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: Autonomous queue readiness gate

  Scenario: AC-67.01 draft specs cannot enter implementation
    Given a queue item references a spec whose status is Draft
    When the readiness gate classifies the item
    Then the recommended lane is SPEC_POLISH
    And the readiness is SPEC_POLISH_REQUIRED
    And human_gate_required is true

  Scenario: AC-67.02 duplicate spec IDs block routing
    Given two indexed specs share the same spec number
    And a queue item references that spec number
    When the readiness gate classifies the item
    Then the readiness is INVALID_UNTIL_SPEC_ID_FIXED
    And the recommended lane is INVALID_UNTIL_SPEC_ID_FIXED

  Scenario: AC-67.03 bounded approved AC gaps can enter implementation
    Given a queue item references an approved spec
    And the referenced plan exists
    And the AC gap is classified as bounded implementation work
    When the readiness gate classifies the item
    Then the recommended lane is IMPLEMENT
    And the item includes a validation_command

  Scenario: AC-67.04 strict mode fails when no implementation candidates exist
    Given the queue has no items classified as IMPLEMENT_READY_CANDIDATE
    When the readiness gate runs with require-implement-ready enabled
    Then the command exits non-zero
```

### Criteria Checklist

- [ ] **AC-67.01**: Draft specs route to SPEC_POLISH, not IMPLEMENT.
- [ ] **AC-67.02**: Duplicate spec IDs block queue routing.
- [ ] **AC-67.03**: Bounded approved AC gaps can become IMPLEMENT candidates with validation commands.
- [ ] **AC-67.04**: Strict mode exits non-zero when no implementation candidates exist.

## 8. Dependencies & Integration Boundaries

| Dependency | Relationship | Contract |
|------------|--------------|----------|
| Spec index | Source of spec status and numbers | Must expose spec file, number, and status |
| Plan files | Source of plan existence | Referenced `plan_ref` must exist before IMPLEMENT |
| Queue JSON files | Gate input | Must include item id, spec reference, plan reference, and AC IDs when available |
| S65 local gate | Downstream validation | IMPLEMENT items should include validation commands compatible with local gate workflow |

## 9. Open Questions

1. Should the readiness gate mutate queue JSON with explicit metadata, or remain a read-only classifier that emits JSON for managers? — *Impact: moderate* — *Owner: orchestrator*
2. Should strict mode fail on any governance blocker, or only fail when no IMPLEMENT items exist? — *Impact: moderate* — *Owner: orchestrator*

## 10. Out of Scope

- Implementing the autonomous executor itself — this spec governs what it may consume.
- Solving every blocked queue item — each blocked item remains its own spec/plan/governance task.
- Running integration/live/eval gates — this spec classifies those lanes but does not execute them.
