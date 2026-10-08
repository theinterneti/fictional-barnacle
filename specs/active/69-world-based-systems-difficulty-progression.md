# S69 — World-Based Systems, Narrative Failure, and Milestones

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.1 → v3
> **Implementation Fit**: ❌ Not Started
> **Level**: 4 — Systems, Difficulty & Progression
> **Dependencies**: S01 (Gameplay Loop), S02 (Genesis Onboarding), S03 (Narrative Engine), S05 (Choice & Consequence), S06 (Character System), S11 (Player Identity & Sessions), S12 (Persistence Strategy), S27 (Save/Load & Game Management), S39 (Universe Composition Model), S66 (Rate-Limit Budget & Task Prioritization)
> **Related**: `docs/vision/TTA-THREADS.md` Game Systems, Difficulty & Failure, Progression & Achievements threads
> **Last Updated**: 2026-05-28

---

## 1. Purpose

The vision says systems, difficulty, and progression begin before v4. The current spec portfolio mostly treats TTA as pure narrative simulation, leaving no contract for ability checks, failure handling, difficulty preference, or milestone recognition. This spec defines the v2.1/v3 bridge: infer lightweight world-based mechanics from Genesis and current world state, resolve uncertain actions as narrative checks, treat death/failure as configurable story consequences, and record milestones without importing a full tabletop rules engine.

This is deliberately not a D&D/5e implementation. It creates the seam that v3 can use for an OSS rules baseline while preserving narrative-only play.

## 2. User Stories

- **As a** player, **I want** the game to understand what kinds of abilities matter in my world, **so that** a wizard tower, cyberpunk city, and cozy mystery do not use the same generic mechanics.
- **As a** player, **I want** failure to create story consequences instead of abrupt punishment, **so that** risk can exist without breaking the intended narrative tone.
- **As a** player, **I want** milestones to recognize discoveries and accomplishments, **so that** progress feels visible even before formal XP or achievements exist.
- **As a** developer, **I want** a mechanics seam independent of the narrative engine, **so that** future OSS rules plugins can be added without rewriting turn generation.

## 3. Functional Requirements

### FR-69.01 — World-based system profile

Each universe MAY have a `system_profile` derived from Genesis/world composition. For v2.1 this derivation is deterministic from S39 composition fields, S02 Genesis tags, and known character/world facts; LLM profile inference is deferred unless a later plan explicitly budgets it under S66. The required v2.1 profile shape is:

```yaml
system_profile:
  mode: narrative_only | world_based
  domains: [physical, social, knowledge, magic, technology, survival, mystery]
  world_labels: { domain: player_facing_label }
  genre_blend: [string]
  confidence: high | medium | low
```

The default mapping is rule-based: survival/frontier composition enables `survival`; fantasy/arcane composition enables `magic`; science-fiction/cyberpunk composition enables `technology`; investigation/mystery composition enables `mystery`; all worlds support `physical`, `social`, and `knowledge` unless explicitly disabled by the universe manifest.

### FR-69.02 — Player preference override

During Genesis or settings, a player MAY choose `narrative_only` or `world_based`. These preferences live in the S11 player `preferences` JSON under `tta.systems.play_mode` and may be copied into a game/session snapshot for reproducibility. Future explicit rulesets are v3+ and MUST NOT appear as selectable v2.1 values until implemented.

### FR-69.03 — Action risk classification

Before resolving a player action, the system SHALL classify whether the action is `trivial`, `uncertain`, `risky`, or `impossible` under the current world state. v2.1 classification is deterministic/hybrid without a mandatory LLM call: explicit route/blocker/safety/world-state constraints decide `impossible`; direct low-stakes actions become `trivial`; actions with meaningful uncertainty become `uncertain`; actions with plausible harm/loss/state change become `risky`. If an LLM classifier is later used, it MUST use a named prompt template and a fallback to this deterministic classifier. Only uncertain or risky actions require a mechanics resolution step.

### FR-69.04 — Narrative check resolution

For uncertain/risky actions in `world_based` mode, the system SHALL produce a typed resolution result consumed by S03/S08 as structured turn context, not prose:

