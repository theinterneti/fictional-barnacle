# v2 Universe & Simulation — Component Technical Plan

> **Phase**: SDD Phase 2 — Component Technical Plan
> **Scope**: Universe entity, Session↔Universe binding, Actor identity, Transport
>   abstraction, Simulation layer (Diegetic Time, NPC Autonomy, Consequence Propagation,
>   World Memory, NPC Social), Universe Composition
> **Input specs**: S29, S30, S31, S32, S33, S34, S35, S36, S37, S38, S39
> **Parent plan**: `plans/system.md` (authoritative — all decisions here must be compatible)
> **Status**: 📝 Draft
> **Last Updated**: 2026-04-22

---

## 0. Resolved Conflicts and Normative Decisions

These decisions are **locked** for v2. Component code must comply; they may be
extended but not altered without updating this section.

| # | Decision |
|---|----------|
| 0.1 | `universes` is a new first-class PostgreSQL table. `world_seed` on `game_sessions` is **preserved read-only** — not dropped, not renamed. |
| 0.2 | `game_sessions.universe_id` is a **nullable FK** in v2. NULL means a v1-era session. No back-fill of universe records for v1 sessions. |
| 0.3 | All world-scoped Neo4j nodes (World, Region, Location, NPC, Item, Event, Quest) gain a `universe_id` property. The `session_id` property on those nodes is **kept** (not removed) for backward query compat. |
| 0.4 | `NarrativeTransport` is a `typing.Protocol` (not ABC). `SSETransport` requires no inheritance; duck-typing enforced by type checker only. |
| 0.5 | Simulation sub-systems (S34–S38) run **synchronously in the turn pipeline**, after generation and before serialization. No background jobs in v2. |
| 0.6 | NPC autonomy uses rule-based logic for BACKGROUND and SUPPORTING tiers; a single batched LLM call for KEY-tier NPCs per turn. No per-NPC LLM loop. |
| 0.7 | Memory compression is triggered by token count exceeding `settings.memory_compress_threshold`, not by wall time or calendar. |
| 0.8 | Universe composition (S39) stores its schema version inside the `config` JSON blob as `composition_version`. S33 never inspects the interior of `config`. |
| 0.9 | The `actors` table uses a separate ULID identity, not `player_id`. One player may own multiple actors (v4+ readiness), but v2 enforces one actor per player at the application layer. |
| 0.10 | `universe_snapshots` are taken at session end, not per-turn. Per-turn snapshots remain in v1 `game_snapshots` (unchanged). |

---

## 1. PostgreSQL Schema Extensions

### 1.1 — Design Principles

The v1 → v2 migration is **strictly additive**:
1. New tables are added; no existing table is dropped or renamed.
2. New FK columns added to existing tables use `DEFAULT NULL` and are nullable.
3. All new tables use ULID string primary keys (matching v1 convention).
4. `game_sessions.world_seed` is kept read-only — valid for v1 session archives.

### 1.2 — New Table: `universes`

```sql
CREATE TABLE universes (
    id            TEXT PRIMARY KEY,              -- ULID
    owner_id      TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'dormant'
                  CHECK (status IN ('dormant', 'active', 'paused', 'archived')),
    config        JSONB NOT NULL DEFAULT '{}',   -- UniverseComposition (S39)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_universes_owner_id ON universes(owner_id);
CREATE INDEX idx_universes_status   ON universes(status);
```

**Status lifecycle:**

```
dormant ──(session binds)──► active
active  ──(session ends)───► paused
paused  ──(session binds)──► active
paused  ──(admin archive)──► archived
```

### 1.3 — New Table: `actors`

An Actor is a player's in-world persona. Independent of universe or session.

```sql
CREATE TABLE actors (
    id            TEXT PRIMARY KEY,              -- ULID
    player_id     TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    display_name  TEXT NOT NULL,
    avatar_config JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_actors_player_id ON actors(player_id);
```

