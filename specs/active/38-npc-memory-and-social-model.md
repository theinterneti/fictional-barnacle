# S38 — NPC Memory & Social Model

> **Status**: ✅ Approved
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 2 — Simulation
> **Dependencies**: v1 S06 (Characters & Relationships), S33 (Universe Persistence), S35 (NPC Autonomy), S37 (World Memory Model)
> **Related**: S36 (Consequence Propagation), S62 (Story Export, v5+)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

v1 tracks NPC relationships as a five-axis numeric vector (`RelationshipDimensions`:
trust, affinity, respect, fear, familiarity). This vector captures *how* an NPC
feels toward the player, but not *why* or *what specifically happened*. There is
no episodic memory — NPCs cannot recall the event where trust was lost, cannot
gossip about it to other NPCs, and forget everything when the session ends.

S38 adds two complementary layers on top of v1's relationship model:

1. **Episodic Memory**: each NPC maintains a timestamped log of significant
   interactions with the player — the events that shaped the relationship vector.
   KEY and SUPPORTING NPCs retain episodic memory across sessions (universe-scoped).

2. **Social Graph & Gossip**: NPCs are connected by a social relationship graph
   (distinct from the world geography graph used by S36). NPCs with sufficient
   familiarity gossip knowledge about the player to their social neighbors,
   propagating reputation across the cast without player involvement.

This spec defines `NPCEpisodicMemory`, `NPCSocialEdge`, `GossipEvent`,
`SocialMemoryWriter`, and the gossip propagation rules.

---

## 2. Design Philosophy

### 2.1 S38 vs S36 — Two Propagation Systems

S36 (Consequence Propagation) and S38 (NPC Social) are complementary but distinct:

| Dimension | S36 — Consequence Propagation | S38 — NPC Social Gossip |
|-----------|-------------------------------|-------------------------|
| Graph | World geography (`CONNECTS_TO`) | Social relationships (`KNOWS`) |
| Unit | `ConsequenceRecord` | `GossipEvent` |
| Trigger | World events exceeding severity threshold | NPC familiarity + opportunity |
| Content | Factual event description (distorted by hop) | Player-reputation fragment |
| Scope | Reaches all entities near an event | Travels NPC-to-NPC selectively |
| Memory | Written to world memory (S37) | Written to NPC episodic memory (S38) |

A `ConsequenceRecord` (S36) traveling from an explosion may cause an NPC to hear
a rumor. That rumor becomes a `GossipEvent` in S38 when the NPC passes it on.

### 2.2 S38 vs S37 — Two Memory Systems

S37 (World Memory Model) is the canonical record of what happened in the world.
S38 (NPC Memory) is how individual NPCs *interpret and remember* those events:

| Dimension | S37 — World Memory | S38 — NPC Episodic Memory |
|-----------|-------------------|--------------------------|
| Scope | Session / universe | Per-NPC |
| Content | Objective event description | NPC-filtered interpretation |
| Persistence | Universe-scoped in Neo4j | Universe-scoped for KEY/SUPPORTING |
| Attribution | `attributed_to` entity ID | Stored under NPC ID |
| Compression | LLM-summarized blocks | Not compressed (relationship-critical) |

An `NPCEpisodicMemory` record SHOULD reference its source `MemoryRecord` by ID.
It is NOT a copy — it is an interpretation with emotional valence and an NPC-specific
framing (`"Elara remembers the player betrayed her at the docks"`). 

### 2.3 Cross-Session Memory for KEY NPCs

KEY NPCs survive session boundaries. Their `RelationshipDimensions` and episodic
memories are stored in the universe's persistent Neo4j graph, attached to the NPC
node. When a new session begins in the same universe, KEY NPC relationships are
restored from the graph. BACKGROUND NPCs have no cross-session memory.

---

## 3. User Stories

> **US-38.1** — **As a** player, NPCs I wronged in a previous session are still cold
> toward me when I return, because they remember what happened.

> **US-38.2** — **As a** player, an NPC I've never met is already wary of me because
> they heard about my actions from a mutual acquaintance.

> **US-38.3** — **As a** player, when I ask an NPC about a past event, they can
> specifically reference it ("That time you broke your promise at the market…")
> rather than just expressing vague distrust.

> **US-38.4** — **As a** universe author, I can configure how aggressively NPCs
> gossip and how quickly reputation travels through the social graph.

