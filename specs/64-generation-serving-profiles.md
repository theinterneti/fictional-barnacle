# S64 — Generation Serving Profiles

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.2
> **Implementation Fit**: ❌ Not Started
> **Level**: 2 — AI & Content
> **Dependencies**: S07 (LLM Integration), S10 (API & Streaming), S11 (Player Identity & Sessions), S15 (Observability), S23 (Error Handling & Resilience), S42 (LLM Playtester Agent Harness), S45 (Evaluation Pipeline), S50 (Rate-Limit Budget & Task Prioritization)
> **Related**: `plans/llm-and-pipeline.md`, `plans/v2_1-evaluation-and-playtesting.md`
> **Last Updated**: 2026-05-25

---

## 1. Purpose

TTA needs an explicit, user-meaningful way to trade response speed against
narrative richness. Today that tradeoff is implicit and inconsistent: some
callers route narrative generation through latency-sensitive paths, others use
creative-quality paths, and batch evaluation traffic can accidentally compete
with player-facing sessions.

S64 defines **generation serving profiles** as a product-level contract for that
tradeoff. A serving profile expresses what kind of generation experience is
being requested — `fast`, `balanced`, or `quality` — and the system uses that
profile to choose routing policy, latency budget, fallback behavior, and
observability.

This spec is deliberately about **policy**, not model IDs. Players and internal
callers choose a profile; the router and operator configuration choose specific
models within that profile's envelope.

---

## 2. Design Principles

### 2.1 Correctness Is Not Adjustable

Serving profiles affect narrative-generation policy only. They MUST NOT change
world-state correctness, persistence semantics, moderation behavior, extraction
correctness, or save/resume integrity.

### 2.2 Profiles Are Product Promises

`fast`, `balanced`, and `quality` are not internal implementation details. They
are stable promises about the expected latency/quality tradeoff of narrative
output. The internal routing stack may change over time, but the behavioral
meaning of each profile must stay legible.

### 2.3 The Frontier Must Be Measured, Not Assumed

The system MUST support empirical comparison of serving profiles on the same
seeds, personas, and inputs. Operators should be able to answer: "What latency
increase bought what quality gain?"

### 2.4 Degradation Must Be Explicit

When the requested profile cannot be satisfied, the system MAY degrade to a
lower profile according to explicit rules. Silent policy drift is not allowed.
Requested profile, effective profile, and degradation reason must be recorded.

### 2.5 Interactive and Batch Work Are Different Products

A human or live smoke test validating player experience is not the same thing as
bulk automated playtesting. The system MUST support profile-aware evaluation so
that bulk runs do not inherit interactive serving assumptions by accident.

---

## 3. User Stories

### US-64.1 — Player prefers quick responses

As a player, I want a quick-response mode so that the story keeps moving even if
prose quality is slightly less rich.

### US-64.2 — Player prefers richer narration

As a player, I want a richer-narration mode so that I can accept longer waits
when I care more about style and depth.

### US-64.3 — Operator compares the tradeoff frontier

As an operator, I want to compare `fast`, `balanced`, and `quality` on the same
scenarios so that I can make routing decisions using evidence instead of taste.

### US-64.4 — Developer isolates batch evaluation traffic

As a developer, I want bulk automated playtests to use an explicit serving
profile so that evaluation traffic does not distort player-facing latency paths.

### US-64.5 — Future UI slider has stable semantics

As a product designer, I want the eventual player slider to map to stable serving
profiles so that the UI does not expose raw model or routing internals.

---

## 4. Canonical Serving Profiles

The system defines three canonical generation serving profiles:

| Profile | Player-facing meaning | Primary promise |
|---|---|---|
| `fast` | "Respond quickly" | Lowest latency and highest completion resilience |
| `balanced` | "Default experience" | Good narrative quality without large latency spikes |
| `quality` | "Take more time for richer prose" | Higher narrative richness with more tolerance for latency |

These names are normative internal identifiers. User-facing labels MAY differ
(e.g. "Quick", "Balanced", "Rich"), but must map cleanly to these three
profiles.

### FR-64.01 — Canonical profile enum

The system SHALL define `fast`, `balanced`, and `quality` as the only canonical
v2.2 generation serving profiles.

### FR-64.02 — Default profile

If a caller does not specify a generation serving profile, the system SHALL use
`balanced` as the default.

### FR-64.03 — Future slider compatibility

Any future continuous UI control SHALL map onto these canonical profiles or a
forward-compatible extension of them. The UI SHALL NOT bind directly to model
IDs or provider names.

---

