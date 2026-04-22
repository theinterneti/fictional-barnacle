# S55 — Bleedthrough Propagation Rules

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v4+
> **Implementation Fit**: ❌ Not Started
> **Level**: 1 — Core Game
> **Dependencies**: S54 (Inter-Universe Event Substrate), S05 (Narrative Engine), S39 (Universe Composition)
> **Related**: S56 (Resonance Correlation Engine)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

*Bleedthrough* is the phenomenon where an event or choice in Universe A creates
a subtle, distorted echo in Universe B — not a direct causal link, but a thematic
ripple. A hero's victory in Universe A might manifest in Universe B as a rumor
of distant drums, an inexplicable sense of triumph felt by a stranger, or a brief
shimmer in the sky.

S55 defines the rules by which bleedthrough events are generated, filtered,
distorted, and injected into receiving universes' narrative pipelines.

Bleedthrough is **optional enrichment**, not a required mechanic. If the S54
substrate is down or bleedthrough is disabled for a universe, the game degrades
gracefully with no visible change to the player.

---

## 2. Bleedthrough Pipeline

```
Source universe: narrative event occurs
        ↓
BleeedthroughFilter: is this event eligible for bleedthrough?
        ↓ (yes)
BleedthroughDistorter: apply thematic distortion
        ↓
S54 substrate: publish to tta:multiverse:events as event_type=bleedthrough
        ↓
Receiving universe: BleedthroughInjector checks relevance threshold
        ↓ (above threshold)
Turn pipeline: inject as ambient_event into next turn context
```

Each stage is independently configurable per universe via the manifest.

---

## 3. Eligibility Filter

A narrative event in Universe A is eligible for bleedthrough if:
1. The event's `narrative_significance` score (0–1, assigned by LLM) ≥ `bleedthrough_threshold`
   (default: 0.7; configurable per universe in manifest)
2. The universe manifest has `emit_bleedthrough: true` (default: true)
3. At least one other universe is currently ACTIVE (S50)

Event types always eligible (regardless of significance score):
- `story_arc_closed` — a major arc completes
- `resonance_fragment_awarded` — a fragment is granted
- `character_death` — a significant character dies

---

## 4. Thematic Distortion

Before publishing, the event's payload is distorted to lose specificity:
- Named entities (characters, places) are replaced with thematic archetypes
  from the source universe's S39 vocabulary
- Specific facts are replaced with impressionistic language
  ("a great struggle" replaces "the Battle of Veldran")
- Distortion intensity is drawn from a configurable probability distribution
  (`bleedthrough_distortion_level`: low/medium/high; default: medium)

Distortion is performed by a dedicated LLM call (short, fast prompt) that
takes the raw event summary and returns a distorted fragment string. This
fragment becomes the `bleedthrough_fragment` field in the S54 event payload.

---

## 5. Injection into Receiving Universe

When a receiving universe's `BleedthroughInjector` receives a bleedthrough
event from S54:
1. It computes a relevance score based on thematic overlap between the
   fragment's archetypes and the receiving universe's S39 vocabulary
2. If relevance ≥ `bleedthrough_reception_threshold` (default: 0.4), the
   fragment is added to the next turn's `ambient_events` list
3. The LLM turn pipeline surfaces ambient events as optional flavor that
   the LLM may or may not weave into narration

Ambient events are **suggestions**, not commands. The LLM may ignore them
if they don't fit the current narrative beat.

---

## 6. Functional Requirements

### FR-55.01 — Eligibility Check

The `BleedthroughFilter` runs synchronously within the turn pipeline after
narrative event generation. Filter check MUST complete within 20 ms (no LLM,
no network). Eligibility is determined by inspecting the event object.

### FR-55.02 — Distortion LLM Call

Distortion is performed by a fire-and-forget async LLM call (S07 LiteLLM).
If the call fails, the event is not published (bleedthrough is skipped for
that event). The main turn pipeline does NOT await this call.

### FR-55.03 — At-Most-Once Injection

Each bleedthrough event is injected into a receiving universe's next turn at
most once, even if the receiving universe has multiple active actors. The
first actor's turn that fires after the event arrives consumes it.

### FR-55.04 — Disable Toggle

A universe may set `receive_bleedthrough: false` in its manifest to refuse all
incoming bleedthrough events. This is useful for high-realism universes where
inexplicable phenomena would break immersion.

---

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: Bleedthrough Propagation

  Scenario: AC-55.01 — High-significance event triggers bleedthrough
    Given a story_arc_closed event in Universe A (significance = 1.0)
    When the BleedthroughFilter evaluates it
    Then the event is eligible for bleedthrough
    And a distortion LLM call is initiated

  Scenario: AC-55.02 — Low-significance event is filtered out
    Given a mundane NPC dialogue event (significance = 0.2)
    When the BleedthroughFilter evaluates it
    Then the event is NOT eligible for bleedthrough

  Scenario: AC-55.03 — Distorted fragment is injected into relevant universe
    Given Universe B's vocabulary has high thematic overlap with the fragment
    When Universe B's BleedthroughInjector receives the event
    Then the fragment is added to the next turn's ambient_events

  Scenario: AC-55.04 — Universe with receive_bleedthrough=false ignores events
    Given Universe C has receive_bleedthrough = false in its manifest
    When a bleedthrough event arrives for Universe C
    Then Universe C discards it without logging a warning
```

---

## 8. Out of Scope

- Causal links between universes (bleedthrough is thematic, not causal).
- Player visibility of bleedthrough origin (players never know what universe
  an ambient event came from).
- Bleedthrough event history or replay.

---

## 9. Open Questions

| ID | Question | Status |
|---|----------|--------|
| OQ-55.01 | Should distortion prompt be a named S09 prompt template? | ✅ Resolved — yes; registered as `bleedthrough_distortion` in the prompt registry. |
| OQ-55.02 | How do we measure bleedthrough quality in evaluation (S45)? | 🔓 Open — proposed metric: human rater scores fragment plausibility; deferred to v4 eval design. |