> **US-38.5** — **As a** developer, I can query all episodic memories for an NPC,
> sorted by importance, to debug why an NPC has a particular relationship score.

---

## 4. Functional Requirements

### FR-38.01 — NPCEpisodicMemory Type

A single episodic memory record for a specific NPC:

| Field | Type | Description |
|-------|------|-------------|
| `episode_id` | ULID | Unique identifier. |
| `npc_id` | str | The NPC who holds this memory. |
| `universe_id` | ULID | Owning universe. |
| `session_id` | UUID | Session in which this memory was formed. |
| `turn_number` | int | Turn number at creation. |
| `world_time_tick` | int | `WorldTime.total_ticks` at creation (S34). |
| `source_memory_id` | ULID or null | The `MemoryRecord` (S37) that originated this episode. |
| `consequence_id` | ULID or null | `ConsequenceRecord` (S36) if this was triggered by propagation. |
| `player_id` | str | Player entity this memory concerns. |
| `content` | str | NPC-framed narrative of the event. |
| `emotional_valence` | float [-1.0, 1.0] | Negative = negative experience; positive = positive. |
| `relationship_delta` | RelationshipChange or null | Dimension changes applied when this memory was formed. |
| `importance_score` | float [0.0, 1.0] | Importance at write time (same scoring rules as S37.FR-37.04). |
| `is_gossip` | bool | True if this memory was received via gossip rather than direct experience. |
| `gossip_source_npc_id` | str or null | The NPC who gossiped this memory to this NPC. |
| `created_at` | datetime | Wall-clock time of record creation. |

### FR-38.02 — NPCSocialEdge Type

A directed social relationship in the NPC graph:

| Field | Type | Description |
|-------|------|-------------|
| `edge_id` | ULID | Unique identifier. |
| `source_npc_id` | str | The NPC holding this relationship view. |
| `target_id` | str | NPC ID or player ID (relationship target). |
| `universe_id` | ULID | Owning universe (relationships are universe-scoped). |
| `dimensions` | RelationshipDimensions | The five-axis vector (trust, affinity, respect, fear, familiarity). |
| `gossip_weight` | float [0.0, 1.0] | How likely this NPC is to gossip about `target_id` to others. |
| `updated_at` | datetime | Last modification time. |

- **FR-38.02a**: `NPCSocialEdge` extends (not replaces) v1's `NPCRelationship`. The
  `dimensions` field maps directly to v1's `RelationshipDimensions`.
- **FR-38.02b**: `gossip_weight` defaults to `familiarity / 100.0`.
  Universe authors may override via NPC template.

### FR-38.03 — GossipEvent Type

A single unit of gossip traveling through the social graph:

| Field | Type | Description |
|-------|------|-------------|
| `gossip_id` | ULID | Unique identifier. |
| `universe_id` | ULID | Owning universe. |
| `originating_episode_id` | ULID | The `NPCEpisodicMemory` that originated this gossip. |
| `sender_npc_id` | str | NPC sending this gossip. |
| `receiver_npc_id` | str | NPC receiving this gossip. |
| `content` | str | Gossip text (may be distorted from original). |
| `hop_count` | int | Number of NPC-to-NPC hops from the direct witness. |
| `reliability` | float [0.0, 1.0] | `1.0` at hop-0 (direct), decrements 0.2 per hop. |
| `session_id` | UUID | Session in which gossip was generated. |
| `world_time_tick` | int | Tick at which gossip was generated. |
| `created_at` | datetime | Wall-clock time. |

### FR-38.04 — SocialMemoryWriter Contract

```python
async def record_episode(
    npc_id: str,
    universe_id: str,
    session_id: UUID,
    turn_number: int,
    world_time: WorldTime,
    content: str,
    emotional_valence: float,
    relationship_delta: RelationshipChange | None,
    source_memory_id: str | None,
    consequence_id: str | None,
    is_gossip: bool,
    gossip_source_npc_id: str | None,
) -> NPCEpisodicMemory: ...

async def propagate_gossip(
    episode_id: str,
    universe_id: str,
    session_id: UUID,
    world_time: WorldTime,
    max_hops: int,
) -> list[GossipEvent]: ...

async def get_npc_context(
    npc_id: str,
    universe_id: str,
    player_id: str,
    budget_tokens: int,
) -> NPCSocialContext: ...

async def get_relationship(
    npc_id: str,
    target_id: str,
    universe_id: str,
) -> NPCSocialEdge | None: ...

async def update_relationship(
    npc_id: str,
    target_id: str,
    universe_id: str,
    change: RelationshipChange,
) -> NPCSocialEdge: ...
```

