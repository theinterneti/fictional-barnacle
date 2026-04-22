# S36 — Consequence Propagation

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 2 — Simulation
> **Dependencies**: S34 (Diegetic Time), S35 (NPC Autonomy), v1 S04 (World Simulation)
> **Related**: S37 (World Memory), S38 (NPC Memory), v1 `WorldChange`, `WorldChangeType`
> **Last Updated**: 2026-04-21

---

## 1. Purpose

In v1, world changes are atomic and local. When the player does something, only the
directly targeted entities change. The guard who dies in the market square stays dead,
but the barkeep in the adjacent tavern has no idea anything happened. The faction the
dead guard belonged to is unaffected until the player walks into their territory.

This is the "world only exists when the player looks at it" limitation.

v2 changes this with **Consequence Propagation**: when a significant event occurs —
player action, NPC autonomous action (S35), or world event — its effects ripple
outward through the location graph and social graph at bounded depth. Nearby entities
react immediately; distant entities hear distorted rumors.

This spec defines:
- The `ConsequencePropagator` service contract
- How effects are calculated at each graph hop
- The distortion model (severity and description degradation)
- Faction-aware propagation shortcuts through the social graph
- The `ConsequenceRecord` output type consumed by narrative generation and S37

---

## 2. Design Philosophy

### 2.1 Principles

- **Bounded depth, not unlimited simulation**: Propagation MUST stop at a configured
  maximum hop depth. Default max depth is 3 hops; configurable per universe.
- **Distortion increases with distance**: At hop 2, the barkeep "heard there was a
  fight." At hop 3, a distant village "got word of some trouble in the city."
- **Graph-walk, not full re-simulation**: Propagation walks the existing Neo4j
  `CONNECTS_TO` graph. It is an additive annotation process.
- **Federation with S35**: NPC autonomous actions (`WorldDelta` from S35) are valid
  propagation sources — not just player actions.
- **Rule-based severity model**: The consequence severity calculation at each hop is
  deterministic. LLM involvement is limited to optional hop-2 paraphrasing only.

### 2.2 What This Spec Is NOT

- S36 does not define how consequences are *rendered* in prose — see narrative generation.
- S36 does not define NPC memory of the player across sessions — see S38.
- S36 does not define the full world memory model — see S37.
- S36 does not define faction mechanics beyond propagation social shortcuts.

---

## 3. User Stories

> **US-36.1** — **As a** player, after I do something significant, I encounter
> acknowledgment of that action from NPCs in nearby locations even if I haven't visited
> them since, so the world feels causally connected.

> **US-36.2** — **As a** player, NPCs closer to where I acted have more accurate
> knowledge; those farther away have vaguer, possibly distorted information.

> **US-36.3** — **As a** player, when I provoke a faction, other members of that
> faction in different locations react even if they weren't witnesses.

> **US-36.4** — **As a** developer, I can trace every `ConsequenceRecord` back to its
> source event for auditing and debugging.

> **US-36.5** — **As a** universe author, I can configure the maximum propagation depth
> and severity threshold per universe.

---

## 4. Functional Requirements

### FR-36.01 — Propagation Source Events

A **propagation source** is any of the following:

| Source Type | Origin | `source_type` value |
|---|---|---|
| Player action | v1 `WorldChange` list from `apply_world_changes` | `"player_action"` |
| NPC autonomous action | S35 `WorldDelta.changes` | `"npc_autonomy"` |
| World event promotion | S35 `WorldDelta.events` (`NarrativeEventAction`) | `"world_event"` |

Only events with `EventSeverity` of `"notable"`, `"major"`, or `"critical"` are
eligible as propagation sources. `"minor"` events do NOT propagate. This threshold
is configurable via `universes.config["propagation"]["min_propagation_severity"]`
(default: `"notable"`).

### FR-36.02 — Propagation Graph Walk

The propagator walks the Neo4j world graph outward from the **source location**.

- **FR-36.02a**: Starting from `source_location_id`, the propagator queries all
  locations reachable via `CONNECTS_TO` edges within `max_propagation_depth` hops.
  (Default: 3; configurable via `universes.config["propagation"]["max_depth"]`.)
- **FR-36.02b**: Queries MUST use the parameterized graph depth pattern already
  established in v1 `_location_context_query`. No new Neo4j driver connection is
  opened; the existing session is reused.
- **FR-36.02c**: Only alive NPCs (`npc.alive = true`) at each reached location are
  included (via `IS_AT` relationship).
