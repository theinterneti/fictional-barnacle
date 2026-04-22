# S53 — Nexus Access Rules

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v4+
> **Implementation Fit**: ❌ Not Started
> **Level**: 1 — Core Game
> **Dependencies**: S52 (Nexus), S51 (Cross-Universe Travel), S50 (Concurrent Universe Loading)
> **Related**: S31 (Actor Identity Portability), S01 (Gameplay Loop)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

S53 defines the *conditions and paths* under which a player-actor may reach the
Nexus. S52 defines what the Nexus *is*; S53 defines *how you get there*.

The Nexus is a privilege, not a default. An actor who has just started their
first session should not immediately encounter it. Access is earned through
narrative engagement, enforced by mechanical gates, and always explainable
within the fiction.

---

## 2. Access Gate

An actor may reach the Nexus only if **all** of the following are true:

| Condition | Check | Notes |
|---|---|---|
| **Session threshold** | Actor has completed ≥1 non-Nexus session | A session is "completed" when the game reaches an ended/completed state |
| **Resonance fragment** | Actor holds a `resonance_fragment` inventory item | Earned by the actor during play; a world-object with in-universe meaning |
| **Universe permits departure** | Source universe manifest has `portal_exit_enabled: true` (default) | Allows individual universes to lock their actors in |

If any condition is unmet and a travel trigger fires, the trigger is consumed
(it happened narratively) but the crossing fails gracefully with an in-universe
explanation (the portal doesn't open, the ritual is incomplete, etc.).

---

## 3. Trigger Paths

Three trigger paths exist. All three respect the access gate.

### 3.1 Narrative Portal (LLM-generated)

When the LLM generates a world-model event of type `portal_to_nexus`, the
turn pipeline intercepts it before narration and checks the gate. If the gate
passes, the crossing is initiated via S51. If not, the pipeline substitutes a
"portal flickers but does not open" narration and discards the event.

The LLM may generate a `portal_to_nexus` event only when:
- The universe manifest declares `allow_narrative_portals: true` (default)
- The story arc (S05 narrative state) is in a phase marked as `threshold_eligible: true`

### 3.2 Player Ritual

Each universe manifest may define a `nexus_ritual` action sequence — a specific
combination of player actions that triggers Nexus travel. If the sequence is
completed and the gate passes, the crossing is initiated.

The ritual definition is narrative content (strings), not engine logic. Example:
```yaml
nexus_ritual:
  required_items: [resonance_fragment]
  required_location: threshold_zone
  action_sequence: [hold_fragment, speak_name, step_forward]
  narrative_confirmation: "The air shimmers. You feel the boundary thin."
```

If no `nexus_ritual` is defined in a universe, the player ritual path is
unavailable from that universe.

### 3.3 Admin Transfer

Administrators may force-transfer an actor to the Nexus regardless of gate
conditions via `POST /admin/actors/{id}/transfer` with `destination: nexus`.
Gate conditions are skipped. A staff note is logged.

---

## 4. Resonance Fragment

The `resonance_fragment` is a first-class item archetype defined in the S39
vocabulary as a `liminal_object`. It is:
- Awarded by the LLM as a narrative reward when a significant story arc closes
- Not purchasable, craftable, or transferable
- Unique per actor (at most one active at a time; acquiring a second replaces
  the first with a richer version)
- Carried in the echo memory pool across universes (flagged `cross_universe: true`)

---

## 5. Functional Requirements

### FR-53.01 — Gate Check

Before any Nexus crossing (regardless of trigger path), the `NexusAccessGate`
service performs the gate check. The result is `PERMITTED` or `DENIED(reason)`.
Gate checks MUST complete within 100 ms (Redis + Postgres reads).

### FR-53.02 — Graceful Failure Narration

When a gate check returns DENIED, the turn pipeline generates a graceful failure
narration. The narration must:
- Make sense within the universe's in-world logic
- Not reveal the mechanical gate to the player
- Leave the possibility of future access open

### FR-53.03 — Resonance Fragment Award

The LLM turn pipeline may emit a `resonance_fragment_award` world-model event
when story arc conditions warrant it. The pipeline intercepts this event,
grants the item to the actor's inventory, and includes a fragment discovery
narration in the turn output.

### FR-53.04 — Return from Nexus

Actors in the Nexus may return to their source universe at any time using
the `player_ritual` path (simplified — no fragment required for return)
or via an LLM-generated `portal_to_source` event. Return travel bypasses
gate conditions (the actor has already qualified).

---

## 6. Acceptance Criteria (Gherkin)

```gherkin
Feature: Nexus Access Rules

  Scenario: AC-53.01 — First-session actor cannot reach Nexus
    Given actor A has completed 0 sessions
    When a portal_to_nexus event is generated
    Then the gate returns DENIED
    And the narration does not reference the Nexus by name
    And the actor remains in the source universe

  Scenario: AC-53.02 — Actor with fragment and sessions passes gate
    Given actor A has completed 2 sessions and holds a resonance_fragment
    When a portal_to_nexus event is generated
    Then the gate returns PERMITTED
    And the crossing proceeds via S51

  Scenario: AC-53.03 — Admin transfer bypasses gate
    Given actor A has 0 sessions and no resonance_fragment
    When POST /admin/actors/{id}/transfer {destination: nexus} is called
    Then the actor is transferred to the Nexus
    And a staff note is logged

  Scenario: AC-53.04 — Resonance fragment is awarded on arc closure
    Given actor A completes a story arc that meets fragment award conditions
    When the LLM emits a resonance_fragment_award event
    Then the item is added to the actor's inventory
    And a fragment discovery narration is included in the turn output
```

---

## 7. Out of Scope

- The interior content of the Nexus (S52).
- What happens in the Nexus (LLM-generated narrative).
- Multiplayer co-presence in the Nexus (S57/S58).

---

## 8. Open Questions

| ID | Question | Status |
|---|----------|--------|
| OQ-53.01 | Should the resonance fragment be visible in a player-facing inventory UI? | 🔓 Open — deferred to v4 UX; engine tracks it regardless. |
| OQ-53.02 | Can a universe opt out of narrative portals entirely? | ✅ Resolved — yes, set `allow_narrative_portals: false` in manifest. |
