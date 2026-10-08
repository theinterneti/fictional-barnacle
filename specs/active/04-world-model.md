# S04 — World Model

> **Status**: ✅ Approved
> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ⚠️ Partial
> **Level**: 1 — Core Game Experience
> **Dependencies**: S00
> **Last Updated**: 2025-07-24

---

## Purpose

The world model is the simulation layer of TTA. It is the answer to the question:
"What exists, where is it, and what's happening there right now?" If the narrative
engine (S03) is the voice, the world model is the memory. It tracks every location,
NPC, item, and environmental condition. It evolves over time. It is the single source
of truth that makes the narrative engine's prose *accurate*.

A great narrative engine telling stories about a shallow world produces impressive-
sounding nonsense. A rich world model with a mediocre engine produces boring accuracy.
TTA needs both. This spec defines the world.

**Co-design note**: This spec defines the **domain model** — what the world IS and
how it behaves. S13 (Storage Schema) defines HOW it's stored (Neo4j graph schema,
SQL tables, etc.). They must align, but this spec does not prescribe storage
technology.

---

## User Stories

### World Richness

- **US-4.1**: As a player, I want the world to feel like it exists beyond what I can
  see — NPCs have lives when I'm not watching, weather changes, time passes — so
  that it feels real, not staged.

- **US-4.2**: As a player, I want to revisit a location and find it changed — a
  market that was bustling is now closed for the night, a building that was intact
  is now damaged — so that time feels real.

- **US-4.3**: As a player, I want to discover new areas that feel like they were
  always there, not generated on the spot, so that exploration is rewarding.

### World Consistency

- **US-4.4**: As a player, I want the geography to be consistent — if I walked north
  to reach the mountain, walking south should take me back — so that I can build
  a mental map.

- **US-4.5**: As a player, I want NPCs to be where they're supposed to be — the
  blacksmith in the forge during the day, the tavern keeper behind the bar — not
  teleporting randomly.

- **US-4.6**: As a player, I want the world's rules to be consistent — if magic is
  rare, I shouldn't stumble over enchanted items every turn.

### World Reactivity

- **US-4.7**: As a player, I want my actions to change the world visibly — if I burn
  down a building, it stays burned — so that I feel consequential.

- **US-4.8**: As a player, I want the world to react to big events — if I defeat a
  tyrant, the political landscape should shift — not just locally, but regionally.

---

## Functional Requirements

### FR-1: World Structure

**FR-1.1** — The world is composed of **entities** organized in a graph structure.
The primary entity types are:

| Entity Type | Description | Examples |
|-------------|-------------|---------|
| **Location** | A place the player can be | room, street, forest clearing, ship deck |
| **Region** | A collection of connected locations | a town, a district, a wilderness area |
| **NPC** | A non-player character | merchant, guard, companion, antagonist |
| **Item** | An object in the world | sword, letter, key, potion |
| **Event** | Something that has happened or is happening | a fire, a festival, a war |
| **Faction** | An organized group | a guild, an army, a family |
| **Condition** | An environmental state | weather, time of day, magical effect |

**FR-1.2** — Entities are connected by **relationships**:

| Relationship | Between | Example |
|-------------|---------|---------|
| `CONTAINS` | Location → Item, NPC | "The tavern contains the barkeep" |
| `CONNECTS_TO` | Location → Location | "The alley connects to the market square" |
| `BELONGS_TO` | Location → Region | "The tavern belongs to the Harbor District" |
| `OWNS` | NPC → Item | "The merchant owns the map" |
| `MEMBER_OF` | NPC → Faction | "The guard is a member of the City Watch" |
| `KNOWS` | NPC → NPC | "The barkeep knows the smuggler" |
| `AFFECTED_BY` | Location/NPC → Event | "The warehouse is affected by the fire" |
| `LOCATED_IN` | NPC/Item → Location | "The key is located in the chest" |

**FR-1.3** — Every entity has:
- A unique identifier
- A display name
- A description template (narration-ready text)
- A set of mutable properties (state that changes over time)
- A creation timestamp and last-modified timestamp