- **FR-38.04a**: `SocialMemoryWriter` MUST be injectable.
  An `InMemorySocialMemoryWriter` MUST exist for unit testing.
- **FR-38.04b**: `get_npc_context()` returns a `NPCSocialContext` containing:
  the current `NPCSocialEdge` between this NPC and the player, a trimmed list
  of `NPCEpisodicMemory` records sorted by `importance_score` descending, and
  any `GossipEvent` records received by this NPC about the player.
- **FR-38.04c**: `propagate_gossip()` is fire-and-forget (async, non-blocking).
  It MUST NOT delay the current turn's generation pipeline.

### FR-38.05 — Gossip Propagation Rules

After `record_episode()` creates a direct experience (`is_gossip = False`):

1. The `SocialMemoryWriter` queries the NPC's social neighbors: all NPCs connected
   via `NPCSocialEdge` with `familiarity >= gossip_familiarity_threshold`
   (default: 30, configurable via `universes.config["social"]["gossip_familiarity_threshold"]`).
2. For each neighbor, a `GossipEvent` is created with `hop_count = 1`,
   `reliability = 0.8`, and content distorted by a template rule (NOT an LLM call).
3. The receiving NPC gains a new `NPCEpisodicMemory` via `record_episode()` with
   `is_gossip = True`, `gossip_source_npc_id` set, and `importance_score` scaled
   by `reliability`.
4. Gossip propagates recursively up to `max_gossip_hops` (default: 2,
   configurable via `universes.config["social"]["max_gossip_hops"]`).
5. **Reliability floor**: gossip with `reliability < 0.2` is NOT propagated further.
6. **No LLM calls in gossip propagation**: all distortion is template-based.
   LLM summarization of gossip chains is deferred to a future spec.

### FR-38.06 — Cross-Session Persistence

| NPC Tier | Persistence Scope | Who Persists |
|----------|------------------|--------------|
| KEY | Universe-scoped | All `NPCEpisodicMemory` + `NPCSocialEdge` persisted to Neo4j universe node |
| SUPPORTING | Universe-scoped | `NPCSocialEdge` persisted; episodic memory persisted for episodes with `importance_score >= 0.5` |
| BACKGROUND | Session-scoped | No cross-session persistence |

- **FR-38.06a**: At session start, KEY and SUPPORTING NPC relationships are loaded
  from the universe's persistent graph.
- **FR-38.06b**: At session end (or game state transition to `completed` or
  `abandoned`), KEY and SUPPORTING NPC data is flushed to Neo4j.

### FR-38.07 — Integration with S35 (NPC Autonomy)

When `AutonomyProcessor.process()` (S35) generates `NarrativeEventAction` for an NPC
(e.g., an NPC moves or changes disposition), the `SocialMemoryWriter` records an
episodic memory for affected social neighbors if the action involves the player
or changes a relationship dimension.

### FR-38.08 — Integration with S36 (Consequence Propagation)

When a `ConsequenceRecord` is received by an NPC via `ConsequencePropagator.propagate()`
(S36), and the `ConsequenceRecord` references the player:

1. `record_episode()` is called with `consequence_id` populated.
2. `emotional_valence` is derived from the consequence severity:
   - `critical` → ±0.8 (sign depends on event type)
   - `major` → ±0.6
   - `notable` → ±0.3
   - `minor` → ±0.1
3. `relationship_delta` is computed from the consequence type and applied.

### FR-38.09 — NPCSocialContext Type

The output of `get_npc_context()`, injected into dialogue generation context:

| Field | Type | Description |
|-------|------|-------------|
| `npc_id` | str | The NPC. |
| `player_id` | str | The player. |
| `relationship` | NPCSocialEdge or null | Current relationship edge. |
| `episodes` | list[NPCEpisodicMemory] | Trimmed, sorted by importance desc. |
| `gossip_received` | list[GossipEvent] | Gossip events this NPC received about player. |
| `total_tokens` | int | Estimated token count of this context. |
| `dropped_count` | int | Episodes dropped to fit budget. |