- **FR-36.02d**: For each NPC or location reached, the propagator computes a
  `ConsequenceRecord` (FR-36.04) using the distortion model (FR-36.03).

### FR-36.03 — Distortion Model

Consequence severity and description degrade with hop distance.

| Hop Distance | Severity Adjustment | Description Fidelity |
|---|---|---|
| 0 (source) | No change | Exact description |
| 1 | Decrement 1 step | Full detail |
| 2 | Decrement 2 steps | Partial detail, vague |
| 3 | Decrement 3 steps | Rumor only |
| > 3 | Not propagated | n/a |

**Severity decrement table** (one step per hop):

| Original | −1 (hop 1) | −2 (hop 2) | −3 (hop 3) |
|---|---|---|---|
| `critical` | `major` | `notable` | `minor` |
| `major` | `notable` | `minor` | (filtered out) |
| `notable` | `minor` | (filtered out) | (filtered out) |
| `minor` | (filtered out) | n/a | n/a |

Events decremented below `"minor"` are NOT propagated at that hop distance.

**Description fidelity**:

- Hop 1 (`full`): Description is passed through unchanged.
- Hop 2 (`partial`): If LLM available, single batched paraphrase call. Otherwise,
  template: `"Word has reached here that {original_description_summary}."`
  (first 80 chars of original description).
- Hop 3 (`rumor`): Template only: `"There are vague rumors of {event_type} near
  {source_location_name}."` No LLM at hop 3 (cost control).

### FR-36.04 — ConsequenceRecord Type

| Field | Type | Description |
|-------|------|-------------|
| `consequence_id` | ULID | Unique identifier. |
| `universe_id` | ULID | Owning universe. |
| `source_event_id` | str | ID of the originating `WorldEvent` or `WorldChange`. |
| `source_type` | str | `"player_action"`, `"npc_autonomy"`, `"world_event"`. |
| `source_location_id` | str | Location where the source event occurred. |
| `affected_entity_id` | str | The NPC or location that received the consequence. |
| `affected_entity_type` | str | `"npc"` or `"location"`. |
| `hop_distance` | int [0–3] | Graph hops from source location. |
| `original_severity` | str | Severity at source. |
| `propagated_severity` | str | Severity at this hop after distortion. |
| `description` | str | Consequence description at this fidelity level. |
| `faction_id` | str or null | Faction ID if propagated via faction graph (FR-36.05). |
| `triggered_at_tick` | int | `WorldTime.total_ticks` at propagation time. |
| `created_at` | datetime | Wall-clock creation time. |

`ConsequenceRecord` objects are persisted as Neo4j nodes with `universe_id` for
cross-session querying. They are NOT stored in Postgres `world_events`.

### FR-36.05 — Faction-Aware Propagation

NPCs that share a `faction_id` with the directly affected NPC receive the consequence
at hop-1 distortion level, regardless of their physical graph distance from the source.

- **FR-36.05a**: Faction propagation applies only to NPC-targeted consequences
  (`affected_entity_type = "npc"`).
- **FR-36.05b**: Faction graph query:

  ```cypher
  MATCH (npc:NPC {faction_id: $faction_id, universe_id: $universe_id})
  WHERE npc.id <> $source_npc_id AND npc.alive = true
  ```

- **FR-36.05c**: Faction records carry `hop_distance = 1` and `faction_id` set.
- **FR-36.05d**: An NPC that is both within physical depth AND in the same faction
  receives only ONE record. Physical record takes precedence if `hop_distance < 1`;
  otherwise the faction record is used.
- **FR-36.05e**: If `faction_id` is null on the affected NPC, no faction propagation.

### FR-36.06 — PropagationResult Type

| Field | Type | Description |
|-------|------|-------------|
| `source_event_id` | str | The event that triggered propagation. |
| `records` | list[ConsequenceRecord] | Records from graph-walk propagation. |
| `faction_records` | list[ConsequenceRecord] | Records from faction-graph propagation. |
| `total_records` | int | `len(records) + len(faction_records)`. |
| `propagation_depth_reached` | int | Actual maximum hop depth reached this run. |
| `skipped_minor` | int | Events filtered by `min_propagation_severity`. |
| `budget_exceeded` | bool | True if `budget_ms` was reached before walk completed. |

### FR-36.07 — ConsequencePropagator Contract

```python
async def propagate(
    source_events: list[PropagationSource],
    universe_id: str,
    world_time: WorldTime,
) -> PropagationResult: ...
```

- **FR-36.07a**: Injectable. A `MemoryConsequencePropagator` with static graph
  fixtures MUST exist for unit testing without a live Neo4j instance.