> **v2 constraint (application layer only):** One actor per player. Enforced by
> `ActorService.get_or_create_for_player()`. The schema allows multiple rows per
> `player_id` intentionally (v4+ readiness — multi-universe residency).

### 1.4 — New Table: `character_states`

Character state is the union of (actor, universe). It captures how the actor exists
within a particular universe, evolving over play sessions.

```sql
CREATE TABLE character_states (
    id            TEXT PRIMARY KEY,              -- ULID
    actor_id      TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
    universe_id   TEXT NOT NULL REFERENCES universes(id) ON DELETE CASCADE,
    traits        JSONB NOT NULL DEFAULT '[]',   -- list[str]
    inventory     JSONB NOT NULL DEFAULT '[]',   -- list[ItemRef]
    conditions    JSONB NOT NULL DEFAULT '[]',   -- list[Condition]
    reputation    JSONB NOT NULL DEFAULT '{}',   -- {faction_id: float}
    relationships JSONB NOT NULL DEFAULT '{}',   -- {npc_id: RelationshipDimensions}
    custom        JSONB NOT NULL DEFAULT '{}',   -- extensible for v4+
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (actor_id, universe_id)
);

CREATE INDEX idx_character_states_actor_id    ON character_states(actor_id);
CREATE INDEX idx_character_states_universe_id ON character_states(universe_id);
```

### 1.5 — New Table: `universe_snapshots`

Cross-session world-state snapshots taken at session end. Distinct from v1
`game_snapshots` (per-turn crash recovery snapshots).

```sql
CREATE TABLE universe_snapshots (
    id            TEXT PRIMARY KEY,              -- ULID
    universe_id   TEXT NOT NULL REFERENCES universes(id) ON DELETE CASCADE,
    session_id    TEXT REFERENCES game_sessions(id) ON DELETE SET NULL,
    turn_count    INT  NOT NULL DEFAULT 0,
    snapshot      JSONB NOT NULL DEFAULT '{}',
    snapshot_type TEXT NOT NULL DEFAULT 'session_end'
                  CHECK (snapshot_type IN ('session_end', 'manual', 'admin')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_universe_snapshots_universe_id
    ON universe_snapshots(universe_id, created_at DESC);
```

### 1.6 — Extension: `game_sessions`

```sql
ALTER TABLE game_sessions
  ADD COLUMN universe_id TEXT REFERENCES universes(id) ON DELETE SET NULL,
  ADD COLUMN actor_id    TEXT REFERENCES actors(id)    ON DELETE SET NULL;

CREATE INDEX idx_game_sessions_universe_id ON game_sessions(universe_id);
CREATE INDEX idx_game_sessions_actor_id    ON game_sessions(actor_id);
```

`NULL` in both columns signals a v1-era session. All v2 sessions MUST have
both populated at session creation time.

---

## 2. Neo4j Schema Extensions

### 2.1 — `universe_id` Property on All World-Scoped Nodes

Every node type that carried `session_id` now also carries `universe_id`.
The migration adds the property to existing nodes; `session_id` is retained.

Affected labels: `World`, `Region`, `Location`, `NPC`, `Item`, `Event`, `Quest`.

| Property | Type | Required | Indexed | Notes |
|----------|------|----------|---------|-------|
| `universe_id` | String (ULID) | Yes (v2+) | Yes | FK to `universes.id` in Postgres |

**Composite index** (preferred query pattern in v2):

```cypher
CREATE INDEX node_universe_session FOR (n:World)
  ON (n.universe_id, n.session_id);
-- Repeat for Region, Location, NPC, Item, Event, Quest
```

### 2.2 — Diegetic Time Fields on `World` Node (S34)

| Property | Type | Required | Notes |
|----------|------|----------|-------|
| `world_time_tick` | Integer | Yes | Monotonic turn counter within this universe |
| `world_time_hour` | Integer 0–23 | Yes | Derived hour-of-day |
| `world_time_minute` | Integer 0–59 | Yes | Derived minute-of-hour |
| `world_time_label` | String | Yes | One of: `dawn`, `morning`, `noon`, `afternoon`, `dusk`, `evening`, `night`, `midnight` |
| `world_time_config` | String (JSON) | No | Serialized `TimeConfig`; falls back to universe-level default if absent |