**FR-1.4** — The world graph is **layered**:

| Layer | What It Tracks | Example |
|-------|---------------|---------|
| **Geography** | Physical space, terrain, connections | Mountains, rivers, roads |
| **Political** | Factions, territories, power dynamics | Who controls what |
| **Social** | NPC relationships, reputation, gossip | Who knows whom, who trusts whom |
| **Ecological** | Resources, weather, natural cycles | Seasons, wildlife, harvests |
| **Narrative** | Story threads, active plots, secrets | What's happening in the story |

### FR-2: World State

**FR-2.1** — Every entity has mutable state properties. Example for a Location:

```
Location: "The Red Lantern Tavern"
  state:
    condition: "open"          # open, closed, damaged, destroyed
    crowd_level: "busy"        # empty, quiet, moderate, busy, packed
    time_visited: 3            # how many times the player has been here
    last_visited: "turn_47"    # when the player was last here
    known_to_player: true      # has the player discovered this location?
    mood: "tense"              # current atmospheric mood
    active_events: ["brawl"]   # events currently happening here
```

**FR-2.2** — World state changes are triggered by:
- **Player actions**: Direct consequences of what the player does (see S05).
- **Time progression**: Passive changes as time passes (see FR-3).
- **NPC actions**: NPCs acting autonomously (see FR-3, S06).
- **Event cascades**: Consequences of earlier events propagating (see S05).
- **Environmental rules**: Weather, day/night, seasonal changes.

**FR-2.3** — State changes MUST be atomic and consistent. If a player action changes
three entities (e.g., moving an item from one location to another), all three changes
succeed or all fail. No partial state updates.

**FR-2.4** — State changes MUST be logged. Every mutation records: what changed, what
caused the change, the previous value, and the new value. This log supports
consequence tracking (S05) and debugging.

### FR-3: Simulation Rules

**FR-3.1** — The world simulates at a **lightweight** level. TTA is not Dwarf
Fortress. Simulation exists to create the *feeling* of a living world, not to
model physics or economics in detail.

**FR-3.2** — **Time progression**: The world has a clock. Time advances with each
player turn. The rate is flexible:
- Normal turn: minutes to an hour pass (depending on action type)
- Travel: hours pass (proportional to distance)
- Rest/sleep: hours pass (a full night)
- Narrative time skip: the system may advance time between chapters

**FR-3.3** — **Day/night cycle**: The world tracks time of day. This affects:
- NPC availability (shops close, guards change shifts)
- Location descriptions (a market looks different at midnight)
- Random encounters (different dangers at night)
- Player visibility and options

**FR-3.4** — **Weather**: The world has weather, influenced by the WorldSeed and
advancing over time. Weather affects:
- Location descriptions (rain, fog, heat)
- Travel difficulty
- NPC behavior (people seek shelter in storms)
- Mood and atmosphere

**FR-3.5** — **NPC schedules**: NPCs have daily routines (simplified). A merchant
is at their shop during business hours and at home at night. A guard patrols
designated routes. This creates a sense of a world with patterns.

**FR-3.6** — **Off-screen events**: Between player turns, things happen in the
world that the player doesn't see. A rival faction makes a move. An NPC travels
somewhere. Weather shifts. These are resolved during the world-state update
phase of each turn.

**FR-3.7** — Simulation detail scales with **proximity to the player**:
- **Adjacent locations**: Fully simulated (NPC positions, events, conditions)
- **Same region**: Partially simulated (major events, faction movements)
- **Distant regions**: Abstract simulation (broad trends, no detail)
- **Unvisited areas**: Potential only — details generated when the player
  approaches (lazy generation)

**FR-3.8** — Simulation MUST NOT produce state changes that contradict player
experience. If the player just saw an NPC in the tavern, the NPC doesn't
teleport to another town in the next turn's off-screen update.

### FR-4: World Generation