- **FR-36.07b**: At most ONE LLM call per `propagate()` invocation, batching all
  hop-2 descriptions. Excess falls back to template.
- **FR-36.07c**: Runs AFTER `AutonomyProcessor.process()` and BEFORE narrative
  generation (Enrich stage).
- **FR-36.07d**: `PropagationResult` is injected into the generation context as
  `"propagated_consequences"`.
- **FR-36.07e**: Must complete within `budget_ms` (default: 100 ms). On budget
  exceeded, returns partial result with `budget_exceeded = True`.

### FR-36.08 — Persistence

- `ConsequenceRecord` nodes are written to Neo4j within the same transaction as the
  triggering `WorldEvent`.
- Records older than `universes.config["propagation"]["record_retention_ticks"]`
  (default: 500 ticks) MAY be pruned by a background maintenance job.
- S37 (World Memory) consumes `ConsequenceRecord` nodes as input to importance
  scoring at memory write time.

---

## 5. Non-Functional Requirements

### NFR-36.01 — Propagation Latency
Graph-walk and `ConsequenceRecord` computation (rule-based) MUST complete in under
100 ms (p95) for a universe with up to 100 locations and 200 NPCs at max depth 3.

### NFR-36.02 — LLM Paraphrasing Budget
Hop-2 paraphrasing MUST NOT issue more than 1 LLM call per `propagate()` run.

### NFR-36.03 — Observability
All `PropagationResult` objects MUST be logged at `DEBUG` level with structlog.
Any `budget_exceeded = True` result MUST be logged at `WARNING` level.

### NFR-36.04 — Test Coverage
Unit tests MUST cover: severity decay, faction-override deduplication,
budget-exceeded short-circuit, minor-event filter, empty graph.

---

## 6. User Journeys

### Journey 1: Player Kills a Guard (Critical Event)

**Setup**: Player at `market_square`. Guard belongs to `city_watch` faction.
Adjacent: `tavern` (hop 1), `guild_hall` (hop 2), `city_gate` (hop 3).
Other `city_watch` NPCs: `gate_captain` at `city_gate` (3 hops away).

1. Source: `player_action`, severity `critical`, location `market_square`.
2. Hop 1 (`tavern`): `barkeep`. Record: severity `major`, full description.
3. Hop 2 (`guild_hall`): `guild_master`. Record: severity `notable`, partial
   — "Word has reached here that a guard was killed in the market."
4. Hop 3 (`city_gate`): `gate_guard`. Record: severity `minor`, rumor
   — "There are vague rumors of player_action near market_square."
5. Faction (`city_watch`): `gate_captain` gets a hop-1 faction record (severity
   `major`, full description). Physical hop-3 record for gate_captain NOT created.
6. `PropagationResult.total_records = 4`.

### Journey 2: NPC Autonomous Event (King Dies)

**Source**: S35 `NarrativeEventAction` produced `WorldEvent: "king_death"`,
severity `critical`, location `throne_room`.

1. `ConsequencePropagator.propagate()` receives `source_type: "world_event"`.
2. Graph walk from `throne_room` proceeds identically to a player action.
3. All `royal_guard` faction NPCs receive hop-1 faction records.
4. Player in a distant dungeon (within graph depth 3) gets a hop-3 rumor record.

---

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | Source event has severity `"minor"` | No records; `skipped_minor += 1` |
| E2 | Source location has no connected locations | `records = []`; no error |
| E3 | NPC is both physical hop-2 and same faction | Faction record (hop-1) wins; one record |
| E4 | LLM paraphrasing call fails | Fall back to template; log warning; continues |
| E5 | `max_depth = 0` configured | Treated as 1; hop-0 source record still created |
| E6 | NPC dies between graph query and record write | Record written with state at query time; best-effort |
| E7 | Budget exceeded mid-walk | `budget_exceeded = True`; partial result; WARNING logged |
| E8 | Faction has 0 other alive members | No faction records; no error |

---

## 8. Acceptance Criteria (Gherkin)