### 2.3 — NPC Autonomy State Fields on `NPC` Node (S35)

| Property | Type | Required | Notes |
|----------|------|----------|-------|
| `routine` | String (JSON) | No | Serialized `NPCRoutine`; list of `RoutineStep` keyed by `time_label` |
| `last_processed_tick` | Integer | No | Last tick when autonomy was processed for this NPC |
| `salience_score` | Float | No | Current salience 0.0–1.0; updated each tick |
| `autonomy_state` | String | No | `idle`, `active`, `traveling`, `interacting` |

### 2.4 — Memory Nodes and Edges (S37)

New node label:

```cypher
// MemoryRecord node
CREATE (:MemoryRecord {
  id:          TEXT,   -- ULID
  universe_id: TEXT,
  tick:        INTEGER,
  importance:  FLOAT,
  tier:        TEXT,   -- 'working' | 'active' | 'compressed'
  content:     TEXT,
  source_type: TEXT,   -- 'player_action' | 'npc_action' | 'world_event' | 'consequence'
  created_at:  DATETIME
})
```

Relationships:

```cypher
(:MemoryRecord)-[:RECORDED_IN]->(:World)
(:MemoryRecord)-[:ABOUT_LOCATION]->(:Location)  // optional
(:MemoryRecord)-[:ABOUT_NPC]->(:NPC)            // optional
(:MemoryRecord)-[:CAUSED_BY_ACTOR]->(:Actor)    // optional (Actor is a Neo4j node mirror of actors table)
```

### 2.5 — NPC Social Graph Edges (S38)

New relationship type between NPC nodes:

```cypher
(:NPC)-[:KNOWS {
  familiarity: FLOAT,      -- 0.0–1.0
  relationship_type: TEXT, -- 'friend', 'rival', 'family', 'professional', 'acquaintance'
  last_interaction_tick: INTEGER
}]->(:NPC)
```

---

## 3. Alembic Migration

### 3.1 — Migration Identifier

`v2_universe_entity` — single Alembic revision covering all new tables and column additions.

### 3.2 — Upgrade Steps (Ordered)

```python
# In upgrade():
op.create_table('universes', ...)
op.create_table('actors', ...)
op.create_table('character_states', ...)
op.create_table('universe_snapshots', ...)
op.add_column('game_sessions', sa.Column('universe_id', sa.Text(), nullable=True))
op.add_column('game_sessions', sa.Column('actor_id',    sa.Text(), nullable=True))
op.create_foreign_key(...)   # universe_id -> universes.id
op.create_foreign_key(...)   # actor_id    -> actors.id
op.create_index(...)         # all indexes
```

No data back-fill is performed in the migration itself.

### 3.3 — Downgrade Strategy

```python
# In downgrade():
op.drop_constraint('fk_game_sessions_universe_id', 'game_sessions')
op.drop_constraint('fk_game_sessions_actor_id',    'game_sessions')
op.drop_column('game_sessions', 'universe_id')
op.drop_column('game_sessions', 'actor_id')
op.drop_table('universe_snapshots')
op.drop_table('character_states')
op.drop_table('actors')
op.drop_table('universes')
```

**Warning**: downgrade destroys all universe, actor, and character state data. Safe
only in dev/test environments. Never run in production after v2 sessions exist.

### 3.4 — Neo4j Startup Migration

Added to `src/tta/db/neo4j.py` → `_run_neo4j_migrations()`:

```cypher
-- Step: backfill universe_id on pre-v2 world-scoped nodes
MATCH (n)
WHERE n.session_id IS NOT NULL
  AND n.universe_id IS NULL
  AND (n:World OR n:Region OR n:Location OR n:NPC OR n:Item OR n:Event OR n:Quest)
SET n.universe_id = n.session_id
RETURN count(n) AS patched_nodes
```

