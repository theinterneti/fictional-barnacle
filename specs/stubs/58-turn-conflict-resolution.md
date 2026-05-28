# S58 — Turn Conflict Resolution

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v4+
> **Implementation Fit**: ❌ Not Started
> **Level**: 1 — Core Game
> **Dependencies**: S57 (Multi-Actor Universe Model), S05 (Narrative Engine), S08 (Turn Pipeline)
> **Related**: S59 (Multiplayer Transport)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

When two or more actors submit turns simultaneously in a shared universe (S57),
their intended actions may conflict at the world-state level. S58 defines the
strategies for detecting, classifying, and resolving such conflicts.

Conflicts in TTA are primarily *narrative* rather than mechanical. The resolution
goal is not to pick a winner but to produce a coherent story from concurrent
intent.

---

## 2. Conflict Classification

| Class | Description | Example |
|---|---|---|
| **Commutative** | Both actions can occur without logical conflict; order is irrelevant | A picks up sword; B speaks to NPC |
| **Sequential** | Both actions can occur but order matters for narrative coherence | A opens door; B enters same door |
| **Competitive** | Both actors intend to do the same thing with a unique resource | A and B both attempt to pick up the same item |
| **Contradictory** | One actor's action makes the other's impossible | A kills NPC; B attempts to speak to that NPC |

---

## 3. Resolution Strategies

### 3.1 Merge (for Commutative)

Both turns are processed in parallel. Their world-state writes are applied in
arrival order. No special handling required. The turn pipeline runs twice
independently and both outputs are delivered to their respective actors.

### 3.2 Priority (for Sequential and Competitive)

One actor's turn is processed first; the second actor receives the updated
world-state before their turn pipeline runs. Priority is determined by:
1. **Actor slot order** (first to join the roster has priority, as a tiebreaker)
2. **Narrative relevance** (the actor whose current story arc is most directly
   engaged with the resource gets priority)

Priority is resolved by the `TurnPriorityResolver` service before either
pipeline starts.

### 3.3 Narrative Reconciliation (for Contradictory)

Neither turn is processed in isolation. Instead, both actions are submitted
to a **reconciliation LLM call** that generates a single world-state outcome
and two personalized narrative beats (one per actor). The reconciliation
prompt receives:
- Both actors' intended actions
- Current world-state
- Both actors' recent narrative context

The reconciliation output is a `ReconciliationResult` containing:
- `world_state_delta`: the resulting world-state changes
- `narrative_a`: the narration Actor A receives
- `narrative_b`: the narration Actor B receives

---

## 4. Conflict Detection

Conflict detection runs after both turns have been received but before
any pipeline execution. The `ConflictDetector` analyzes the two turns'
world-model intents (parsed from the LLM's structured output) and
classifies the conflict.

Detection must complete within 50 ms (no LLM call; rule-based + world-state
read only).

---

## 5. Functional Requirements

### FR-58.01 — Turn Window

Concurrent turns are collected within a **turn window**: a configurable interval
(default: 2 seconds) after the first turn in a universe is submitted. All turns
submitted within the window are considered concurrent. The window exists to
avoid processing turns one-at-a-time when players act close together.

### FR-58.02 — Conflict Detection

The `ConflictDetector` classifies conflicts after the turn window closes.
Classification rules are based on world-model event types (create, update,
delete) targeting shared resources (items, NPCs, locations).

### FR-58.03 — Resolution Dispatch

Based on classification, the `TurnConflictResolver` dispatches to the
appropriate strategy (§3.1–3.3).

### FR-58.04 — Single-Actor Fast Path

If only one turn is in the window when it closes, conflict resolution is
skipped entirely (fast path). This is the common case and must add zero
latency to single-actor turns.

### FR-58.05 — Resolution Metrics

Prometheus counters:
- `tta_turn_conflict_total{conflict_class}` — conflicts by class
- `tta_turn_reconciliation_total` — reconciliation LLM calls

Prometheus histogram:
- `tta_turn_reconciliation_latency_seconds` — reconciliation LLM latency

---

## 6. Acceptance Criteria (Gherkin)

```gherkin
Feature: Turn Conflict Resolution

  Scenario: AC-58.01 — Commutative turns are merged
    Given Actor A submits a turn to pick up a sword
    And Actor B submits a turn to speak to an NPC (different resource)
    When the conflict detector runs
    Then the conflict class is Commutative
    And both turns are processed independently

  Scenario: AC-58.02 — Competitive turns use priority
    Given Actor A and Actor B both submit turns to pick up the same item
    When the conflict detector runs
    Then the conflict class is Competitive
    And the TurnPriorityResolver assigns one actor as first
    And the first actor's turn processes; the second receives updated state

  Scenario: AC-58.03 — Contradictory turns trigger reconciliation
    Given Actor A submits a turn to kill NPC Mira
    And Actor B submits a turn to speak to NPC Mira
    When the conflict detector runs
    Then the conflict class is Contradictory
    And a reconciliation LLM call produces narrative_a and narrative_b
    And Actor A and Actor B receive different narrations for the same world outcome

  Scenario: AC-58.04 — Single-actor fast path adds zero latency
    Given only Actor A submits a turn during the window
    When the window closes
    Then conflict resolution is skipped
    And Actor A's turn proceeds immediately
```

---

## 7. Out of Scope

- PvP or adversarial mechanics (actors are always collaborative in TTA).
- Turn queue ordering for 3+ actors (v4 targets 2 actors; 3+ is a v5+ concern).
- Real-time synchronization state visible to players (internal engine state).

---

## 8. Open Questions

| ID | Question | Status |
|---|----------|--------|
| OQ-58.01 | What is the maximum reconciliation wait before we timeout and deliver partial? | 🔓 Open — proposed 8s timeout; deferred to v4 impl tuning. |
| OQ-58.02 | Should reconciliation use a dedicated LLM model (cheaper/faster)? | 🔓 Open — yes, likely; model selection deferred to v4 LLM config. |