---

## 5. Non-Functional Requirements

### NFR-38.01 — record_episode() Latency
`record_episode()` MUST complete in under 20 ms (p95), excluding async gossip propagation.

### NFR-38.02 — get_npc_context() Latency
`get_npc_context()` MUST complete in under 50 ms (p95) for an NPC with up to 200
episodic memory records.

### NFR-38.03 — Gossip Non-Blocking
`propagate_gossip()` is async, fire-and-forget. It MUST NOT delay the turn pipeline
by more than 5 ms.

### NFR-38.04 — No LLM in Gossip Path
Gossip propagation (FR-38.05) MUST NOT make LLM calls. Template-only distortion.
This ensures gossip scales without LLM cost per hop.

### NFR-38.05 — Observability
Every `record_episode()` MUST emit a structlog event with `episode_id`, `npc_id`,
`importance_score`, `is_gossip`, and `hop_count` (if gossip).
Every `propagate_gossip()` run MUST emit `gossip_id`, `sender`, `receiver`,
`hop_count`, and `reliability`.

### NFR-38.06 — Test Coverage
Unit tests MUST cover: importance scoring, gossip propagation to depth 2,
reliability floor stopping propagation, cross-session KEY NPC relationship restore,
BACKGROUND NPC no-persistence, S36 integration (consequence → episode), and
budget trimming in `get_npc_context()`.

---

## 6. User Journeys

### Journey 1: Player Betrays KEY NPC (Cross-Session Consequence)

**Turn N**: Player chooses to betray Commander Vesh (KEY NPC, familiarity=60,
trust=40). A `ConsequenceRecord` with severity `major` referencing the player is
generated (S36).

1. `record_episode()` called for Vesh: `emotional_valence = -0.6`,
   `relationship_delta = RelationshipChange(trust=-20, affinity=-15, respect=-10)`.
2. Episode stored in Neo4j under Vesh's universe node.
3. Gossip propagation fires: Vesh's familiarity-30+ neighbors (3 NPCs) receive
   `GossipEvent` (hop_count=1, reliability=0.8): "Vesh was betrayed by {player_name}".
4. Those 3 NPCs gain episodic memories (`is_gossip=True`), relationship deltas applied.
5. **Next session**: player loads the universe. Vesh's `RelationshipDimensions`
   restored from Neo4j: trust=-20 from base. Vesh greets player coldly.
   `get_npc_context()` returns Vesh's episodes — the betrayal event is visible to
   the generation model, enabling specific dialogue.

### Journey 2: Player's Reputation Travels (Gossip Propagation)

**Turn 15**: Player rescues innkeeper Carla (SUPPORTING, familiarity=45) from bandits.
Positive `ConsequenceRecord` (notable). `record_episode()` creates a positive
episode for Carla: `emotional_valence = +0.3`, trust+10.

1. Gossip propagation: Carla's neighbors include the blacksmith (familiarity=55)
   and the merchant (familiarity=30 — exactly at threshold).
2. Both receive `GossipEvent` (hop_count=1, reliability=0.8): "Carla says {player_name}
   saved her from bandits."
3. Blacksmith gossips further to the guard captain (familiarity=40):
   hop_count=2, reliability=0.6, content distorted to "{player_name} drove off
   some trouble near the inn."
4. At hop_count=3, reliability would be 0.4 — still above 0.2 floor, but
   `max_gossip_hops = 2` stops propagation here.
5. When player meets the guard captain, `get_npc_context()` includes the hop-2
   gossip event — captain's tone is slightly warmer (relationship delta scaled
   by reliability: trust+5 × 0.6 = trust+3).

### Journey 3: Budget-Trimmed NPC Context

KEY NPC with 150 episodic memories. `get_npc_context(budget_tokens=1000)` called.

1. `NPCSocialEdge` summary: ~100 tokens.
2. Top-15 episodes by `importance_score` desc: ~700 tokens.
3. Top-5 gossip events: ~200 tokens.
4. Total: ~1000 tokens. `dropped_count = 135` episodes excluded.
5. Generation model receives a focused, budget-compliant NPC context.