## 5. Behavioral Scope and Invariants

### FR-64.04 — Scope of profile influence

Generation serving profiles SHALL govern the policy used for narrative
generation tasks, including:
- router task hints for generation calls
- latency and timeout budgets for generation calls
- dispatch preference (e.g. sync vs queue-tolerant)
- fallback/degradation policy for generation calls
- token/output budgets for generation calls
- observability labels and evaluation reporting for generation calls

### FR-64.05 — Correctness invariants

Generation serving profiles SHALL NOT alter:
- game rules or state-transition logic
- extraction/classification correctness requirements
- moderation and safety decisions
- persistence, save, restore, or resume semantics
- error taxonomy between permanent and transient failures

### FR-64.06 — Non-generation tasks remain explicit

If a non-generation stage is ever allowed to vary by serving profile, that
behavior MUST be specified explicitly in a future revision. It is not implied by
v2.2.

---

## 6. Routing and Degradation Contract

### FR-64.07 — Policy envelope, not model selection

Serving profiles SHALL resolve to a **policy envelope** rather than a concrete
model ID. The policy envelope defines the routing semantics that FMR and the
LLM client use to select a model.

### FR-64.08 — Profile-specific routing semantics

Each profile SHALL define, at minimum:
- router task hint for narrative generation
- latency sensitivity / latency class
- dispatch preference
- timeout budget
- output token budget
- allowed fallback/degradation targets

The exact values are implementation-defined in the technical plan.

### FR-64.09 — Explicit degradation rules

If a requested profile cannot be satisfied, the system MAY degrade only along
an explicit path:
- `quality -> balanced -> fast`
- `balanced -> fast`
- `fast` has no lower profile

Any degradation SHALL be recorded in logs and observability fields with:
- requested profile
- effective profile
- degradation reason

### FR-64.10 — No silent premium escalation

A `fast` request SHALL NOT be silently treated as `quality` if doing so would
materially violate the `fast` latency envelope. Opportunistic model upgrades are
allowed only if they stay within the requested profile's latency contract.

### FR-64.11 — Graceful failure after profile exhaustion

If the requested profile and all allowed degradation targets are unavailable,
the system SHALL fail using the existing LLM/resilience contract from S07 and
S23 rather than fabricating placeholder narrative.

---

## 7. API, Session, and Preference Semantics

### FR-64.12 — Session-scoped preference

The system SHALL support an optional generation serving profile at session scope
for player-facing gameplay sessions.

### FR-64.13 — Request override

The system MAY support a per-request override for operator and evaluation tools,
but the override SHALL be explicit and validated against the canonical profile
enum.

### FR-64.14 — Persisted preference fields

If a gameplay session or player preference stores a generation serving profile,
the stored value SHALL use the canonical internal identifier (`fast`,
`balanced`, `quality`).

### FR-64.15 — Unavailable profile handling

If a caller requests an invalid or unsupported profile, the system SHALL reject
the request with a validation error rather than silently coercing it.

---

## 8. Playtesting and Evaluation Semantics

### FR-64.16 — Profile-aware batch planning

The evaluation pipeline SHALL support planning and reporting batches by serving
profile. Operators MUST be able to run the same seed/persona matrix under
multiple profiles.

### FR-64.17 — Distinct evaluation run classes

The system SHALL support at least these run classes:
- interactive smoke runs validating player-facing behavior
- bulk evaluation runs measuring throughput, stability, and quality at scale
- premium narrative benchmark runs focused on richer-prose policies

These run classes MAY reuse the same game API, but MUST carry explicit serving
profile and run-class metadata.

### FR-64.18 — Frontier-comparison outputs

Evaluation artifacts SHALL make it possible to compare profiles on the same
input set for:
- latency distribution
- completion/error rate
- fallback/degradation rate
- quality scores
- human preference data when available

### FR-64.19 — Batch traffic isolation

Bulk automated playtesting SHALL NOT rely on the same implicit routing policy as
interactive player traffic. It MUST use an explicit generation serving profile.

---

## 9. Observability and Analytics

### FR-64.20 — Per-call observability fields

Every generation call SHALL record:
- requested serving profile
- effective serving profile
- whether degradation occurred
- degradation reason (if any)
- requested run class / traffic class if available
- model actually used
- latency and token counts

### FR-64.21 — Batch/profile aggregates

The system SHALL expose aggregate metrics by serving profile for:
- call count
- completion rate
- fallback rate
- degradation rate
- latency percentiles
- quality-report medians where applicable

### FR-64.22 — Evaluation trace labels