> This placeholder links `universe_id = session_id` for pre-v2 nodes so that
> `universe_id`-scoped queries do not break. Proper back-fill (creating `universes`
> rows for pre-v2 sessions) is an optional admin script, not in the startup task.

---

## 4. Service & Type Contracts

### 4.1 — Module Layout

```
src/tta/
  universe/
    __init__.py
    models.py          # Universe, Actor, CharacterState, UniverseSnapshot SQLModel types
    service.py         # UniverseService, ActorService
    composition.py     # UniverseComposition, TimeConfig (S39, S34)
    exceptions.py      # UniverseNotFound, UniverseBusy, ActorNotFound, ...
  simulation/
    __init__.py
    world_time.py      # WorldTimeService (S34)
    npc_autonomy.py    # NPCAutonomyProcessor (S35)
    consequence.py     # ConsequencePropagator (S36)
    world_memory.py    # MemoryWriter, MemoryCompressor (S37)
    npc_memory.py      # SocialMemoryWriter, GossipPropagator (S38)
    types.py           # WorldDelta, ConsequenceRecord, MemoryRecord, GossipEvent
  api/
    transport.py       # NarrativeTransport Protocol + SSETransport (S32)
```

### 4.2 — `UniverseService` Contract

```python
class UniverseService:
    """Manages Universe lifecycle. PostgreSQL only (no Neo4j)."""

    async def create(
        self,
        owner_id: str,
        name: str,
        composition: UniverseComposition,
        pg: AsyncConnection,
    ) -> Universe: ...

    async def get(self, universe_id: str, pg: AsyncConnection) -> Universe: ...

    async def activate(
        self,
        universe_id: str,
        session_id: str,
        pg: AsyncConnection,
    ) -> Universe:
        """Atomically check status in (dormant, paused) and set status = active.
        Uses SELECT ... FOR UPDATE to prevent concurrent binding.
        Raises UniverseBusy if another session already holds it active."""
        ...

    async def pause(self, universe_id: str, pg: AsyncConnection) -> Universe: ...

    async def archive(self, universe_id: str, pg: AsyncConnection) -> Universe: ...

    async def list_for_player(
        self, player_id: str, pg: AsyncConnection
    ) -> list[Universe]: ...
```

### 4.3 — `ActorService` Contract

```python
class ActorService:
    """Manages Actor identity and CharacterState. PostgreSQL only."""

    async def get_or_create_for_player(
        self, player_id: str, display_name: str, pg: AsyncConnection
    ) -> Actor:
        """v2 constraint: returns existing actor if present. Creates only if
        the player has no actor yet. Never creates two actors for one player."""
        ...

    async def get_character_state(
        self, actor_id: str, universe_id: str, pg: AsyncConnection
    ) -> CharacterState | None: ...

    async def upsert_character_state(
        self, actor_id: str, universe_id: str, delta: dict, pg: AsyncConnection
    ) -> CharacterState: ...
```

### 4.4 — Core Simulation Types

```python
@dataclass
class WorldDelta:
    """Output of NPCAutonomyProcessor — one or more NPC state changes."""
    npc_changes: list[NPCStateChange]
    new_events:  list[WorldEvent]
    tick:        int


@dataclass
class ConsequenceRecord:
    """Output of ConsequencePropagator — one effect ripple at a given hop."""
    event_id:    str
    hop:         int                # 0 = origin, 1 = direct neighbor, ...
    target_type: str                # 'npc', 'location', 'faction'
    target_id:   str
    severity:    float              # 0.0–1.0, decays with each hop
    description: str                # distorted narrative fragment
    tick:        int


@dataclass
class MemoryRecord:
    """A single world-memory entry written by MemoryWriter."""
    id:          str                # ULID
    universe_id: str
    tick:        int
    importance:  float              # 0.0–1.0
    tier:        str                # 'working' | 'active' | 'compressed'
    content:     str
    source_type: str
    actor_id:    str | None
    location_id: str | None
    npc_ids:     list[str]


@dataclass
class GossipEvent:
    """An NPC-to-NPC reputation fragment propagated via the social graph."""
    id:          str                # ULID
    source_npc_id: str
    target_npc_id: str
    subject:     str                # 'player' | npc_id
    fragment:    str                # brief reputation statement
    tick:        int
    familiarity_threshold: float    # KNOWS.familiarity required to transmit
```