```yaml
MechanicsResolution:
  resolution_id: string
  risk_level: trivial | uncertain | risky | impossible
  result: success | success_with_cost | partial_success | failure_with_consequence | impossible
  domain: physical | social | knowledge | magic | technology | survival | mystery
  stakes: none | inconvenience | resource_loss | injury | relationship_change | location_change | story_branch
  consequence_summary:
    state_delta: string
    narrative_constraint: string
    player_explanation: string | null
  influenced_by_preferences: [play_mode, death_preference]
```

The narrative engine may phrase the outcome creatively, but it must preserve the `result`, `stakes`, and `state_delta` semantics.

### FR-69.05 — Death and severe failure boundary

In v2.1, player death is a narrative event, not an automatic game over. The player can configure `no_death` or `story_consequences` in S11 `preferences` under `tta.systems.death_preference`. Future `system_default` behavior is reserved for v3 rulesets and MUST NOT be exposed as a v2.1 selectable value. In `no_death`, lethal outcomes become injury, capture, loss, interruption, or transformation appropriate to the world.

### FR-69.06 — Milestone tracking

The system SHALL record lightweight milestones for turn count, first location discovery, first NPC meaningful interaction, first resolved risky action, major faction event, and completed narrative arc when such events are detectable. Milestones persist with the saved game/session under S27 and use S12 persistence primitives; player-wide milestones MAY also be mirrored to the S11 player profile when explicitly marked `scope: player`. Required v2.1 dedup keys are `game:{game_id}:turn_count:{threshold}`, `game:{game_id}:location:{location_id}`, `game:{game_id}:npc:{npc_id}:meaningful_interaction`, `game:{game_id}:first_risky_action`, `game:{game_id}:faction:{faction_id}:major_event`, and `game:{game_id}:arc:{arc_id}:completed`.

### FR-69.07 — Mechanics/narrative separation

The mechanics resolver SHALL output structured facts and constraints to the narrative engine. It MUST NOT generate final prose directly and MUST NOT bypass S03/S08 narrative generation boundaries.

### FR-69.08 — Observability and explainability

Every mechanics resolution SHALL emit structured debug data: mode, domain, risk level, resolution result, stakes, and whether player difficulty/death preferences influenced the result. Player-facing explanation MAY be concise but must be available for any `failure_with_consequence`, `impossible`, `injury`, `resource_loss`, `relationship_change`, or `location_change` outcome.

## 4. Non-Functional Requirements

### NFR-69.01 — Low latency

**Category**: Performance

**Target**: Mechanics classification and resolution add no more than 500 ms p95 when using deterministic/local logic. If an LLM is used for classification in a later plan, the call must be budgeted under S66 as HIGH or LOW priority and must not compete with CRITICAL narrative-turn generation unless explicitly approved.

### NFR-69.02 — Genre neutrality

**Category**: Product quality

**Target**: The system profile supports non-combat worlds without making combat the default mechanics lens.

### NFR-69.03 — Plugin-ready seam

**Category**: Extensibility

**Target**: The resolver interface is named `MechanicsResolverProtocol` and returns `MechanicsResolution`, allowing a future OSS rules plugin to replace the v2.1 resolver without changing the narrative engine contract.

## 5. User Journeys

### Journey 1: Risky action in a world-based fantasy setting

- **Trigger**: Player tries to leap across a broken bridge while fleeing.
- **Steps**:
  1. System classifies the action as risky and physical/survival-related.
  2. Resolver produces `success_with_cost` or `failure_with_consequence` based on world state and character facts.
  3. Narrative engine receives the result and writes the scene outcome.
  4. Milestone tracker may record first risky action resolved.
- **Happy path**: The outcome feels grounded in the world and preserves story momentum.
- **Alternative paths**: If `no_death` is enabled, a lethal fall becomes injury, separation, lost gear, or rescue/capture.

### Journey 2: Player prefers narrative-only play

- **Trigger**: Player selects narrative-only during Genesis/settings.
- **Steps**:
  1. Universe still records a system profile for future compatibility.
  2. Turn processing skips explicit mechanics resolution unless the action is impossible.
  3. Milestones still record discoveries and story progress.
- **Happy path**: The game remains low-crunch while preserving future migration data.

