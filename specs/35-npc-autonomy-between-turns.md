# S35 — NPC Autonomy Between Turns

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 2 — Simulation
> **Dependencies**: S34 (Diegetic Time), S29 (Universe Identity)
> **Related**: v1 S06 (Character System), S36 (Consequence Propagation), S38 (NPC Memory)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

In v1, NPCs exist only when the player is present. There is no concept of an NPC
doing anything between player turns — the butcher does not close his shop at dusk,
the king does not fall ill while the player is away, the thief guild does not
reorganize after losing a conflict. Every encounter is freshly generated on demand.

This is a correct v1 simplification. It means the world only exists when the player
looks at it — a fundamentally flat simulation.

v2 changes this with **NPC Autonomy Between Turns**: NPCs with defined routines and
goals pursue them off-screen. A salience filter prevents this from becoming a
performance problem or a multi-agent orchestration system — not every NPC is modeled
every turn. The output of autonomy processing is a `WorldDelta`: a structured list of
NPC state changes that the narrative generation stage can incorporate into the story,
making the world feel genuinely alive.

**This spec explicitly rejects multi-agent orchestration.** The charter's §10 scope
fence ("no 10-agent decomposition") stands. There is no agent-router, no LangGraph,
no per-NPC LLM loop. Autonomy is rule-based by default; a single optional batched
LLM call per turn handles KEY-tier NPCs that have exceeded rule-based expressivity.

---

## 2. Design Philosophy

### 2.1 Principles

- **Salience filter, not full simulation**: Only NPCs that matter to the current player
  context are modeled. BACKGROUND-tier NPCs are never autonomously processed — they
  are regenerated on demand as in v1. SUPPORTING-tier NPCs are processed only when
  in recently-visited locations. KEY-tier NPCs are always processed.
- **Rule-based first, LLM optional**: The default autonomy mode is deterministic
  rule evaluation against `RoutineStep` schedules. An LLM-assisted mode is
  available for KEY-tier NPCs that need more than rules can express, but it is
  opt-in per NPC, not the default.
- **WorldDelta as the output contract**: The autonomy processor produces a `WorldDelta`
  — a list of atomic NPC state changes. Everything downstream (narrative generation,
  consequence propagation) consumes `WorldDelta`. The processor is not responsible
  for narrating the changes; only for computing them.
- **No orchestration primitives**: NPCs do not send messages to each other, hold
  conversations, or delegate tasks via a routing layer. Autonomy is a property of
  individual NPCs evaluated independently. Social effects (gossip, faction reactions)
  belong to S38 (NPC Memory) and S36 (Consequence Propagation).
- **Budget-bounded**: Processing has a configurable time budget per turn. NPCs that
  exceed the budget are deferred, with lower-priority NPCs deprioritized first.

### 2.2 What This Spec Is NOT