### 4.5 — `NarrativeTransport` Protocol (S32)

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class NarrativeTransport(Protocol):
    """Abstract contract for delivering narrative events to a connected client.
    All code above the transport boundary MUST use this protocol exclusively.
    No imports of tta.api.sse or direct SSEEvent construction are permitted
    above this boundary.
    """

    async def send_narrative(self, text: str) -> int:
        """Send a narrative string, chunked appropriately for the transport.
        Returns the number of chunks emitted."""
        ...

    async def send_end(self, game_state_summary: dict) -> None: ...

    async def send_error(self, code: str, message: str) -> None: ...

    async def send_heartbeat(self) -> None: ...

    async def send_state_update(self, state: dict) -> None: ...

    async def send_moderation(self, decision: dict) -> None: ...


class SSETransport:
    """SSE implementation of NarrativeTransport. Owns chunking logic."""

    def __init__(self, buffer: SseEventBuffer) -> None: ...

    async def send_narrative(self, text: str) -> int:
        """Split text into sentence-aligned chunks and append to buffer.
        Chunking logic moved here from games.py._split_narrative()."""
        ...
```

### 4.6 — Simulation Pipeline Hook in `TurnState`

The existing `TurnState` (defined normatively in `plans/llm-and-pipeline.md §2.3`)
gains new optional fields for v2:

```python
class TurnState:
    # ... existing v1 fields unchanged ...

    # v2 additions (all optional — None in v1 pipeline runs)
    universe_id:     str | None = None
    actor_id:        str | None = None
    world_delta:     WorldDelta | None = None              # populated by S35
    consequences:    list[ConsequenceRecord] | None = None # populated by S36
    new_memories:    list[MemoryRecord] | None = None      # populated by S37
```

---

## 5. Turn Pipeline Extensions

The v1 pipeline runs: `Understand → Enrich → Generate → Stream`.

The v2 pipeline adds a **Simulation Stage** that runs after `Generate` and before `Stream`:

```
Understand → Enrich → Generate → Simulate → Stream
```

### 5.1 — `SimulationStage`

```python
class SimulationStage:
    """Orchestrates all simulation sub-systems for one turn.
    Runs synchronously. All sub-systems receive and update TurnState.
    """

    def __init__(
        self,
        world_time: WorldTimeService,
        npc_autonomy: NPCAutonomyProcessor,
        consequence: ConsequencePropagator,
        memory: MemoryWriter,
        npc_memory: SocialMemoryWriter,
    ) -> None: ...

    async def process(self, state: TurnState, neo4j: AsyncDriver) -> TurnState:
        """Execution order (S34 must precede all others; S38 must follow S37):
        1. WorldTimeService.advance_tick()      → updates World node in Neo4j
        2. NPCAutonomyProcessor.process_turn()  → sets state.world_delta
        3. ConsequencePropagator.propagate()    → sets state.consequences
        4. MemoryWriter.write()                 → sets state.new_memories
        5. SocialMemoryWriter.propagate_gossip() → fires-and-returns (no state output)
        """
        ...