## 6. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | Genesis cannot infer a useful system profile | Default to `narrative_only` with a generic profile and log the inference gap. |
| E2 | Player attempts an impossible action | Resolver returns `impossible` with a world-state reason for the narrative engine. |
| E3 | Player toggles death preference mid-game | New preference applies to future turns; historical outcomes are not rewritten. |
| E4 | Milestone event is detected twice | Milestone store deduplicates by milestone key and game/session/player scope, depending on the milestone type. |
| E5 | World supports magic and technology | System profile can include multiple domains; resolver picks the relevant domain per action. |
| E6 | Mechanics result conflicts with narrative safety/moderation | Safety/moderation boundary wins; mechanics result is revised or blocked. |
| E7 | Future explicit ruleset is selected before implemented | Settings reject it or mark it unavailable; no silent fallback that misleads the player. |

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: World-based systems, narrative failure, and milestones

  Scenario: AC-69.01 Genesis produces a world-based system profile
    Given a universe has Genesis output describing genre, tone, character capabilities, and world constraints
    When the system profile is derived
    Then the profile includes one or more mechanics domains relevant to that world
    And the selected play mode is stored as narrative_only or world_based

  Scenario: AC-69.02 risky actions produce structured resolution results
    Given a player attempts an uncertain or risky action in world_based mode
    When the mechanics resolver runs
    Then it returns one of success, success_with_cost, partial_success, failure_with_consequence, or impossible
    And the result includes domain, stakes, and consequence summary

  Scenario: AC-69.03 no-death preference prevents abrupt game over
    Given the player's death preference is no_death
    And a risky action would otherwise produce lethal failure
    When the resolver produces the outcome
    Then the final consequence is injury, capture, loss, interruption, or transformation
    And the game remains playable

  Scenario: AC-69.04 narrative-only mode skips explicit mechanics checks
    Given the player selected narrative_only mode
    When the player attempts a normal non-impossible action
    Then no explicit mechanics resolution is required
    And the narrative engine resolves the action through existing story logic

  Scenario: AC-69.05 milestones are recorded once
    Given a player discovers a new location for the first time
    When milestone tracking runs
    Then a location discovery milestone is recorded
    And repeating the same discovery does not create a duplicate milestone

  Scenario: AC-69.06 mechanics do not generate final prose
    Given the resolver has produced a structured action result
    When turn generation continues
    Then the narrative engine receives the result as input context
    And final player-facing prose is generated by the narrative pipeline
```

### Criteria Checklist

- [ ] **AC-69.01**: Genesis/world state derives a system profile and play mode.
- [ ] **AC-69.02**: Risky actions produce structured mechanics outcomes.
- [ ] **AC-69.03**: No-death preference prevents abrupt game-over failure.
- [ ] **AC-69.04**: Narrative-only mode remains low-crunch.
- [ ] **AC-69.05**: Milestones record progress without duplicates.
- [ ] **AC-69.06**: Mechanics stay separated from final prose generation.

## 8. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|---|---|---|
| S01 | Gameplay loop | Mechanics resolution runs inside turn processing only when action classification requires it. |
| S02 | Genesis | Genesis/world output supplies profile inference inputs and optional player preference. |
| S03/S08 | Narrative engine/pipeline | Resolver outputs structured context; narrative pipeline generates final text. |
| S05 | Choice/consequence | Failure consequences become typed consequences that can propagate. |
| S06 | Character system | Character traits/facts inform domains, but no full stat sheet is required in v2.1. |
| S39 | Universe composition | Universe/world traits bound what actions are plausible. |
| S68 | Client | Choice buttons can surface suggested mechanics-aware actions. |

## 9. Open Questions

1. Should v2.1 resolver be deterministic/rule-based only, or may it use an LLM classifier behind the rate-limit budget? — *Impact: high* — *Owner: implementation plan*
2. Should difficulty/death preference be configured during Genesis, in settings, or both? — *Impact: moderate* — *Owner: UX planning*

## 10. Out of Scope

- Full D&D 5e SRD, Fate, PbtA, OSR, or other OSS rules implementation — v3+ explicit ruleset specs.
- Combat initiative, equipment tables, spell lists, XP curves, or formal character sheets — later system plugin work.
- Adaptive difficulty inferred from play patterns — v5 directional only.
- Community achievements/badges — v4/v5 sharing/community layer.
- Therapeutic death/failure interpretation — Future Therapeutic Layer, not this mechanics spec.