- This spec does NOT define multi-agent NPC conversations or coordination.
- This spec does NOT define how autonomy results are narrated (that is the generation
  stage's responsibility, via `WorldDelta` context injection).
- This spec does NOT define NPC memory of the player across sessions (see S38).
- This spec does NOT define consequence propagation to non-NPC world entities (see S36).

---

## 3. User Stories

> **US-35.1** — **As a** player, when I return to a location I visited yesterday
> (in-world), I find it different in believable ways — the market is closed, the
> guards have changed shift — without me having to trigger those changes explicitly.

> **US-35.2** — **As a** player, I can learn that significant off-screen events
> occurred while I was away (the duke was assassinated, the guild has new leadership),
> so the world feels like it exists and changes without me.

> **US-35.3** — **As a** player, NPCs behave consistently with the time of day:
> the tavern keeper is behind the bar at evening, asleep at midnight.

> **US-35.4** — **As a** developer, I can add a routine schedule to an NPC by
> storing `RoutineStep` records on the NPC's Neo4j node and trust the autonomy
> processor will execute them correctly given the current `WorldTime`.

> **US-35.5** — **As a** developer, the autonomy processor is a contained,
> injectable service — I can test it in isolation by providing a mock `WorldTime`
> and a list of NPCs.

> **US-35.6** — **As an** operator, I can observe the `WorldDelta` output for any
> processed turn in the observability layer (Langfuse, structlog) to audit what
> autonomous changes were applied.

---

## 4. Functional Requirements

### FR-35.01 — RoutineStep Type

A `RoutineStep` represents a single rule that an NPC follows when the world-time
matches a condition.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `trigger` | RoutineTrigger | Yes | The condition that activates this step. |
| `action` | AutonomyAction | Yes | The change to apply when the trigger fires. |
| `priority` | Integer [1, 10] | No (default: 5) | Higher values are processed first within a tick. |
| `repeating` | Boolean | No (default: true) | If true, fires every tick the trigger condition is met. If false, fires only once and becomes inactive. |
| `condition` | RoutineCondition or null | No | Optional guard expression. Step fires only if condition is satisfied. See FR-35.02. |

`RoutineStep` records are stored on the NPC's Neo4j node as a JSON array property
named `schedule`. An NPC with an empty or absent `schedule` array is treated as
having no autonomous behavior — it behaves as in v1.

### FR-35.02 — RoutineTrigger Types

A `RoutineTrigger` activates a `RoutineStep` when its condition is met. Supported
trigger types:

| Trigger Type | Fields | Description |
|---|---|---|
| `time_of_day` | `label: str` | Fires when `WorldTime.time_of_day_label` equals `label`. |
| `tick_elapsed` | `delta: int` | Fires when `total_ticks - last_fired_tick >= delta`. Tracks when the step last fired. |
| `world_event` | `event_type: str` | Fires when a `WorldEvent` of the given type has been recorded in the universe within the salience window. |
| `player_visited` | `location_id: str, within_ticks: int` | Fires if the player visited `location_id` within the last `within_ticks`. |

Only `time_of_day` and `tick_elapsed` are required for v2.0. `world_event` and
`player_visited` triggers are OPTIONAL for v2.0 implementations and MUST be
implemented in v2.1.

### FR-35.03 — AutonomyAction Types

An `AutonomyAction` specifies what changes when a `RoutineStep` fires. The union of
all actions produced in a tick forms the `WorldDelta` (FR-35.04).

| Action Type | Fields | Effect |
|---|---|---|
| `MoveAction` | `target_location_id: str` | Updates `NPC.location_id` to the target. The NPC is now in a different location. |
| `StateChangeAction` | `new_state: NPCState` | Updates `NPC.state` (see v1 `NPCState` literal: `idle`, `active`, `busy`, `sleeping`, `traveling`). |
| `DispositionShiftAction` | `npc_id: str, delta: int` | Adjusts the NPC's `disposition` score by `delta` (clamped to disposition range). |
| `NarrativeEventAction` | `description: str, severity: EventSeverity` | Records a `WorldEvent` with the given description and severity. Consumed by narrative generation and S36. |

All action types MUST be represented as discriminated union types. An `AutonomyAction`
is always exactly one action type.

### FR-35.04 — WorldDelta Type

`WorldDelta` is the output of a single autonomy processing run.

| Field | Type | Description |
|-------|------|-------------|
| `tick` | int | The `total_ticks` value at which this delta was computed. |
| `changes` | list[NPCStateChange] | Ordered list of applied NPC state changes. |
| `events` | list[WorldEvent] | `NarrativeEventAction` results that were promoted to `WorldEvent` records. |

`NPCStateChange` carries:
- `npc_id: str` — the affected NPC
- `action_type: str` — which action type was applied
- `before: dict` — the NPC state snapshot before the change
- `after: dict` — the NPC state snapshot after the change

`WorldDelta` for a skip-ahead of N ticks is the union of all per-tick `WorldDelta`
objects, in tick order.

### FR-35.05 — AutonomyProcessor Contract

The `AutonomyProcessor` is a service that computes `WorldDelta` given a session
context. Its interface MUST satisfy:

```
process(
    universe_id: str,
    world_time: WorldTime,
    npcs: list[NPC],
) -> WorldDelta
```

- **FR-35.05a**: The processor MUST be injectable (not a singleton). Tests MUST be
  able to provide a `MemoryAutonomyProcessor` with static NPC fixtures.
- **FR-35.05b**: The processor MUST apply the salience filter (FR-35.06) before
  processing any NPC. NPCs filtered out produce no `NPCStateChange` entries.
- **FR-35.05c**: The processor MUST apply `RoutineStep`s in descending priority
  order within a tick.
- **FR-35.05d**: If two `RoutineStep`s on the same NPC conflict in the same tick
  (e.g., both attempt a `StateChangeAction`), the higher-priority step wins. The
  lower-priority step is recorded as a `deferred_change` in the `WorldDelta` for
  observability.
- **FR-35.05e**: The processor MUST respect the `budget_ms` parameter (see
  FR-35.08). If the budget is exceeded, remaining unprocessed NPCs are recorded in
  `WorldDelta.deferred_npcs` with the reason `budget_exceeded`.
- **FR-35.05f**: The processor MUST be called BEFORE the narrative generation stage
  in the turn pipeline. Its `WorldDelta` output is injected into the generation
  context as `autonomous_changes`.

### FR-35.06 — Salience Filter

The salience filter determines which NPCs are eligible for autonomous processing in
a given tick. NPCs that do not pass the filter are skipped (no processing, no cost).

| NPC Tier | Processing Condition |
|----------|---------------------|
| `KEY` | Always processed if the NPC has a non-empty `schedule`. |
| `SUPPORTING` | Processed if the NPC's current `location_id` matches any location the player has visited within the last `salience_window_turns` turns (default: 5). |
| `BACKGROUND` | Never processed by the autonomy processor. Behavior regenerated on demand as in v1. |

The `salience_window_turns` is configurable via `universes.config["autonomy"]["salience_window_turns"]`
(default: 5, minimum: 1, maximum: 50).

### FR-35.07 — WorldEvent Records

A `NarrativeEventAction` result is promoted to a `WorldEvent` record stored in the
universe's event log (Neo4j). `WorldEvent` fields:

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | ULID | Unique identifier. |
| `universe_id` | ULID | Owning universe. |
| `event_type` | str | Classifies the event (e.g., `"npc_death"`, `"political_change"`, `"environmental"`). |
| `description` | str | Human-readable summary of what occurred. |
| `severity` | EventSeverity | `minor`, `notable`, `major`, `critical`. |
| `source_npc_id` | str or null | NPC that generated the event, if any. |
| `location_id` | str or null | Location where the event occurred, if applicable. |
| `triggered_at_tick` | int | The `total_ticks` at which the event occurred. |
| `created_at` | datetime | Wall-clock time of record creation. |

`WorldEvent` records are immutable once written. They serve as the historical record
of autonomous activity and are consumed by S36 (consequence propagation) and S37
(world memory).

### FR-35.08 — Processing Budget

The autonomy processor MUST accept a `budget_ms: int` parameter (default: 50).

- **FR-35.08a**: If the processor has consumed `budget_ms` milliseconds of CPU time
  and unprocessed NPCs remain, it MUST stop, record remaining NPCs in
  `WorldDelta.deferred_npcs`, and return the partial `WorldDelta`.
- **FR-35.08b**: Deferred NPCs are NOT retried in the same turn. They may be
  processed in the next turn if they remain salient.
- **FR-35.08c**: KEY-tier NPCs MUST always be processed within the budget window,
  regardless of ordering. If including all KEY-tier NPCs would alone exceed the
  budget, the budget is extended to accommodate them (KEY-tier NPCs are never
  deferred due to budget).
- **FR-35.08d**: Processing time is measured via `time.monotonic()` at processor
  entry and at each NPC processing boundary.

### FR-35.09 — LLM-Assisted Mode (Opt-In)

For KEY-tier NPCs that have complex autonomous behavior beyond what `RoutineStep`
rules can express, an **LLM-assisted mode** is available.

- **FR-35.09a**: LLM-assisted mode is activated by setting `npc.autonomy_mode =
  "llm_assisted"` on the NPC's Neo4j node. Default is `"rule_based"`.
- **FR-35.09b**: In LLM-assisted mode, the processor includes the NPC in a single
  **batched LLM call** per turn alongside all other `llm_assisted` KEY-tier NPCs.
  The prompt describes each NPC's current state, schedule, and the `WorldTime`, and
  asks for an `AutonomyAction` per NPC.
- **FR-35.09c**: The LLM response MUST be parsed into `AutonomyAction` instances.
  If parsing fails for an NPC, that NPC falls back to `rule_based` processing for
  the current tick. The failure is logged.
- **FR-35.09d**: The LLM call MUST be counted against the session's cost tracking
  (S07, S28) and MUST use the standard LiteLLM client.
- **FR-35.09e**: If the `llm_assisted` batch call fails entirely (network error,
  rate limit), all `llm_assisted` NPCs fall back to `rule_based` for the current
  tick. The fallback is logged as a warning.
- **FR-35.09f**: The number of `llm_assisted` KEY-tier NPCs per turn is capped at
  `universes.config["autonomy"]["max_llm_npcs_per_turn"]` (default: 5). NPCs
  exceeding this cap fall back to `rule_based` for that tick.

---

## 5. Non-Functional Requirements

### NFR-35.01 — Processing Latency
Rule-based autonomy processing for up to 20 KEY + SUPPORTING NPCs MUST complete in
under 50 ms (p95) on a standard API server. This budget is configurable via
`budget_ms`.

### NFR-35.02 — LLM Call Overhead
The optional LLM-assisted batch call MUST NOT block the turn response. It SHOULD be
structured so that if it exceeds `settings.turn_timeout_ms`, the call is abandoned
and results fall back to rule-based.

### NFR-35.03 — Observability
All `WorldDelta` outputs MUST be logged at `DEBUG` level via structlog, keyed by
`universe_id` and `total_ticks`. `NarrativeEventAction` promotions to `WorldEvent`
MUST be logged at `INFO` level with `event_type` and `severity`.

---

## 6. User Journeys

### Journey 1: Butcher Closes Shop at Dusk

**Setup**: The `Butcher` NPC has a `RoutineStep`:
- `trigger: time_of_day(label="dusk")`
- `action: StateChangeAction(new_state="busy")` (preparing to close)
- And: `action: MoveAction(target_location_id="butcher_back_room")`

**Turn processing**:
1. Player takes a turn. `WorldTime` advances to `dusk`.
2. Autonomy processor runs. Salience filter: Butcher is KEY-tier → always processed.
3. `time_of_day` trigger matches. Both actions fire in priority order.
4. `WorldDelta` includes: `{npc: Butcher, state: idle→busy}`,
   `{npc: Butcher, location: market→butcher_back_room}`.
5. Narrative generation receives `WorldDelta` context.
6. Narrator may note: "The butcher begins rolling down his shutters as the light fails."

### Journey 2: King Dies While Player Explores Ruins

**Setup**: The `King` NPC has a `RoutineStep`:
- `trigger: tick_elapsed(delta=20)` (after 20 in-world hours)
- `condition: NPC.state == "ill"` (only fires if the king is already ill)
- `action: NarrativeEventAction(description="The king has died of his illness.", severity="critical")`
- `repeating: false`

**Turn processing** (20 ticks after king became ill):
1. Player takes a turn in a distant dungeon.
2. Autonomy processor runs. King is KEY-tier → processed.
3. `tick_elapsed` trigger fires. Condition `state == "ill"` is true.
4. `NarrativeEventAction` fires → `WorldEvent` record written to universe event log.
5. `WorldDelta.events` contains the king's death event.
6. Narrative generation MAY or MAY NOT surface this to the player this turn,
   based on proximity and salience (S36 / generation stage decision).
7. On next visit to the capital, the consequence is inescapable.

### Journey 3: Skip-Ahead with NPC Autonomy

**Turn**: Player sleeps until dawn (15-tick skip).

1. `compute_world_time` calculates 15 ticks needed.
2. Autonomy processor called 15 times (or in a batched 15-tick run).
3. In ticks 3–10, a festival NPC routine fires: `StateChangeAction(active)`,
   `NarrativeEventAction("Festival preparations fill the square.", minor)`.
4. `WorldDelta` (aggregate of 15 ticks) delivered to narrative generation.
5. Player wakes up to: "The square outside is festooned with banners you didn't
   notice last night."

---

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | NPC has `schedule = []` (empty) | No autonomy processing; NPC treated as v1 on-demand |
| E2 | NPC tier is BACKGROUND with a non-empty `schedule` | Schedule is ignored; BACKGROUND tier is never processed autonomously |
| E3 | Two RoutineSteps conflict on the same NPC in the same tick | Higher-priority step wins; lower-priority recorded as `deferred_change` in WorldDelta |
| E4 | `MoveAction` targets a non-existent `location_id` | Action is rejected; NPC stays in current location; error logged; `deferred_change` recorded |
| E5 | LLM-assisted batch call times out | All `llm_assisted` NPCs fall back to `rule_based` for this tick; warning logged |
| E6 | LLM response has invalid JSON for one NPC | That NPC falls back to `rule_based`; other NPCs' LLM results are applied normally |
| E7 | Budget exceeded before all salient NPCs processed | Partial WorldDelta returned; unprocessed NPCs listed in `deferred_npcs` |
| E8 | `repeating: false` step fires during skip-ahead at tick 3 and again at tick 7 | Only fires once (at tick 3); `repeating: false` marks step inactive after first fire |
| E9 | `player_visited` trigger (v2.1) used in a v2.0 deployment | Trigger is treated as `not_matched` (never fires); logged as unsupported trigger type |
| E10 | Universe has no active sessions and a new one starts after 30 real days | `WorldTime` was last persisted at the end of the prior session; autonomy does NOT back-fill those 30 real days — only session turns advance time |

---

## 8. Acceptance Criteria (Gherkin)

```gherkin
Feature: NPC Autonomy Between Turns

  Background:
    Given a universe with a KEY-tier NPC named "Aldric the Butcher"
    And Aldric has a schedule with one RoutineStep:
      | trigger             | action                       |
      | time_of_day("dusk") | StateChangeAction(new_state="sleeping") |
    And an active game session with default time config

  Scenario: AC-35.01 — KEY-tier NPC routine fires at correct time
    Given the current world_time.time_of_day_label = "afternoon"
    When the turn pipeline advances world_time to "dusk"
    Then the autonomy processor fires Aldric's RoutineStep
    And WorldDelta contains an NPCStateChange for Aldric: state = "sleeping"

  Scenario: AC-35.02 — BACKGROUND-tier NPC with a schedule is not processed
    Given a BACKGROUND-tier NPC "Bob the Passerby" with a non-empty schedule
    When the autonomy processor runs
    Then Bob's schedule is not evaluated
    And WorldDelta contains no NPCStateChange for Bob

  Scenario: AC-35.03 — SUPPORTING-tier NPC outside salience window is not processed
    Given a SUPPORTING-tier NPC whose location was NOT visited in the last 5 turns
    When the autonomy processor runs
    Then the SUPPORTING NPC's schedule is not evaluated

  Scenario: AC-35.04 — SUPPORTING-tier NPC within salience window is processed
    Given a SUPPORTING-tier NPC whose location was visited 2 turns ago
    And the NPC has a matching RoutineStep
    When the autonomy processor runs
    Then the RoutineStep fires
    And WorldDelta contains an NPCStateChange for that NPC

  Scenario: AC-35.05 — WorldDelta is injected into narrative generation context
    Given the autonomy processor produced a non-empty WorldDelta
    When the narrative generation stage runs
    Then the generation prompt context includes "autonomous_changes" from the WorldDelta

  Scenario: AC-35.06 — non-repeating RoutineStep fires only once
    Given Aldric has a non-repeating RoutineStep with trigger time_of_day("dawn")
    When the player takes a turn that advances time to "dawn"
    Then the step fires once
    When the player takes a subsequent turn that passes through "dawn" again
    Then the step does not fire a second time

  Scenario: AC-35.07 — NarrativeEventAction promotes to WorldEvent record
    Given an NPC has a RoutineStep with a NarrativeEventAction
    When the RoutineStep fires
    Then a WorldEvent record is written to the universe's event log
    And the WorldEvent has the correct event_type, description, severity, and triggered_at_tick

  Scenario: AC-35.08 — Budget limit defers lower-priority NPCs
    Given 30 SUPPORTING-tier NPCs all within the salience window
    And the budget_ms is set very low (e.g., 1 ms) so only 5 fit
    When the autonomy processor runs
    Then at most 5 NPCs are processed within the budget
    And WorldDelta.deferred_npcs lists the remaining 25 NPCs with reason "budget_exceeded"

  Scenario: AC-35.09 — LLM-assisted NPC falls back to rule_based on parse failure
    Given a KEY-tier NPC with autonomy_mode = "llm_assisted"
    And the LLM response for that NPC cannot be parsed into an AutonomyAction
    When the autonomy processor runs
    Then the NPC's rule_based schedule is evaluated instead
    And a warning is logged with the parse failure details

  Scenario: AC-35.10 — AutonomyProcessor is injectable for testing
    Given a MemoryAutonomyProcessor with a static NPC fixture list
    When process() is called with a specific WorldTime
    Then the processor returns a deterministic WorldDelta matching the fixture expectations
    And no database or LLM calls are made
```

---

## 9. Out of Scope

- **Multi-agent NPC coordination**: NPCs do not communicate with each other via any
  routing layer. Social effects are S38's responsibility.
- **NPC memory of the player**: Cross-session NPC recollection is S38.
- **Consequence propagation to locations, factions, items**: That is S36.
- **Narrating autonomous changes**: The generation stage renders `WorldDelta`; this
  spec only produces it.
- **Player-facing autonomy controls**: Players cannot currently tune which NPCs are
  autonomous or turn off autonomy. Reserved for v3+.
- **Async/background processing**: Autonomy is always synchronous, in-turn. There is
  no background job that runs autonomy while the player is not playing.

---

## 10. Open Questions

| OQ | Question | Proposed Resolution |
|----|----------|---------------------|
| OQ-35.01 | NPC autonomy computation: batched LLM call with salience-filtered NPCs, or rule-based fallbacks? | **Resolved in this spec**: rule-based is primary (FR-35.02–FR-35.03); LLM-assisted is opt-in per NPC (FR-35.09). |
| OQ-35.02 | Should `WorldDelta` be persisted as part of the turn record, or only logged? | Proposed: log only (Langfuse + structlog); do NOT write to `universe_snapshots` — it's derivable. Final decision deferred to S37 (World Memory) author who needs the history. |
| OQ-35.03 | Should `deferred_npcs` be retried in the same pipeline pass (second sweep) or strictly next turn? | Proposed: strictly next turn. A second sweep risks budget overrun and complexity. |
| OQ-35.04 | How does S36 (Consequence Propagation) consume `WorldEvent` records produced by autonomy? | S36 is the normative spec for that contract. S35 only specifies that events are written to the universe event log. |

---

## Appendix A — Salience Filter Decision Table

| NPC Tier | Has Schedule? | Within Salience Window? | Autonomy_Mode | Processed? |
|----------|--------------|------------------------|---------------|-----------|
| KEY | Yes | n/a | rule_based | ✅ Yes |
| KEY | Yes | n/a | llm_assisted | ✅ Yes (in LLM batch) |
| KEY | No | n/a | any | ❌ No (no-op) |
| SUPPORTING | Yes | Yes | rule_based | ✅ Yes |
| SUPPORTING | Yes | No | rule_based | ❌ No (filtered) |
| BACKGROUND | Yes | n/a | any | ❌ No (tier excluded) |
| BACKGROUND | No | n/a | any | ❌ No (tier excluded) |

---

## Appendix B — AutonomyProcessor Data Flow

```
Turn pipeline (Enrich stage)
         │
         ▼
  AutonomyProcessor.process(universe_id, world_time, npcs)
         │
    Salience Filter
    (KEY always, SUPPORTING if visited, BACKGROUND never)
         │
    Rule Evaluation
    (RoutineStep trigger → AutonomyAction)
         │
    Optional LLM batch
    (llm_assisted KEY-tier only, single call, opt-in)
         │
         ▼
       WorldDelta
    {changes, events, deferred_npcs}
         │
         ├──► Neo4j write: NPC state updates + WorldEvent records
         │
         └──► Narrative Generation stage context: "autonomous_changes"
```