```

### 5.2 — Salience Filter (S35)

The NPC autonomy processor MUST NOT process every NPC every turn (performance).
The salience filter determines which NPCs are eligible for processing:

```python
SALIENCE_RULES = [
    # Tier     | Condition                          | Process?
    # KEY      | always                             | YES
    # SUPPORT  | last_processed_tick > N turns ago  | YES
    # BACKGND  | has a routine step for current     | YES (routine step only)
    #          | time_label AND random < 0.10       |
    # BACKGND  | otherwise                          | NO
]
```

Maximum NPCs processed per turn: `settings.npc_autonomy_max_per_turn` (default: 10).

### 5.3 — Consequence Propagation Depth (S36)

Propagation walks `(:Location)-[:CONNECTS_TO]-(:Location)` up to
`settings.consequence_max_depth` hops (default: 3). Social graph shortcuts
via `(:NPC)-[:KNOWS]-(:NPC)` are allowed when NPC `familiarity >= 0.6`.

Severity decay per hop: `new_severity = severity * settings.consequence_decay_factor`
(default: 0.5). Events with severity below `settings.consequence_min_severity`
(default: 0.05) are not written.

### 5.4 — Memory Budget and Compression (S37)

Working memory: last `settings.memory_working_size` MemoryRecords (default: 5).
Always included in generation context in full.

Active memory: all records with `tier == 'active'`.

Compression trigger: when total token count of all MemoryRecords exceeds
`settings.memory_compress_threshold` (default: 3000 tokens):
1. Score all `active` records by `importance * (1.0 - tick_age_factor)`.
2. Compress the lowest-scoring half into a single `compressed` record via
   `LLMRole.SUMMARIZATION` call.
3. Replace the compressed source records with the single summary record.

---

## 6. Universe Composition Schema (S39)

The `universes.config` JSONB column stores a `UniverseComposition` blob:

```python
@dataclass
class TimeConfig:
    """Time system config; stored in universes.config['time_config']."""
    ticks_per_hour:  int = 1          # How many turns = 1 in-world hour
    hours_per_day:   int = 24         # Hours in a day for this universe
    start_hour:      int = 8          # In-world hour at universe creation
    label_thresholds: dict[str, tuple[int,int]] = field(default_factory=lambda: {
        "midnight":  (0,  3),
        "dawn":      (4,  6),
        "morning":   (7,  11),
        "noon":      (12, 12),
        "afternoon": (13, 16),
        "dusk":      (17, 19),
        "evening":   (20, 22),
        "night":     (23, 23),
    })


@dataclass
class UniverseComposition:
    """Content vocabulary for a universe. Stored in universes.config."""
    composition_version: str = "1.0"
    themes:      list[str] = field(default_factory=list)  # e.g. ["redemption", "isolation"]
    tropes:      list[str] = field(default_factory=list)  # e.g. ["chosen_one", "found_family"]
    archetypes:  list[str] = field(default_factory=list)  # e.g. ["trickster", "mentor"]
    genre_twists: list[str] = field(default_factory=list) # e.g. ["cozy_horror", "hopeful_grimdark"]
    tone:        str = "balanced"                         # "dark" | "light" | "balanced"
    seed:        str | None = None                        # deterministic seeding value
    time_config: TimeConfig = field(default_factory=TimeConfig)
    # Reserved namespaces (populated by simulation sub-systems):
    # config['consequence_config']  → S36 propagation parameters
    # config['memory_config']       → S37 memory budget parameters
    # config['npc_social_config']   → S38 gossip parameters
```

---

## 7. Transport Abstraction (S32)

### 7.1 — Refactor Scope

**Existing code to refactor** in `src/tta/api/routes/games.py`:
- `_split_narrative()` function → moves to `SSETransport.send_narrative()`
- Direct `SseEventBuffer.append()` calls → replaced with `transport.send_*()`

**Import prohibition (enforced by ruff rule or CI check):**

```toml
# pyproject.toml — ruff noqa or custom bandit rule:
# No file outside tta/api/transport.py or tta/api/sse.py may import
# from tta.api.sse directly for the purpose of narrative delivery.
```

### 7.2 — SSETransport Injection

`SSETransport` is instantiated in the `stream_turn` route handler and passed into the
pipeline orchestrator. This is the only change needed to the route handler boundary:

```python
# games.py: stream_turn
async def stream_turn(...):
    buffer = SseEventBuffer()
    transport = SSETransport(buffer)
    await orchestrator.run(state, transport=transport)
    return EventSourceResponse(buffer.stream())