```gherkin
Feature: Consequence Propagation

  Background:
    Given a universe with max propagation depth = 3
    And a world graph: market_square → tavern (hop 1) → guild_hall (hop 2) → city_gate (hop 3)
    And NPCs: barkeep at tavern, guild_master at guild_hall, gate_guard at city_gate
    And a guard NPC at market_square belonging to faction "city_watch"
    And a gate_captain NPC at city_gate belonging to faction "city_watch"

  Scenario: AC-36.01 — Minor events do not propagate
    Given a source event with severity "minor"
    When propagate() is called
    Then PropagationResult.total_records = 0
    And PropagationResult.skipped_minor = 1

  Scenario: AC-36.02 — Notable event propagates to correct depths only
    Given a source event with severity "notable" at market_square
    When propagate() is called
    Then a ConsequenceRecord exists for barkeep with propagated_severity = "minor"
    And no ConsequenceRecord exists for guild_master or gate_guard

  Scenario: AC-36.03 — Critical event propagates with correct severity decay
    Given a source event with severity "critical" at market_square
    When propagate() is called
    Then barkeep record has propagated_severity = "major"
    And guild_master record has propagated_severity = "notable"
    And gate_guard record has propagated_severity = "minor"

  Scenario: AC-36.04 — Faction members receive hop-1 record regardless of distance
    Given a critical source event targeting the guard at market_square
    When propagate() is called
    Then gate_captain has a ConsequenceRecord with hop_distance = 1 and faction_id = "city_watch"
    And gate_captain does NOT also have a hop-3 ConsequenceRecord

  Scenario: AC-36.05 — Hop-2 description falls back to template on LLM failure
    Given the LLM paraphrasing service is unavailable
    And a critical source event at market_square
    When propagate() is called
    Then guild_master ConsequenceRecord.description starts with "Word has reached here that"

  Scenario: AC-36.06 — PropagationResult is injected into generation context
    Given propagate() returns a non-empty PropagationResult
    When the narrative generation stage runs
    Then the generation context includes "propagated_consequences"

  Scenario: AC-36.07 — Budget exceeded returns partial result without error
    Given propagation budget_ms is set to 0 (forced timeout)
    And a critical source event at market_square
    When propagate() is called
    Then PropagationResult.budget_exceeded = True
    And no exception is raised

  Scenario: AC-36.08 — ConsequenceRecords are persisted to Neo4j
    Given a critical source event at market_square
    When propagate() completes with a non-empty result
    Then ConsequenceRecord nodes exist in Neo4j with the correct universe_id
```

---

## 9. Out of Scope

- Faction relationship mechanics (alliances, rivalries, reputation scores).
- Cross-universe propagation — consequences do not cross universe boundaries.
- Item propagation — stolen items noticed by distant owners.
- Consequence record background pruning scheduling.
- **Adaptive propagation depth** — depth is fixed per universe. Deferred to v3+.
- Player-visible rumor mechanics — what the player *hears* from NPCs is a narrative
  generation concern.

---

## 10. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-36.01 | Propagation graph depth limit — fixed or adaptive? | ✅ Resolved | **Fixed** (default 3, configurable per universe). Adaptive depth deferred to v3+. |
| OQ-36.02 | Should `ConsequenceRecord` be exposed to players via a "heard rumors" API? | ⏳ Open | Proposed: no direct API; records influence generation context only. Future spec to decide. |
| OQ-36.03 | How does propagation interact with secret passages NPCs don't know about? | ⏳ Open | Proposed: `CONNECTS_TO` edges carry `traversable_by_npcs: bool`. S40 author to decide. |

---

## Appendix A — PropagationSource Type

```python
from dataclasses import dataclass
from tta.world.time import WorldTime   # S34

@dataclass(frozen=True)
class PropagationSource:
    source_event_id: str
    source_type: str  # "player_action" | "npc_autonomy" | "world_event"
    source_location_id: str
    original_severity: str   # EventSeverity
    description: str
    faction_id: str | None = None
    affected_entity_id: str | None = None
    affected_entity_type: str | None = None  # "npc" | "location"
```

## Appendix B — Distortion Fidelity Decision Table

| Hop | Fidelity Level | LLM Used? | Template Used? | Severity Filter |
|-----|----------------|-----------|----------------|-----------------|
| 0 | exact | No | No | Original severity |
| 1 | full | No | No | −1 step |
| 2 | partial | Yes (batched, optional) | Yes (fallback) | −2 steps |
| 3 | rumor | No | Always | −3 steps |
| >3 | (not propagated) | — | — | Filtered |

## Appendix C — Pipeline Position

```
Turn Pipeline (v2 Enrich stage):
  1. Understand stage (parse intent)
  2. AutonomyProcessor.process()       →  WorldDelta              [S35]
  3. ConsequencePropagator.propagate() →  PropagationResult       [S36] ← THIS SPEC
  4. MemoryWriter.record()             →  MemoryRecord[]          [S37]
  5. Context assembly                  →  generation context dict
  6. Generate stage
  7. Stream stage
```