---

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | `record_episode()` called for a BACKGROUND NPC | Stored in session memory only (not Neo4j persistent); no cross-session restore |
| E2 | Gossip cycle: A gossips to B, B gossips to A | Idempotency: `originating_episode_id` check prevents recording the same gossip twice |
| E3 | NPC's social neighbors all below familiarity threshold | No gossip events generated; log DEBUG |
| E4 | Cross-session restore fails (Neo4j unavailable) | Use baseline `RelationshipDimensions` (all zeros); log WARNING; session continues |
| E5 | `emotional_valence` supplied outside [-1.0, 1.0] | Clamp silently to range |
| E6 | `get_npc_context()` called for NPC with no episodes | Return empty `NPCSocialContext` with null relationship |
| E7 | Gossip loops through 3+ NPCs with same episode | `seen_episode_ids` set in propagation call prevents re-processing |
| E8 | SUPPORTING NPC episode importance < 0.5 at session flush | Not persisted cross-session; log DEBUG |

---

## 8. Acceptance Criteria (Gherkin)

```gherkin
Feature: NPC Memory & Social Model

  Background:
    Given a universe with social config:
      | gossip_familiarity_threshold | 30 |
      | max_gossip_hops              | 2  |
    And a KEY NPC "Vesh" with familiarity=60, trust=40
    And a SUPPORTING NPC "Carla" with familiarity=45, trust=20
    And a BACKGROUND NPC "Passerby" with familiarity=5

  Scenario: AC-38.01 — Episodic memory is created with correct importance score
    Given a direct player interaction with Vesh causing a major consequence
    When SocialMemoryWriter.record_episode() is called
    Then a NPCEpisodicMemory is created with is_gossip = False
    And importance_score reflects the major consequence boost

  Scenario: AC-38.02 — Gossip propagates to familiarity-threshold neighbors
    Given Vesh has a direct episode from the player interaction
    When propagate_gossip() fires
    Then GossipEvents are created for Vesh's neighbors with familiarity >= 30
    And each receiving NPC gains a NPCEpisodicMemory with is_gossip = True

  Scenario: AC-38.03 — Gossip reliability decrements per hop
    Given a hop-1 GossipEvent with reliability = 0.8
    When that NPC propagates to a hop-2 neighbor
    Then the resulting GossipEvent has reliability = 0.6

  Scenario: AC-38.04 — Gossip stops at max_gossip_hops
    Given a GossipEvent at hop_count = 2
    When propagate_gossip() is called for the receiving NPC
    Then no further GossipEvents are created

  Scenario: AC-38.05 — Gossip stops at reliability floor
    Given a GossipEvent with reliability below 0.2
    When propagate_gossip() checks this event
    Then no further GossipEvents are created

  Scenario: AC-38.06 — KEY NPC episodes persist across sessions
    Given Vesh has a NPCEpisodicMemory from session 1
    When a new session 2 begins in the same universe
    Then Vesh's RelationshipDimensions and episodic memories are restored

  Scenario: AC-38.07 — BACKGROUND NPC has no cross-session memory
    Given Passerby has an episode from session 1
    When a new session 2 begins in the same universe
    Then Passerby has no restored episodes
    And Passerby's RelationshipDimensions start at zero

  Scenario: AC-38.08 — S36 consequence triggers episode with emotional_valence
    Given a critical ConsequenceRecord referencing the player arrives for Vesh
    When SocialMemoryWriter processes the consequence
    Then a NPCEpisodicMemory is created with emotional_valence = ±0.8
    And the relationship delta is applied to Vesh's NPCSocialEdge
```

---

## 9. Out of Scope

- NPC-to-NPC relationships (other than gossip conduit): tracked in `NPCSocialEdge`
  but emotional valence between NPCs (not involving the player) is deferred to v3+.
- Multiplayer: one NPC remembering multiple players — deferred to v4+ (OQ-38.01).
- LLM-assisted gossip distortion — deferred to a future spec.
- Gossip about events NOT involving the player — deferred to v3+.
- NPC-to-player direct memory sharing (NPCs tell the player what they heard) — this
  is a generation/dialogue concern, not a memory model concern.

---

## 10. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-38.01 | NPC memory in multiplayer (v4+): one NPC, multiple players — how does that work? | ⏳ Open | Deferred to v4+ as out of scope for v2.0. The `player_id` field in `NPCEpisodicMemory` explicitly supports one player per episode; multi-player extension will require per-player episode partitioning. |
| OQ-38.02 | Should gossip distortion be template-only (FR-38.05) or LLM-assisted? | ✅ Resolved | **Template-only** for v2.0 (no LLM cost per hop). LLM-assisted gossip distortion deferred to a future enhancement. |
| OQ-38.03 | Should `NPCSocialEdge` store NPC↔NPC relationships, or only NPC↔player? | ⏳ Open | Proposed: NPC↔NPC edges stored but only `familiarity` dimension populated in v2.0 (needed for gossip routing). Full five-axis NPC↔NPC relationships deferred to v3+. |