**FR-4.1** — Initial world generation occurs during Genesis (S02). The WorldSeed
produces:
- The player's starting location (fully detailed)
- The starting region (locations sketched, connections defined, some detail)
- Adjacent regions (names and themes only — generated lazily)
- Key NPCs (those who appear during Genesis, fully detailed)
- Initial world conditions (time, weather, political situation)

**FR-4.2** — World generation is **lazy**. Areas are generated in detail only when
the player approaches or when narrative requires it. This allows theoretically
unbounded worlds without upfront computation.

**FR-4.3** — Lazy generation MUST be **deterministic relative to the WorldSeed**. If
two players with the same WorldSeed (hypothetically) walked to the same ungenerated
area, the results should be structurally similar (not identical — there's randomness
— but consistent with the world's rules).

**FR-4.4** — Generated areas MUST be consistent with:
- WorldSeed parameters (tech level, magic presence, tone)
- Adjacent area characteristics (a desert doesn't border a tundra without
  justification)
- World-level rules (if magic is rare, a new area doesn't have wizards everywhere)

**FR-4.5** — The system MUST generate enough world during Genesis that the player
never encounters obvious lazy-generation seams in their first 10 turns.

### FR-5: World Boundaries

**FR-5.1** — A world has a **conceptual size** set by the WorldSeed `world_scale`:

| Scale | Approximate Size | Region Count |
|-------|-----------------|--------------|
| Intimate | One town/building | 1-3 regions |
| Regional | A province or county | 3-8 regions |
| Continental | A large landmass | 8-20 regions |
| Cosmic | Multiple realms/planets | 15-30+ regions |

**FR-5.2** — World boundaries are **soft, not hard**. The player cannot walk to the
"edge of the map" and hit an invisible wall. Instead:
- At world boundaries, the narrative discourages further travel naturally
  ("The road fades into trackless wilderness. Something tells you your story
  lies behind you, not ahead.")
- If the player persists, the boundary expands — a new region is generated.
  But the narrative gently steers back.

**FR-5.3** — World size does NOT mean world *density*. An intimate world (one town)
has depth — many interiors, many NPCs, layered secrets. A cosmic world has breadth
— many locations, but each with less detail.

**FR-5.4** — The system MUST track which regions the player has visited and ensure
that new regions don't feel copy-pasted. Each region has a distinct identity.

### FR-6: Persistence

**FR-6.1** — The following world state MUST survive across sessions:
- All location states (conditions, events, modifications)
- All NPC states (positions, dispositions, inventory, conversation history)
- All item states (positions, conditions, ownership)
- Time of day and weather
- Active events and their progress
- World graph structure (connections, containment)
- Faction states (territory, relationships, power)

**FR-6.2** — The system MUST support **incremental persistence**. After each turn,
only *changed* state is written. A full world snapshot is written at chapter
boundaries and on explicit save.

**FR-6.3** — The system MUST support **world state rollback** for error recovery.
If a state update corrupts the world, the system can revert to the last known-good
snapshot.

**FR-6.4** — Abandoned game state (player hasn't played in 90+ days) MAY be
archived to cold storage but MUST be restorable.

### FR-7: World Queries

**FR-7.1** — The system MUST support efficient queries against the world graph. Core
query patterns:

| Query | Purpose | Example |
|-------|---------|---------|
| **Nearby** | What's near the player? | Locations, NPCs, items within 1-2 hops |
| **Path** | How to get from A to B? | Shortest path between locations |
| **History** | What happened here? | Events at a location, sorted by time |
| **State** | What's the current state of X? | NPC disposition, location condition |
| **Search** | Find entity by property | "Which NPC has the key?" |
| **Diff** | What changed since turn N? | State changes since last visit |
| **Region** | What's in this region? | All locations, NPCs, items in a region |

**FR-7.2** — The "Nearby" query is the most critical — it assembles the local context
for every narrative generation call. It MUST complete within 200ms.

**FR-7.3** — The "Diff" query supports the narrative engine's "what changed" feature.
When a player revisits a location, the engine can describe what's different.

**FR-7.4** — All queries return structured data, not prose. The narrative engine (S03)
transforms query results into narrative.

---

## Non-Functional Requirements

- **NFR-4.1** — "Nearby" query MUST complete within 200ms (p95).
- **NFR-4.2** — World state update (after a turn) MUST complete within 500ms.
- **NFR-4.3** — Lazy world generation MUST complete within 3 seconds (generating a
  new region on the fly).
- **NFR-4.4** — The world graph MUST support at least 10,000 entities per world
  without query degradation.
- **NFR-4.5** — World state persistence (incremental) MUST complete within 1 second.
- **NFR-4.6** — World state snapshot (full) MUST complete within 5 seconds.
- **NFR-4.7** — The system MUST support 100 concurrent worlds (one per active player).

---

## User Journeys

### Journey 1: Exploring a Living Town

1. Player is in the marketplace at midday. NPCs are shopping, a bard is playing,
   stalls are open.
2. Player explores for 10 turns, visiting the blacksmith, the temple, the docks.
3. Time passes — it's now evening. The marketplace is quieter. Some stalls are
   closing. The bard has moved to the tavern. Street lamps are being lit.
4. Player goes to the tavern — it's busier than before, because NPCs who were
   in the market have come here. The bard is playing a different song.
5. The world feels alive because NPCs moved, lighting changed, and the atmosphere
   shifted — all driven by the simulation layer.

### Journey 2: Consequences Reshaping Geography

1. Turn 15: Player sets fire to a warehouse (a choice with consequences — see S05).
2. Turn 16: The warehouse is "burning." NPCs nearby are panicking.
3. Turn 20: The warehouse is "destroyed." The surrounding area is "damaged."
4. Turn 40: The player returns. Where the warehouse stood, there's rubble. A
   makeshift market has sprung up in the cleared space. New NPCs are there.
5. The world model tracked: fire → damage → destruction → regeneration. The
   narrative engine described each stage.

### Journey 3: Lazy Generation at the Frontier

1. Player decides to leave the starting region and head west.
2. The western region exists as a stub: "The Ashvale — a volcanic lowland with
   sulfurous hot springs and a mining culture."
3. As the player approaches, the system generates: 4 locations (a mine entrance,
   a hot spring settlement, a trade road, a collapsed bridge), 3 NPCs (a mine
   foreman, a healer, a traveling merchant), and initial conditions.
4. The player arrives and the area feels fully realized. No seams. No loading.
5. Behind the scenes, generation took 2.5 seconds during the "travel" turns.

### Journey 4: Querying What Changed

1. Player visits the temple in turn 10. It's serene, well-maintained, a priest
   named Brother Aldric tends the altar.
2. Player leaves and does other things for 30 turns.
3. Player returns to the temple. The world model's "Diff" query returns:
   - Brother Aldric is no longer here (he left on a pilgrimage — off-screen event).
   - A new acolyte is tending the altar (generated to replace Aldric).
   - A crack has appeared in the altar stone (seeded by an earthquake event from
     turn 25).
4. The narrative engine describes all three changes naturally: *"The temple is
   quieter than you remember. Brother Aldric's absence is felt in the dust
   gathering on the altar — and in the nervous energy of the young acolyte who's
   taken his place. She looks up as you enter. 'Did you feel the tremor last week?
   The altar stone cracked. Some say it's a sign.'"*

---

## Edge Cases

- **EC-4.1**: Player tries to go somewhere that doesn't exist ("I go to the moon").
  System responds in-world: *"You look up at the sky. The moon hangs there, distant
  and unreachable. Your feet stay on the ground."* No world generation triggered.

- **EC-4.2**: Player destroys a key location (the only bridge, the main quest NPC's
  home). The world adapts — alternative paths are generated, NPCs relocate, the
  story pivots. The world is not breakable.

- **EC-4.3**: Time progression creates a paradox (NPC should be in two places). The
  simulation resolves in favor of the location the player would most likely encounter.
  The NPC is where it makes the best story.

- **EC-4.4**: Lazy generation would create a location that conflicts with established
  world state (e.g., a peaceful meadow next to an active battlefield). The system
  checks adjacency constraints and regenerates if needed.

- **EC-4.5**: Player asks about a location they've never been to and the system hasn't
  generated yet. An NPC might describe it in vague, consistent-with-WorldSeed terms.
  The actual generation waits until the player travels there.

- **EC-4.6**: World entity count exceeds the 10,000 limit (highly active, long game).
  System archives entities in unvisited, distant regions — they persist in cold
  storage but don't consume active graph resources.

- **EC-4.7**: Player's actions trigger a chain reaction that would modify hundreds
  of entities (e.g., a kingdom-wide war). System batches updates and applies
  them over several turns, narrating the spreading impact.

- **EC-4.8**: Weather and time of day conflict with the WorldSeed's `defining_detail`
  ("the sky is always amber"). The defining detail overrides standard simulation:
  the sky *is* always amber, and weather/time manifest differently in this world.

---

## Acceptance Criteria

- **AC-4.1**: Given a player is in a location, when they type "look around," then
  the world model provides the narrative engine with: current entities present,
  environmental conditions, time of day, and active events — within 200ms.

- > **[v2 — Cascading State]** Requires a world-tick engine that propagates state
  > changes across entities. v1 tracks world_changes from LLM output but does not
  > cascade effects to nearby entities autonomously.

  **AC-4.2**: Given a player sets fire to a building, when the turn resolves, then
  the building's state changes to "burning," nearby NPC behaviors change, and
  subsequent turns reflect the fire's progression.

- **AC-4.3**: Given a player leaves a location and returns 20 turns later, when they
  arrive, then the Diff query returns all state changes that occurred during their
  absence, and the narrative reflects those changes.

- > **[v2 — Region Generation]** Requires on-demand region generation with adjacency
  > consistency checks. v1 uses a single pre-seeded world; dynamic region expansion
  > is deferred to v2.

  **AC-4.4**: Given a player travels to an ungenerated region, when they arrive, then
  a new region is generated within 3 seconds, consistent with WorldSeed parameters
  and adjacent region characteristics.

- > **[v2 — World Ticks]** Requires an autonomous world-tick scheduler that advances
  > NPC schedules and environmental state independently of player actions. v1 reflects
  > time-of-day in narrative prompts but does not move NPCs autonomously.

  **AC-4.5**: Given it is midday in the world and the player waits for several turns,
  when time advances to evening, then NPC positions change (shops close, schedules
  shift) and location descriptions reflect the time change.

- **AC-4.6**: Given the player has visited 5 regions, when they revisit any of them,
  then each region has a distinct identity (different terrain, culture, atmosphere).

- > **[v2 — Scale]** Requires Neo4j graph backend for performant traversal at this
  > entity count. v1 uses in-memory world state with smaller worlds.

  **AC-4.7**: Given the world model has 5,000 entities, when a Nearby query runs,
  then it completes within 200ms.

- **AC-4.8**: Given a player's session crashes mid-turn, when they resume, then the
  world state is restored to the last completed turn (no corruption from partial
  updates).

---

## Dependencies

| Spec | Relationship |
|------|-------------|
| **S01 — Gameplay Loop** | Every turn reads and updates the world model. |
| **S02 — Genesis** | Genesis generates the initial world state from the WorldSeed. |
| **S03 — Narrative Engine** | The engine queries the world model for every generation call. |
| **S05 — Choice & Consequence** | Consequences modify world state. |
| **S06 — Character System** | NPC state is part of the world model. PC presence in the world is tracked. |
| **S13 — Storage Schema** | The storage layer must support the domain model defined here. |

---

## Open Questions

- **OQ-4.1**: How much off-screen simulation is worth the compute cost? Every off-
  screen NPC movement is a state write. Should off-screen updates be deferred until
  the player approaches?

- **OQ-4.2**: Should the world have a "physics" layer (gravity, temperature, material
  properties) or is that over-engineering for a text game? Leaning toward no — the
  narrative engine handles physics narratively.

- **OQ-4.3**: How do we handle world generation consistency across model versions?
  If the LLM used for lazy generation is upgraded, new regions might feel different
  from old ones. Is this acceptable?

- **OQ-4.4**: Should the world model support "alternate timelines" for speculative
  consequence evaluation ("what would happen if...")?  Probably out of scope for v1.

- **OQ-4.5**: How fine-grained should time tracking be? Minutes? Hours? "Morning/
  afternoon/evening/night"? Finer time allows more simulation but adds complexity.

- **OQ-4.6**: Should items have durability/degradation? A sword that dulls over time
  adds simulation depth but increases tracking overhead.

---

## Out of Scope (v1)

- Procedural terrain generation (maps, hex grids, spatial coordinates)
- Physics simulation
- Economic simulation (supply/demand, pricing models)
- Ecology simulation (animal populations, food chains)
- Real-time world updates (world only advances on player turns)
- Multi-world interactions (portals between different players' worlds)
- Player-built structures or world modifications beyond state changes
- Minimap or visual world representation

---

## v1 Closeout (Non-normative)

> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ⚠️ Partial
>
> This section is retrospective. It records what shipped in v1, what was verified,
> gaps found via simulation and code review, and what is deferred to v2. No FRs or
> ACs are modified here.

### Implementation Fit

| Item | Shipped | Verified | Evidence | Notes |
|------|---------|----------|----------|-------|
| AC-4.1 WorldContext on "look around" | ✅ Yes | ✅ Unit tests | `tests/unit/world/test_s04_ac_compliance.py` TestAC401 — 6 tests (location, NPCs, items, exits, conditions) | Time-of-day and active_events fields absent from v1 WorldContext |
| AC-4.2 Cascading state on fire/destruction | ❌ No | — | Pre-marked `[v2]` in spec | No world-tick engine in v1; world_changes from LLM output applied but do not cascade to neighbouring entities |
| AC-4.3 Diff query returns changes | ⚠️ Partial | ✅ Unit tests | `test_s04_ac_compliance.py` TestAC403 — 3 tests | Changes stored and retrievable; automatic narrative diff on revisit deferred to v2 |
| AC-4.4 Lazy region generation | ❌ No | — | Pre-marked `[v2]` in spec | v1 uses 2 pre-seeded templates (`haunted_manor`, `quiet_village`); no on-demand generation |
| AC-4.5 NPC schedule / day-night advance | ❌ No | — | Pre-marked `[v2]` in spec | Time-of-day injected into prompts as narrative flavour only; no autonomous NPC movement |
| AC-4.6 Distinct region identity | ✅ Yes | ✅ Unit tests | `test_s04_ac_compliance.py` TestAC406 — 4 tests | Template metadata keys, archetypes, tones and scales verified distinct |
| AC-4.7 5000-entity Nearby ≤200ms | ❌ No | — | Pre-marked `[v2]` in spec | In-memory world state used when Neo4j unavailable; scale not benchmarked |
| AC-4.8 Atomic state restoration | ✅ Yes | ✅ Unit tests | `test_s04_ac_compliance.py` TestAC408 — 4 tests | Batch changes applied atomically; idempotency and empty-batch safety confirmed |
| FR-1.x World entity graph | ✅ Yes | ✅ Neo4j service + unit tests | `src/tta/world/neo4j_service.py`; `tests/unit/world/test_neo4j_service.py` | Location, Region, NPC, Item nodes and relationships wired |
| FR-2.3/FR-2.4 Atomic + logged changes | ✅ Yes | ✅ Unit tests | `src/tta/world/changes.py`; `test_changes.py` | Change log persisted per turn |
| FR-4.1 Starting location from template | ⚠️ Partial | ✅ Code review | `neo4j_service.py:289–290` reads `is_starting_location`; fallback to `locations[0]` at line 504–505 | Spawn correct when Neo4j available; falls back to first list entry when Neo4j is offline — sim showed wrong-location spawn under fallback path |
| FR-4.2/4.3 Lazy / deterministic generation | ❌ No | — | Pre-marked `[v2]` in spec | World is entirely pre-seeded from templates |
| FR-6.1/6.2 Incremental persistence | ⚠️ Partial | ✅ Code review | `src/tta/world/service.py`; world_changes stored after each turn | Full entity-state snapshot (FR-6.2) not implemented; no chapter-boundary snapshot |
| FR-6.3 World state rollback | ❌ No | — | Not implemented | Rollback is ad-hoc; no explicit snapshot/restore API |
| FR-7.1/7.2 Nearby query ≤200ms | ⚠️ Partial | ✅ Unit tests | `test_world_service.py`, `test_neo4j_service.py` | Query implemented; 200ms SLA not benchmarked; in-memory fallback used when Neo4j offline |

**Overall**: World structure, atomic changes, and starting-location handling ship in v1.
Simulation FRs (FR-3.x), lazy generation (FR-4.2–4.5), full persistence (FR-6.2–6.3),
and scale (FR-7 SLAs) are entirely v2. 5 of 8 ACs have partial or full coverage.

### Gaps Found

**Gap 1 — Spawn point fallback uses wrong location.**
`neo4j_service.py` lines 289–290 correctly reads `is_starting_location: true` from the
template. However, when Neo4j is unavailable (offline dev environment, CI) the code
falls through to the fallback at line 504–505 which takes `tmpl.locations[0]` — the
first location in the list by definition order, not the marked starting location. In
the `haunted_manor` template this happens to be `loc_gate` (which is the starting
location), but any template where the starting location is not first in the JSON
`locations` array will spawn the player at the wrong place. Simulation confirmed this
produces misleading "you are at X" context assembly even when the narrative described
arriving at Y.

**Gap 2 — Spatial continuity under Neo4j fallback.**
When Neo4j is unavailable, `context.py` `get_full_context()` falls back to the
`game_state` dict, which only tracks player location as a string label — not a canonical
graph node identifier. Across 3–4 turns the LLM can drift the location label (e.g.,
"the gatehouse" vs "the rusted iron gate at the estate entrance") with no constraint,
producing incoherent movement tracking. This is a v2 root-cause fix: Neo4j must be
treated as a hard dependency for location identity, not an optional enhancement.

**Gap 3 — No diff-driven narrative on revisit.**
AC-4.3's change storage works, but the narrative engine (S03/S08) never reads the diff
on player return — there is no "what changed since you were last here" injection into the
generation prompt. The data exists; the plumbing to use it does not.

**Gap 4 — Simulation FRs silent in v1.**
FR-3.2–FR-3.8 (time, day/night, weather, NPC schedules, off-screen events, proximity
simulation) are entirely absent. They are marked `[v2]` in the ACs but the FRs
themselves do not carry the `[v2 —]` notation. This creates a false impression that
simulation is partially implemented when it is entirely deferred.

### Deferred to v2

| Item | Reason | v2 Priority |
|------|--------|-------------|
| World-tick engine (FR-3.x) | Requires autonomous scheduler and event propagation beyond turn-driven updates | High |
| Cascading state effects (AC-4.2) | Requires world-tick + entity dependency graph | High |
| Lazy / deterministic region generation (AC-4.4, FR-4.2–4.5) | Requires on-demand LLM region seeding with adjacency constraint solver | High |
| NPC schedule simulation (AC-4.5, FR-3.5) | Requires world-tick + NPC routine engine | Medium |
| Off-screen events (FR-3.6) | Requires world-tick with event cascade rules | Medium |
| 5000-entity scale + 200ms SLA (AC-4.7, NFR-4.1) | Requires Neo4j as mandatory dependency with benchmarked indexing | Medium |
| Full world snapshot + chapter-boundary snapshot (FR-6.2) | Requires coordinated snapshot across PostgreSQL + Neo4j + Redis | Medium |
| World state rollback API (FR-6.3) | Requires snapshot/restore protocol with transaction support | Low |
| Diff-driven revisit narration (AC-4.3 full) | Needs change diff injected into generation prompt by S08 context stage | Medium |
| Spawn fallback correctness (FR-4.1) | Fix: fallback should filter by `is_starting_location` rather than take `[0]` | High (quick fix) |