Langfuse traces and exported evaluation artifacts SHALL include serving-profile
labels so that long-term comparison by profile is possible.

---

## 10. Non-Functional Requirements

### NFR-64.01 — Profile stability

The semantic meaning of `fast`, `balanced`, and `quality` MUST remain stable
across releases. Operators may retune internals, but the perceived product
contract must not drift arbitrarily.

### NFR-64.02 — Healthy-supply latency targets

Under healthy model supply and absent system overload, default profile targets
SHALL be measurable and operator-visible. Suggested defaults for v2.2:
- `fast`: optimized for lowest turn latency
- `balanced`: optimized for stable default play
- `quality`: optimized for richer prose with relaxed latency tolerance

Exact numeric targets are defined in the technical plan and may evolve with
empirical data.

### NFR-64.03 — No hidden coupling to provider names

No user-facing profile semantics SHALL depend on a specific provider or model
family being available.

### NFR-64.04 — Comparison reproducibility

Evaluation runs comparing multiple profiles SHALL be reproducible on the same
scenario seeds, personas, and input scripts so that frontier analysis is valid.

---

## 11. User Journeys

### Journey 1 — Player starts a session with the default profile

Trigger: a player creates a new game without specifying a serving profile.

1. Player starts a new session.
2. System applies the default profile `balanced`.
3. Narrative generation requests carry `requested_profile=balanced`.
4. The turn completes normally.
5. Observability records the requested and effective profile.

Happy path: the player receives the standard experience without needing to think
about routing internals.

Alternative path: if `balanced` is temporarily unavailable, the system degrades
to `fast`, logs the degradation, and still completes the turn if possible.

### Journey 2 — Operator runs a profile comparison batch

Trigger: an operator runs evaluation across `fast`, `balanced`, and `quality`.

1. Operator configures a shared seed/persona matrix.
2. Pipeline runs the same matrix under each profile.
3. Results are exported with profile labels.
4. Operator compares latency, completion rate, and quality medians.
5. Operator updates serving policy based on measured tradeoffs.

Happy path: the operator obtains a comparable latency/quality frontier rather
than anecdotal impressions.

### Journey 3 — Quality request degrades gracefully under supply pressure

Trigger: a player or benchmark requests `quality` while the quality envelope is
unavailable.

1. Caller requests `quality`.
2. System determines the `quality` envelope is not currently satisfiable.
3. System degrades to `balanced` per allowed degradation path.
4. The turn completes under `effective_profile=balanced`.
5. Logs, traces, and metrics record the degradation reason.

Happy path: the session continues with a documented downgrade rather than an
opaque failure.

Alternative path: if `balanced` and `fast` are also unavailable, the request
fails under the normal resilience contract.

---

## 12. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | Caller submits unknown profile `ultra` | Validation error; request is rejected |
| E2 | `quality` profile unavailable mid-session | Degrade to `balanced` or `fast` per policy; record reason |
| E3 | `fast` profile has a stronger model available | Allowed only if latency contract is preserved; effective profile remains `fast` |
| E4 | Bulk eval forgets to specify a profile | Pipeline defaults to `balanced` and logs the defaulting decision |
| E5 | Different clients use different implicit task mappings | Forbidden by this spec; profile contract must be centralized |
| E6 | Resume/save path restores a session with stored profile | Restored session resumes with the same canonical profile unless explicitly overridden |
| E7 | Quality benchmark and interactive smoke share the same transport path | Allowed if run-class/profile metadata remain explicit and routing policies stay distinct |
| E8 | Provider/model pool changes across releases | Allowed as long as profile semantics and observability remain stable |

---

## 13. Acceptance Criteria (Gherkin)

```gherkin
Feature: Generation Serving Profiles

  Scenario: AC-64.01 — Default generation profile is balanced
    Given a gameplay session is created without a generation serving profile
    When the first narrative generation request is issued
    Then the requested serving profile is "balanced"

  Scenario: AC-64.02 — Invalid profile is rejected
    Given a caller submits generation_profile = "ultra"
    When the request is validated
    Then the system returns a validation error
    And no generation request is dispatched

  Scenario: AC-64.03 — Quality can degrade to balanced
    Given a caller requests generation_profile = "quality"
    And the quality policy envelope is unavailable
    When generation is dispatched
    Then the effective serving profile is "balanced"
    And the degradation reason is recorded

  Scenario: AC-64.04 — Fast does not silently become quality
    Given a caller requests generation_profile = "fast"
    When generation is dispatched
    Then the effective serving profile is never set to "quality"
    Unless the request still satisfies the fast latency contract

  Scenario: AC-64.05 — Serving profile does not change correctness stages
    Given the same player input and world state
    When generation is run under fast, balanced, and quality
    Then extraction and persistence semantics remain unchanged
    And only generation-policy behavior may differ

  Scenario: AC-64.06 — Evaluation pipeline can compare profiles on the same matrix
    Given a batch config with a fixed seed and persona matrix
    When the evaluation pipeline runs that matrix for fast, balanced, and quality
    Then the output artifacts include per-profile results for the same inputs

  Scenario: AC-64.07 — Bulk playtesting uses an explicit profile
    Given an automated bulk playtest batch
    When generation requests are dispatched
    Then each request includes an explicit serving profile
    And batch traffic does not depend on an implicit interactive routing policy

  Scenario: AC-64.08 — Observability records requested and effective profiles
    Given any narrative generation call
    When the call completes or fails
    Then logs and traces include requested_profile and effective_profile
```