---

## Appendix A — Type Shapes

```python
from dataclasses import dataclass, field
from datetime import datetime
from tta.models.world import RelationshipDimensions, RelationshipChange

@dataclass
class NPCEpisodicMemory:
    episode_id: str             # ULID
    npc_id: str
    universe_id: str
    session_id: str             # UUID
    turn_number: int
    world_time_tick: int
    source_memory_id: str | None
    consequence_id: str | None
    player_id: str
    content: str
    emotional_valence: float    # [-1.0, 1.0]
    relationship_delta: RelationshipChange | None
    importance_score: float     # [0.0, 1.0]
    is_gossip: bool
    gossip_source_npc_id: str | None
    created_at: datetime = field(default_factory=lambda: datetime.now())

@dataclass
class NPCSocialEdge:
    edge_id: str                # ULID
    source_npc_id: str
    target_id: str              # NPC ID or player ID
    universe_id: str
    dimensions: RelationshipDimensions = field(
        default_factory=RelationshipDimensions
    )
    gossip_weight: float = 0.0  # familiarity / 100.0 by default
    updated_at: datetime = field(default_factory=lambda: datetime.now())

@dataclass
class GossipEvent:
    gossip_id: str              # ULID
    universe_id: str
    originating_episode_id: str
    sender_npc_id: str
    receiver_npc_id: str
    content: str
    hop_count: int
    reliability: float          # [0.0, 1.0]; decrements 0.2/hop
    session_id: str
    world_time_tick: int
    created_at: datetime = field(default_factory=lambda: datetime.now())
```

## Appendix B — Gossip Propagation Flowchart

```
record_episode(is_gossip=False)
  │
  └─► propagate_gossip() [async, fire-and-forget]
        │
        ├─► Query social neighbors where familiarity >= threshold
        │
        ├─► For each neighbor:
        │     ├─► Create GossipEvent(hop_count=1, reliability=0.8)
        │     ├─► Distort content via template
        │     └─► record_episode(is_gossip=True, gossip_source=self)
        │           │
        │           └─► [recursive] propagate_gossip() if hop_count < max_hops
        │                 │   AND reliability >= 0.2
        │                 │   AND episode NOT already seen
        │                 └─► ... (up to max_hops depth)
        │
        └─► Log all created GossipEvents
```

## Appendix C — Persistence by Tier

```
Session end / game state → completed|abandoned:

  KEY NPC:
    └─► ALL NPCEpisodicMemory → Neo4j (NPC node, universe-scoped)
    └─► NPCSocialEdge (player↔npc, npc↔npc familiarity) → Neo4j

  SUPPORTING NPC:
    └─► NPCEpisodicMemory where importance_score >= 0.5 → Neo4j
    └─► NPCSocialEdge (player↔npc) → Neo4j

  BACKGROUND NPC:
    └─► No persistence. In-session only.

Session start / universe load:

  KEY + SUPPORTING NPCs:
    └─► NPCSocialEdge restored from Neo4j (→ RelationshipDimensions)
    └─► Top-50 episodes by importance_score restored for KEY NPCs
    └─► Top-20 episodes by importance_score restored for SUPPORTING NPCs
```

## Appendix D — Pipeline Position

```
Turn Pipeline (v2 Enrich stage):
  1. Understand stage (parse intent)
  2. AutonomyProcessor.process()          →  WorldDelta              [S35]
  3. ConsequencePropagator.propagate()    →  PropagationResult       [S36]
  4. MemoryWriter.record()                →  MemoryRecord[]          [S37]
     └─► compress_if_needed() (async)
  5. SocialMemoryWriter.record_episode()  →  NPCEpisodicMemory[]     [S38] ← THIS SPEC
     └─► propagate_gossip() (async)
  6. Context assembly: get_context()      →  MemoryContext
                      get_npc_context()   →  NPCSocialContext[]
  7. Generate stage
  8. Stream stage
```