```

The pipeline orchestrator's `Stream` stage receives `transport: NarrativeTransport`
instead of the raw `buffer`. All internal stages use `transport.send_*()`.

---

## 8. API Changes

### 8.1 — New Endpoints (v2)

These endpoints are **new surface area** that v2 introduces. They integrate with
v1 S10 error handling (S23 contracts), S11 session management, and S25 rate limiting.

| Method | Path | Spec | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/universes` | S29 | Create a new universe |
| `GET`  | `/api/v1/universes` | S29 | List player's universes |
| `GET`  | `/api/v1/universes/{id}` | S29 | Get a universe |
| `DELETE` | `/api/v1/universes/{id}` | S29 | Archive a universe |
| `GET`  | `/api/v1/actors/me` | S31 | Get or create the player's actor |
| `GET`  | `/api/v1/actors/me/character-states` | S31 | List character states across universes |
| `POST` | `/api/v1/games` | S30 | Create a session (now requires `universe_id`) |

### 8.2 — Modified Endpoint: `POST /api/v1/games`

The session creation endpoint is extended:

```python
class CreateGameRequest(BaseModel):
    # v1 fields (backward compat):
    world_seed: WorldSeedParams | None = None     # deprecated in v2, ignored if universe_id given

    # v2 additions:
    universe_id: str | None = None                # if provided, bind to existing universe
    # If universe_id is None: auto-create a universe from world_seed (v1 compat path)
```

**v1 compat path**: if `universe_id` is None and `world_seed` is provided, the
session creation transparently auto-creates a universe, binds the session, and
proceeds. The client does not observe the new entity.

---

## 9. Settings Extensions

New settings added to `src/tta/config.py` (all with sane defaults):

```python
class Settings(BaseSettings):
    # ... existing v1 settings ...

    # v2 Universe
    universe_max_per_player: int = 5              # FR-29.06

    # v2 Simulation — NPC Autonomy (S35)
    npc_autonomy_enabled: bool = True
    npc_autonomy_max_per_turn: int = 10           # salience filter cap

    # v2 Simulation — Consequence Propagation (S36)
    consequence_propagation_enabled: bool = True
    consequence_max_depth: int = 3
    consequence_decay_factor: float = 0.5
    consequence_min_severity: float = 0.05

    # v2 Simulation — Memory (S37)
    memory_working_size: int = 5                  # last N records always in context
    memory_compress_threshold: int = 3000         # tokens before compression
    memory_importance_decay: float = 0.02         # per-tick importance decay

    # v2 Simulation — Social (S38)
    gossip_familiarity_threshold: float = 0.6     # KNOWS.familiarity to gossip
    gossip_max_hops: int = 2
```

---

## 10. Testing Strategy

### 10.1 — Unit Tests

| Module | Test file | Spec ACs |
|--------|-----------|----------|
| `universe/service.py` | `tests/unit/universe/test_universe_service.py` | AC-29.*, AC-30.* |
| `universe/service.py` (`ActorService`) | `tests/unit/universe/test_actor_service.py` | AC-31.* |
| `api/transport.py` | `tests/unit/api/test_transport.py` | AC-32.* |
| `simulation/world_time.py` | `tests/unit/simulation/test_world_time.py` | AC-34.* |
| `simulation/npc_autonomy.py` | `tests/unit/simulation/test_npc_autonomy.py` | AC-35.* |
| `simulation/consequence.py` | `tests/unit/simulation/test_consequence.py` | AC-36.* |
| `simulation/world_memory.py` | `tests/unit/simulation/test_world_memory.py` | AC-37.* |
| `simulation/npc_memory.py` | `tests/unit/simulation/test_npc_memory.py` | AC-38.* |
| `universe/composition.py` | `tests/unit/universe/test_composition.py` | AC-39.* |

All test functions in the above files MUST carry `@pytest.mark.spec("AC-NN.MM")`.

