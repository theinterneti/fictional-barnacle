# S56 — Resonance Correlation Engine

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v4+
> **Implementation Fit**: ❌ Not Started
> **Level**: 1 — Core Game
> **Dependencies**: S54 (Inter-Universe Event Substrate), S39 (Universe Composition), S37 (Memory Records)
> **Related**: S55 (Bleedthrough Propagation), S56 builds on S55 semantic layer
> **Last Updated**: 2026-04-21

---

## 1. Purpose

Where S55 propagates isolated events, S56 detects *persistent thematic patterns*
across universes — "resonances": moments when two or more universes are
independently exploring the same theme, archetype, or emotional territory.

A resonance is not a causal link. It is a statistical coincidence with narrative
weight: "Universe A has been full of stories about betrayal. Universe B, unknown
to Universe A, has also been full of stories about betrayal. The Resonance Engine
notices this and can surface it."

Resonances surface in gameplay as:
- Subtle changes in ambient tone (the LLM receives a resonance tag in context)
- Optional "echo moments": a character in Universe B feels a pang of something
  they can't quite name when betrayal is relevant
- Nexus enrichment: Wayfinder NPCs (S52) can describe active resonances when asked

---

## 2. Resonance Vocabulary

Resonances are identified by their **archetype label** — a term from the S39
universal archetype vocabulary. Example archetypes that can form resonances:
- `betrayal`, `sacrifice`, `homecoming`, `threshold_crossing`, `loss`
- `mentor_death`, `forbidden_knowledge`, `monster_within`

A resonance between Universe A and Universe B on archetype X exists when:
- Both universes have emitted ≥ 3 narrative events tagged with archetype X
  in the last **resonance_window** (default: 24 in-world hours)
- The events are from different session-actors (not one player driving both)

---

## 3. Resonance Lifecycle

```
ABSENT → EMERGING (3+ events in window) → ACTIVE → FADING → ABSENT
```

| State | Condition | Effect on gameplay |
|---|---|---|
| EMERGING | 3–5 events in window | Light touch; LLM context hint only |
| ACTIVE | 6+ events in window | Wayfinders can describe it; echo moments enabled |
| FADING | No new events for half the window | Reduced effect; ambient only |
| ABSENT | Window fully elapsed | No effect |

Resonance scores use exponential half-life decay:

```
score(t) = Σ events × e^(−λ × (t − event_time))
```

where λ = ln(2) / (window_seconds / 2). EMERGING threshold: score ≥ 1.0.
ACTIVE threshold: score ≥ 2.0.

---

## 4. Functional Requirements

### FR-56.01 — Event Tagging

During turn pipeline narrative event generation, the LLM tags each event with
up to 3 archetype labels from the S39 vocabulary. Tags are added to the event
metadata as `archetype_tags: list[str]`.

### FR-56.02 — Resonance Tracking

The `ResonanceCorrelationEngine` is a background service (ARQ job, S48) that
runs on a 5-minute schedule. It reads archetype tag events from the S54
substrate, updates resonance scores in Redis, and publishes `resonance_state_change`
events when a resonance transitions state.

### FR-56.03 — Context Injection

When a universe's turn pipeline executes, it queries active resonances for
that universe's archetype vocabulary. ACTIVE resonances are added to the LLM
context as `active_resonances: list[{archetype, strength}]`. The LLM is
instructed to weave these in lightly (not announce them).

### FR-56.04 — Nexus Disclosure

Wayfinder NPCs in the Nexus (S52) are given ACTIVE resonances for all loaded
universes in their NPC context. Players who ask Wayfinders about the multiverse
may receive resonance-informed responses.

### FR-56.05 — Echo Moments

When a session turn involves an event tagged with an ACTIVE resonance archetype,
the turn pipeline may inject an `echo_moment` prompt hint: a suggestion for
the LLM to include a brief, phenomenological reaction in the narration.
Echo moments are probabilistic (50% chance per eligible turn) to avoid repetition.

### FR-56.06 — Decay and Expiry

Resonance scores decay continuously. Expired resonances (score < 0.1) are
deleted from Redis. The 5-minute ARQ job also prunes expired resonances.

---

## 5. Acceptance Criteria (Gherkin)

```gherkin
Feature: Resonance Correlation Engine

  Scenario: AC-56.01 — Resonance EMERGES after threshold events
    Given Universe A and Universe B have each emitted 3 events tagged with betrayal
    When the ResonanceCorrelationEngine runs
    Then a resonance for betrayal between A and B transitions to EMERGING

  Scenario: AC-56.02 — Active resonance is injected into LLM context
    Given the betrayal resonance between A and B is ACTIVE
    When Universe A processes a turn
    Then active_resonances includes {archetype: betrayal, strength: ...}
    And the LLM context includes the resonance hint

  Scenario: AC-56.03 — Resonance decays when events stop
    Given an ACTIVE resonance with no new events for > resonance_window
    When the decay job runs
    Then the resonance score drops below 0.1
    And the resonance is pruned from Redis

  Scenario: AC-56.04 — Wayfinder can describe active resonances
    Given the betrayal resonance is ACTIVE
    And an actor in the Nexus asks a Wayfinder about the state of the multiverse
    Then the Wayfinder's NPC context includes the betrayal resonance
    And the LLM response may reference the theme without naming source universes
```

---

## 6. Out of Scope

- Cross-universe causal narratives (resonances are observational, not causal).
- Player-visible resonance dashboards (internal engine state only).
- Resonances involving a single universe (requires ≥2 universes).

---

## 7. Open Questions

| ID | Question | Status |
|---|----------|--------|
| OQ-56.01 | Should resonance scores be persisted across server restarts? | 🔓 Open — Redis AOF covers this if enabled; no special handling needed. |
| OQ-56.02 | How are resonances evaluated in the S45 pipeline? | 🔓 Open — proposed: resonance activation rate as a derived metric from session logs. |