### Criteria Checklist
- [ ] **AC-64.01**: Default profile is `balanced`
- [ ] **AC-64.02**: Invalid profiles are rejected
- [ ] **AC-64.03**: Explicit degradation path is enforced
- [ ] **AC-64.04**: `fast` is not silently treated as `quality`
- [ ] **AC-64.05**: Correctness semantics are invariant across profiles
- [ ] **AC-64.06**: Evaluation can compare profiles on the same matrix
- [ ] **AC-64.07**: Bulk playtesting uses explicit profile metadata
- [ ] **AC-64.08**: Observability records requested/effective profile

---

## 14. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|------|-------------|----------|
| S07 | Extends LLM role-based routing with profile-aware generation policy | S64 constrains how `generation` role requests are routed and observed |
| S10 | Defines how profile metadata enters request/response APIs | Session/request fields and validation must be API-visible where exposed |
| S11 | Governs any persisted player/session preference | Canonical profile IDs may be stored with session/player state |
| S15 | Provides metrics and traces | Requested/effective profile labels must be observable |
| S23 | Supplies failure taxonomy and graceful-failure behavior | Profile exhaustion still uses existing resilience semantics |
| S42 | Playtester agent uses profile-aware generation requests | Automated playtester traffic must carry explicit profile metadata |
| S45 | Evaluation pipeline compares profiles | Batch outputs and Langfuse export must be profile-aware |
| S50 | Coordinates concurrency and traffic priority | Serving profiles coexist with task-priority tiers; neither replaces the other |

---

## 15. Open Questions

| ID | Question | Impact | Owner |
|---|----------|--------|-------|
| OQ-64.01 | Should player-facing sessions expose profile selection at create-time, resume-time, or both in v2.2? | High | Product + API |
| OQ-64.02 | Should `quality` be allowed to use comparison dispatch by default, or only in benchmarks? | High | Routing / Ops |
| OQ-64.03 | Do we want a fourth internal profile later (e.g. `ultra_quality` or `economy`), or should v2.2 stay fixed at three? | Moderate | Product |
| OQ-64.04 | Which numeric latency targets are realistic for each profile on the current free-model pool? | High | Ops / Eval |
| OQ-64.05 | Should profile preference be stored at player scope, session scope, or both? | Moderate | Product + API |

---

## 16. Out of Scope

- Direct user-facing slider UI — deferred until profile semantics and frontier data are validated.
- Arbitrary user selection of specific model IDs or providers — hidden behind policy envelopes by design.
- Retuning extraction/classification/summarization by profile — unchanged in v2.2 unless separately specified.
- Commercial pricing or monetization tied to profiles — not part of this spec.
- Non-generation personalization knobs such as tone or verbosity sliders — separate product features.

---

## Appendix

### A. Glossary

- **Serving profile**: a stable generation policy contract (`fast`, `balanced`,
  `quality`) chosen by a caller or user.
- **Requested profile**: the profile asked for by the caller.
- **Effective profile**: the profile actually used after any allowed degradation.
- **Policy envelope**: the routing/timeout/fallback semantics associated with a
  profile.
- **Frontier**: the measured tradeoff curve between latency, completion
  resilience, and narrative quality.

### B. References

- `specs/07-llm-integration.md`
- `specs/45-evaluation-pipeline.md`
- `specs/50-rate-limit-budget.md`
- `plans/llm-and-pipeline.md`
- `plans/v2_1-evaluation-and-playtesting.md`

### C. Structural Notes

This spec intentionally defines the product contract for generation serving
profiles without locking implementation details such as exact tenant names,
provider pools, or token budgets. Those are specified in the technical plan.