### 10.2 — Integration Tests

- `tests/integration/universe/test_universe_lifecycle.py` — full create → bind → pause cycle with real Postgres
- `tests/integration/simulation/test_simulation_stage.py` — full simulation stage with real Neo4j
- `tests/integration/api/test_games_v2.py` — POST /games with universe_id, binding atomicity check

### 10.3 — BDD Tests

Gherkin scenarios MUST be written for each user story before implementation begins:

```
tests/bdd/features/universe_creation.feature     → US-29.*, US-30.*
tests/bdd/features/actor_identity.feature        → US-31.*
tests/bdd/features/transport_abstraction.feature → US-32.*
tests/bdd/features/diegetic_time.feature         → US-34.*
```

### 10.4 — AC Compliance Tests

One `test_sNN_ac_compliance.py` file per spec, following the existing pattern in
`tests/unit/`. All test functions carry `@pytest.mark.spec("AC-NN.MM")`.

### 10.5 — Performance Considerations

- Simulation stage must complete in `< 200ms` per turn (shared budget with pipeline).
- NPC autonomy salience filter MUST cap total Neo4j reads at `npc_autonomy_max_per_turn * 3` per turn.
- Memory compression LLM call: counts against `settings.llm_per_session_budget`; logged to Langfuse as `LLMRole.SUMMARIZATION`.

---

## 11. Wave Implementation Order

The following waves are recommended. Each wave maps to one or more GitHub issues.

| Wave | Specs | Deliverables |
|------|-------|-------------|
| **v2-Wave-01** | S33 | Alembic migration (`v2_universe_entity`), SQLModel types, Neo4j startup migration |
| **v2-Wave-02** | S29, S30 | `UniverseService`, universe lifecycle endpoints, session binding, atomicity tests |
| **v2-Wave-03** | S31 | `ActorService`, `/actors/me` endpoint, `CharacterState` upsert |
| **v2-Wave-04** | S32 | `NarrativeTransport` protocol, `SSETransport` refactor, games.py cleanup |
| **v2-Wave-05** | S39 | `UniverseComposition`, `TimeConfig`, composition validation, universe config CRUD |
| **v2-Wave-06** | S34 | `WorldTimeService`, diegetic time advance, tick fields on World node, time-of-day labels |
| **v2-Wave-07** | S35 | `NPCAutonomyProcessor`, salience filter, routine evaluation, `WorldDelta` output |
| **v2-Wave-08** | S36 | `ConsequencePropagator`, graph-walk, distortion model, `ConsequenceRecord` output |
| **v2-Wave-09** | S37 | `MemoryWriter`, three-tier model, token budget tracking, compression |
| **v2-Wave-10** | S38 | `SocialMemoryWriter`, `GossipPropagator`, `NPCSocialEdge` graph edges |
| **v2-Wave-11** | — | `SimulationStage` wiring into pipeline; BDD tests for full simulation path |

> S40 (Genesis v2) is referenced by S39 and S34 but not yet drafted. It is not
> assigned to a wave until its spec is complete.

---

## 12. Cross-References

### Specs Covered

S29, S30, S31, S32, S33, S34, S35, S36, S37, S38, S39

### Normative Sections

The following sections of this plan are **locked**:

- **§0** — Resolved Conflicts and Normative Decisions
- **§1.2–§1.6** — PostgreSQL table schemas (column names and constraints)
- **§4.5** — `NarrativeTransport` Protocol method signatures
- **§4.6** — `TurnState` v2 additions
- **§5.1** — `SimulationStage` execution order

### Compatibility with v1 Plans

| v1 Plan | Sections Affected |
|---------|------------------|
| `system.md §3.2` | §1 (additive extension, no drops) |
| `llm-and-pipeline.md §2.3` | §4.6 (TurnState additions) |
| `api-and-sessions.md §5.1` | §8 (new endpoints, backward-compat create path) |
| `world-and-genesis.md §1` | §2 (Neo4j additions; session_id kept) |
