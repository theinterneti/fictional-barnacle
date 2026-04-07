# World Model + Genesis — Component Technical Plan

> **Phase**: SDD Phase 2 — Component Technical Plan
> **Scope**: World graph schema, world state management, Genesis-lite onboarding
> **Input specs**: S04 (World Model), S13 (World Graph Schema), S02 (Genesis Onboarding)
> **Parent plan**: `plans/system.md` (authoritative — all decisions here must be compatible)
> **Wave**: 3 (World + Genesis — see system.md §9)
> **Status**: 📝 Draft
> **Last Updated**: 2026-04-07

---

## 1. Neo4j Schema

### 1.1 — Design Principles

The schema extends system.md §3.3's minimal v1 schema with additional properties from
S13. Three rules govern the extension:

1. **`id` is the canonical identity property** on every node. system.md §3.3 uses `id`,
   not S13's `location_id` / `npc_id`. S13 field names are mapped at the service
   boundary (Pydantic models), never stored in Neo4j.
2. **Native `datetime()`** for all temporal fields. No ISO 8601 strings in the graph —
   Neo4j's native type supports indexing, comparison, and ordering natively. Stringify
   only at API serialization.
3. **Session isolation is hybrid**: every node carries a `session_id` property AND is
   structurally reachable from a `(:World)` root node. Queries use the property index
   for speed; write operations match through the World root for safety.

### 1.2 — Node Labels and Properties

#### World

The root node for a game session's world. One World per game session. The World node
is the structural anchor for session isolation — every other node is reachable from it.

| Property | Type | Required | Indexed | Notes |
|----------|------|----------|---------|-------|
| `id` | String (ULID) | Yes | Unique | Canonical identity |
| `session_id` | String (UUID) | Yes | Unique | FK to `game_sessions.id` in Postgres |
| `name` | String | Yes | — | World name (LLM-generated) |
| `description` | String | Yes | — | Short summary for UI |
| `template_key` | String | Yes | — | Which template was used (e.g., `quiet_village`) |
| `world_seed` | String (JSON) | Yes | — | Serialized WorldSeed parameters |
| `status` | String | Yes | — | `active`, `paused`, `completed`, `archived` |
| `created_at` | DateTime | Yes | — | |
| `updated_at` | DateTime | Yes | — | |

#### Region

| Property | Type | Required | Indexed | Notes |
|----------|------|----------|---------|-------|
| `id` | String (ULID) | Yes | Unique | |
| `session_id` | String (UUID) | Yes | Yes | Denormalized for query speed |
| `name` | String | Yes | Yes | |
| `description` | String | Yes | — | Narrative description |
| `atmosphere` | String | No | — | Mood/tone for narrative AI |
| `danger_level` | Integer (0–10) | Yes | — | |
| `template_key` | String | No | — | Stable identifier from template |
| `created_at` | DateTime | Yes | — | |
| `updated_at` | DateTime | Yes | — | |

#### Location

| Property | Type | Required | Indexed | Notes |
|----------|------|----------|---------|-------|
| `id` | String (ULID) | Yes | Unique | |
| `session_id` | String (UUID) | Yes | Yes | |
| `name` | String | Yes | Yes | |
| `description` | String | Yes | — | Base narrative description (≥20 chars) |
| `description_visited` | String | No | — | Shorter text for repeat visits |
| `type` | String | Yes | Yes | `interior`, `exterior`, `underground`, `water` |
| `is_accessible` | Boolean | Yes | — | Can the player currently enter? |
| `light_level` | String | Yes | — | `dark`, `dim`, `lit`, `bright` |
| `visited` | Boolean | Yes | — | Has the player been here? (from system.md §3.3) |
| `tags` | List[String] | No | — | Semantic tags for AI context |
| `template_key` | String | No | — | Stable identifier from template |
| `created_at` | DateTime | Yes | — | |
| `updated_at` | DateTime | Yes | — | |

#### NPC

| Property | Type | Required | Indexed | Notes |
|----------|------|----------|---------|-------|
| `id` | String (ULID) | Yes | Unique | |
| `session_id` | String (UUID) | Yes | Yes | |
| `name` | String | Yes | Yes | |
| `description` | String | Yes | — | Physical/personality description |
| `personality` | String | No | — | Traits for AI behavior |
| `role` | String | Yes | Yes | `merchant`, `quest_giver`, `companion`, `ambient` |
| `disposition` | String | Yes | — | `friendly`, `neutral`, `hostile`, `fearful` |
| `dialogue_style` | String | No | — | Speech pattern guidance |
| `alive` | Boolean | Yes | — | (system.md §3.3 uses `alive`) |
| `state` | String | Yes | — | `idle`, `active`, `busy`, `sleeping`, `traveling` |
| `tags` | List[String] | No | — | |
| `template_key` | String | No | — | |
| `created_at` | DateTime | Yes | — | |
| `updated_at` | DateTime | Yes | — | |

#### Item

| Property | Type | Required | Indexed | Notes |
|----------|------|----------|---------|-------|
| `id` | String (ULID) | Yes | Unique | |
| `session_id` | String (UUID) | Yes | Yes | |
| `name` | String | Yes | Yes | |
| `description` | String | Yes | — | |
| `type` | String | Yes | Yes | `weapon`, `tool`, `key`, `consumable`, `quest`, `ambient` |
| `portable` | Boolean | Yes | — | (system.md §3.3 uses `portable`) |
| `hidden` | Boolean | Yes | — | (system.md §3.3 uses `hidden`) |
| `is_usable` | Boolean | Yes | — | |
| `use_effect` | String | No | — | What happens when used |
| `tags` | List[String] | No | — | |
| `template_key` | String | No | — | |
| `created_at` | DateTime | Yes | — | |
| `updated_at` | DateTime | Yes | — | |

#### PlayerSession

A lightweight pointer in the graph. Detailed session data lives in Postgres.

| Property | Type | Required | Indexed | Notes |
|----------|------|----------|---------|-------|
| `session_id` | String (UUID) | Yes | Unique | Same as `game_sessions.id` in Postgres |
| `player_id` | String (UUID) | Yes | Yes | FK to `players.id` |
| `world_id` | String (ULID) | Yes | Yes | FK to World node |
| `created_at` | DateTime | Yes | — | |

> **Note:** system.md §3.3 uses `(:Player {session_id})`. We use the label
> `PlayerSession` in Neo4j to avoid confusion with the Postgres `players` table.
> The service layer maps between them.

#### Event (Neo4j — World Narrative Events)

**Important distinction:** Neo4j `Event` nodes represent **significant world
happenings** — things NPCs remember, that alter the narrative, that players can ask
about. They are NOT the same as Postgres `world_events` rows, which are a **mechanical
changelog** of state mutations. See §5.2 for the full separation.

| Property | Type | Required | Indexed | Notes |
|----------|------|----------|---------|-------|
| `id` | String (ULID) | Yes | Unique | |
| `session_id` | String (UUID) | Yes | Yes | |
| `type` | String | Yes | Yes | `narrative`, `combat`, `trade`, `discovery`, `quest` |
| `description` | String | Yes | — | What happened (narrative text) |
| `severity` | String | Yes | — | `minor`, `notable`, `major`, `critical` |
| `is_public` | Boolean | Yes | — | Visible to all, or only involved parties? |
| `triggered_at` | DateTime | Yes | Yes | When this event occurred in-world |
| `created_at` | DateTime | Yes | — | |

Events are **append-only**. Once created, they must not be modified or deleted.

#### Quest

| Property | Type | Required | Indexed | Notes |
|----------|------|----------|---------|-------|
| `id` | String (ULID) | Yes | Unique | |
| `session_id` | String (UUID) | Yes | Yes | |
| `name` | String | Yes | Yes | |
| `description` | String | Yes | — | |
| `status` | String | Yes | Yes | `available`, `active`, `completed`, `failed` |
| `difficulty` | String | No | — | `easy`, `medium`, `hard` |
| `created_at` | DateTime | Yes | — | |
| `updated_at` | DateTime | Yes | — | |

Valid status transitions: `available` → `active` → `completed` | `failed`. No backward
transitions.

### 1.3 — Relationship Types

| Relationship | From → To | Properties | Notes |
|-------------|-----------|------------|-------|
| `CONTAINS_REGION` | World → Region | — | Structural |
| `CONTAINS_LOCATION` | Region → Location | — | Structural |
| `CONNECTS_TO` | Location → Location | `direction`, `description`, `is_locked`, `lock_description`, `required_item_id`, `is_hidden`, `travel_time` | Directional. Two-way path = two relationships. `direction` uses controlled vocab: n/s/e/w/ne/nw/se/sw/up/down/in/out |
| `IS_AT` | NPC → Location | `arrived_at` (DateTime), `activity` (String) | system.md §3.3 name. One per NPC at a time. |
| `IS_AT` | Player → Location | `arrived_at` (DateTime), `visited_count` (Integer) | system.md §3.3 name. One per PlayerSession. |
| `IS_AT` | Item → Location | `placed_at` (DateTime), `is_hidden` (Boolean), `discovery_hint` (String) | For items in locations. |
| `CARRIED_BY` | Item → PlayerSession | `acquired_at` (DateTime) | system.md §3.3 name. Mutually exclusive with item `IS_AT`. |
| `OWNS` | NPC → Item | `acquired_at` (DateTime), `acquisition_method` (String) | NPC inventory. Mutually exclusive with item `IS_AT`. |
| `KNOWS_ABOUT` | NPC → Any | `knowledge_type`, `detail`, `is_secret` (Boolean), `learned_at` (DateTime) | system.md §3.3. Target can be Location, Item, NPC, Event, Quest. |
| `INVOLVED_IN` | Any → Event | `role` (String: `cause`, `witness`, `target`, `location`) | Links entities to events. |
| `GIVES_QUEST` | NPC → Quest | — | |
| `REQUIRES` | Quest → Item \| Event | — | Completion requirements |
| `REWARDS` | Quest → Item | — | |

**Relationship naming alignment with system.md §3.3:**

| system.md name | Used for | S13 equivalent |
|---------------|----------|---------------|
| `IS_AT` | NPC/Item/Player at Location | `PRESENT_IN`, `LOCATED_IN`, `CONTAINS` |
| `CARRIED_BY` | Item in player inventory | — |
| `KNOWS_ABOUT` | NPC knowledge | Same |
| `CONNECTS_TO` | Location ↔ Location | Same |

We use system.md names as canonical. S13 names appear only in this document for
cross-reference.

### 1.4 — Constraints and Indexes

```cypher
// === Uniqueness constraints (also serve as indexes) ===
CREATE CONSTRAINT world_id_unique IF NOT EXISTS
  FOR (w:World) REQUIRE w.id IS UNIQUE;
CREATE CONSTRAINT world_session_unique IF NOT EXISTS
  FOR (w:World) REQUIRE w.session_id IS UNIQUE;
CREATE CONSTRAINT region_id_unique IF NOT EXISTS
  FOR (r:Region) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT location_id_unique IF NOT EXISTS
  FOR (l:Location) REQUIRE l.id IS UNIQUE;
CREATE CONSTRAINT npc_id_unique IF NOT EXISTS
  FOR (n:NPC) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT item_id_unique IF NOT EXISTS
  FOR (i:Item) REQUIRE i.id IS UNIQUE;
CREATE CONSTRAINT event_id_unique IF NOT EXISTS
  FOR (e:Event) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT quest_id_unique IF NOT EXISTS
  FOR (q:Quest) REQUIRE q.id IS UNIQUE;
CREATE CONSTRAINT player_session_unique IF NOT EXISTS
  FOR (p:PlayerSession) REQUIRE p.session_id IS UNIQUE;

// === Session isolation indexes (every query filters on this) ===
CREATE INDEX region_session IF NOT EXISTS FOR (r:Region) ON (r.session_id);
CREATE INDEX location_session IF NOT EXISTS FOR (l:Location) ON (l.session_id);
CREATE INDEX npc_session IF NOT EXISTS FOR (n:NPC) ON (n.session_id);
CREATE INDEX item_session IF NOT EXISTS FOR (i:Item) ON (i.session_id);
CREATE INDEX event_session IF NOT EXISTS FOR (e:Event) ON (e.session_id);
CREATE INDEX quest_session IF NOT EXISTS FOR (q:Quest) ON (q.session_id);

// === Lookup indexes ===
CREATE INDEX location_name IF NOT EXISTS FOR (l:Location) ON (l.name);
CREATE INDEX location_type IF NOT EXISTS FOR (l:Location) ON (l.type);
CREATE INDEX npc_name IF NOT EXISTS FOR (n:NPC) ON (n.name);
CREATE INDEX npc_role IF NOT EXISTS FOR (n:NPC) ON (n.role);
CREATE INDEX item_name IF NOT EXISTS FOR (i:Item) ON (i.name);
CREATE INDEX item_type IF NOT EXISTS FOR (i:Item) ON (i.type);
CREATE INDEX event_type IF NOT EXISTS FOR (e:Event) ON (e.type);
CREATE INDEX event_triggered IF NOT EXISTS FOR (e:Event) ON (e.triggered_at);
CREATE INDEX quest_status IF NOT EXISTS FOR (q:Quest) ON (q.status);
CREATE INDEX player_session_world IF NOT EXISTS FOR (p:PlayerSession) ON (p.world_id);
```

### 1.5 — Schema Migration Strategy

Neo4j has no built-in migration framework. TTA uses numbered Cypher scripts with a
version-tracking node.

```
migrations/neo4j/
├── 001_initial_schema.cypher    # Constraints + indexes from §1.4
├── 002_add_quest_nodes.cypher   # Example future migration
└── ...
```

**Version tracking:**

```cypher
MERGE (v:SchemaVersion {id: 'current'})
SET v.version = 1, v.applied_at = datetime(), v.migration = '001_initial_schema'
```

**Migration rules:**
- Every migration is idempotent (`IF NOT EXISTS`, `MERGE`, conditional `SET`).
- Migrations run at application startup before accepting requests.
- A migration runner reads the `SchemaVersion` node, applies un-applied scripts in order.
- Destructive migrations (property removal, node deletion) are a separate category
  requiring explicit confirmation flag.

**Python migration runner** (in `src/tta/world/migrations.py`):

```python
async def run_migrations(driver: AsyncDriver) -> None:
    """Apply pending Neo4j schema migrations."""
    migrations = _load_migration_files()
    async with driver.session() as session:
        current = await _get_current_version(session)
        for migration in migrations:
            if migration.version > current:
                await session.execute_write(
                    lambda tx: tx.run(migration.cypher)
                )
                await _set_version(session, migration.version)
                log.info("applied_migration", version=migration.version)
```

### 1.6 — Session Isolation Model

**Approach: Hybrid — property + structural anchoring.**

Every node carries a `session_id` property, AND every node is structurally connected to
a `(:World)` root node via containment relationships. This dual approach provides:

1. **Fast indexed lookups**: `WHERE n.session_id = $sid` uses the per-label index.
2. **Structural safety**: write operations match through the World root, preventing
   accidental cross-session mutations.
3. **Bulk cleanup**: `MATCH (w:World {session_id: $sid}) ...` cascading delete.

**Read path** (uses property index for speed):

```cypher
MATCH (loc:Location {id: $loc_id, session_id: $sid})
...
```

**Write path** (anchored through World root for safety):

```cypher
MATCH (w:World {session_id: $sid})
      -[:CONTAINS_REGION]->(:Region)
      -[:CONTAINS_LOCATION]->(loc:Location {id: $loc_id})
SET loc.description = $new_desc, loc.updated_at = datetime()
```

**Cleanup** (game end or abandonment):

```cypher
// Delete all nodes for a session in dependency order
MATCH (w:World {session_id: $sid})
OPTIONAL MATCH (w)-[*]->(n)
DETACH DELETE n, w
```

For very large worlds (>1000 nodes), cleanup is batched:

```cypher
// Batch delete in chunks of 500
CALL {
  MATCH (w:World {session_id: $sid})-[*]->(n)
  WITH n LIMIT 500
  DETACH DELETE n
} IN TRANSACTIONS OF 500 ROWS
```

> **Why not separate Neo4j databases?** Neo4j CE 5.x supports only the default
> `neo4j` database and the `system` database. Multi-database requires Enterprise Edition.

---

## 2. Cypher Query Patterns

### 2.1 — `get_location_context(session_id, location_id, depth=1)`

The most-called query in the system. Assembles everything the narrative AI needs about
the player's current location.

**depth=1** (default — current location + immediate exits):

```cypher
MATCH (loc:Location {id: $location_id, session_id: $session_id})
OPTIONAL MATCH (loc)-[conn:CONNECTS_TO]->(adj:Location)
OPTIONAL MATCH (npc:NPC)-[at:IS_AT]->(loc) WHERE npc.alive = true
OPTIONAL MATCH (item:Item)-[iat:IS_AT]->(loc) WHERE item.hidden = false
RETURN loc,
       collect(DISTINCT {location: adj, direction: conn.direction,
                         locked: conn.is_locked}) AS exits,
       collect(DISTINCT {npc: npc, activity: at.activity}) AS npcs,
       collect(DISTINCT item) AS items
```

**depth=2** (nearby context — adds entities in adjacent locations):

```cypher
MATCH (loc:Location {id: $location_id, session_id: $session_id})

// Direct exits
OPTIONAL MATCH (loc)-[conn:CONNECTS_TO]->(adj:Location)

// NPCs at current location
OPTIONAL MATCH (npc:NPC)-[at:IS_AT]->(loc) WHERE npc.alive = true

// Items at current location (visible only)
OPTIONAL MATCH (item:Item)-[iat:IS_AT]->(loc) WHERE item.hidden = false

// Nearby NPCs (within 2 hops)
OPTIONAL MATCH (loc)-[:CONNECTS_TO*1..2]->(nearby:Location)
               <-[nat:IS_AT]-(nearby_npc:NPC)
WHERE nearby_npc.alive = true

RETURN loc,
       collect(DISTINCT {location: adj, direction: conn.direction,
                         locked: conn.is_locked}) AS exits,
       collect(DISTINCT {npc: npc, activity: at.activity}) AS npcs,
       collect(DISTINCT item) AS items,
       collect(DISTINCT {npc: nearby_npc, location: nearby.name}) AS nearby_npcs
```

**Performance notes:**
- The `session_id` + `id` lookup uses the uniqueness constraint index (O(1)).
- OPTIONAL MATCH ensures we return partial results (location with no NPCs is valid).
- Variable-length path `*1..2` is bounded; Neo4j handles this efficiently for small
  fan-out (typical location has 2-6 exits).
- Target: **< 50ms p95** for depth=1 on worlds with ≤1000 locations.

**Service-layer mapping:**

```python
async def get_location_context(
    self, session_id: str, location_id: str, depth: int = 1
) -> LocationContext:
    query = _LOCATION_CONTEXT_DEPTH_1 if depth <= 1 else _LOCATION_CONTEXT_DEPTH_2
    async with self._driver.session() as neo_session:
        result = await neo_session.execute_read(
            lambda tx: tx.run(query, session_id=session_id,
                              location_id=location_id)
        )
        record = await result.single()
        return _map_location_context(record)
```

### 2.2 — `get_recent_events(session_id, limit=5)`

**This queries Postgres, NOT Neo4j.** The `world_events` table (system.md §3.2) is the
source of truth for mechanical state changes.

```sql
SELECT id, event_type, entity_id, payload, created_at
FROM world_events
WHERE session_id = $1
ORDER BY created_at DESC
LIMIT $2;
```

**Service-layer implementation** (in `WorldService`, delegates to Postgres repo):

```python
async def get_recent_events(
    self, session_id: str, limit: int = 5
) -> list[WorldEvent]:
    return await self._event_repo.get_recent(session_id, limit)
```

This is NOT a Neo4j operation. The `WorldService` wraps both Neo4j and Postgres access
for the pipeline's convenience.

### 2.3 — `apply_world_changes(session_id, changes)`

Applies a list of `WorldChange` objects produced by the generation stage. Each change is
dispatched to a type-specific Cypher mutation. All mutations for a turn run in a single
Neo4j transaction with a correlated Postgres `world_events` insert.

**WorldChange type enum:**

```python
class WorldChangeType(str, Enum):
    PLAYER_MOVED = "player_moved"
    ITEM_TAKEN = "item_taken"
    ITEM_DROPPED = "item_dropped"
    NPC_MOVED = "npc_moved"
    NPC_DISPOSITION_CHANGED = "npc_disposition_changed"
    LOCATION_STATE_CHANGED = "location_state_changed"
    CONNECTION_LOCKED = "connection_locked"
    CONNECTION_UNLOCKED = "connection_unlocked"
    QUEST_STATUS_CHANGED = "quest_status_changed"
    ITEM_VISIBILITY_CHANGED = "item_visibility_changed"
    NPC_STATE_CHANGED = "npc_state_changed"
```

**Mutation patterns by type:**

#### Player Movement

Precondition: `CONNECTS_TO` exists, `is_locked = false`, target `is_accessible = true`.

```cypher
// Validate and move in one query
MATCH (from:Location {id: $from_id, session_id: $sid})
      -[conn:CONNECTS_TO {direction: $direction}]->
      (to:Location {session_id: $sid})
WHERE conn.is_locked = false AND to.is_accessible = true

// Delete old position
WITH from, to, conn
MATCH (p:PlayerSession {session_id: $sid})-[old:IS_AT]->(from)
DELETE old

// Create new position
WITH p, to
CREATE (p)-[:IS_AT {arrived_at: datetime(), visited_count: $visit_count}]->(to)
SET to.visited = true, to.updated_at = datetime()

RETURN to.id AS new_location_id
```

#### Item Pickup

Precondition: item at player's location, `portable = true`, `hidden = false`.

```cypher
MATCH (p:PlayerSession {session_id: $sid})-[:IS_AT]->(loc:Location)
MATCH (item:Item {id: $item_id, session_id: $sid})-[at:IS_AT]->(loc)
WHERE item.portable = true AND item.hidden = false
DELETE at
CREATE (item)-[:CARRIED_BY {acquired_at: datetime()}]->(p)
SET item.updated_at = datetime()
RETURN item.id AS picked_up
```

#### Item Drop

```cypher
MATCH (p:PlayerSession {session_id: $sid})-[:IS_AT]->(loc:Location)
MATCH (item:Item {id: $item_id})-[carry:CARRIED_BY]->(p)
DELETE carry
CREATE (item)-[:IS_AT {placed_at: datetime(), is_hidden: false}]->(loc)
SET item.updated_at = datetime()
```

#### NPC Movement

```cypher
MATCH (npc:NPC {id: $npc_id, session_id: $sid})-[old:IS_AT]->(:Location)
MATCH (dest:Location {id: $dest_id, session_id: $sid})
DELETE old
CREATE (npc)-[:IS_AT {arrived_at: datetime(), activity: $activity}]->(dest)
SET npc.state = $new_state, npc.updated_at = datetime()
```

#### Property Updates (NPC disposition, location state, etc.)

```cypher
MATCH (n {id: $entity_id, session_id: $sid})
SET n += $properties, n.updated_at = datetime()
```

**Orchestration — reliable dual-write:**

The `apply_world_changes()` method must write to both Neo4j (state mutation) and Postgres
(event log). These are two separate databases with no distributed transaction support.

**Strategy: Neo4j first, Postgres second, with retry and reconciliation.**

```python
async def apply_world_changes(
    self, session_id: str, changes: list[WorldChange]
) -> None:
    # 1. Apply all mutations in a single Neo4j transaction
    async with self._driver.session() as neo_session:
        await neo_session.execute_write(
            self._apply_neo4j_mutations, session_id, changes
        )

    # 2. Record events in Postgres (retried on failure)
    events = [change.to_world_event(session_id) for change in changes]
    try:
        await self._event_repo.bulk_insert(events)
    except Exception:
        # Log the failure and enqueue for retry.
        # The Neo4j state is correct; the event log will catch up.
        log.error("world_event_write_failed",
                  session_id=session_id, event_count=len(events))
        await self._event_retry_queue.enqueue(events)
```

If the Postgres write fails:
- Events are enqueued to an in-memory retry queue (backed by a simple asyncio task).
- A reconciliation query can detect drift: compare Neo4j `updated_at` timestamps with
  the latest `world_events` timestamp for a session.
- For v1, this is sufficient. If the retry also fails, the events are lost but the world
  state in Neo4j is still correct — narrative continuity degrades gracefully.

**Idempotency:** Each `WorldChange` carries the originating `turn_id`. The Postgres
`world_events` table has a composite unique index on `(session_id, turn_id, entity_id,
event_type)`. Re-applying the same change is a no-op at the Postgres layer. At the
Neo4j layer, mutations are naturally idempotent (SET is idempotent; relationship
delete + create produces the same end state).

### 2.4 — Additional Query Patterns

#### Full World State (Save/Resume)

For explicit save, query all nodes and relationships for a session:

```cypher
MATCH (w:World {session_id: $sid})
OPTIONAL MATCH (w)-[:CONTAINS_REGION]->(r:Region)
OPTIONAL MATCH (r)-[:CONTAINS_LOCATION]->(l:Location)
OPTIONAL MATCH (npc:NPC {session_id: $sid})-[npc_at:IS_AT]->(npc_loc:Location)
OPTIONAL MATCH (item:Item {session_id: $sid})
OPTIONAL MATCH (p:PlayerSession {session_id: $sid})-[p_at:IS_AT]->(p_loc:Location)
OPTIONAL MATCH (item)-[carry:CARRIED_BY]->(p)
RETURN w, collect(DISTINCT r) AS regions,
       collect(DISTINCT l) AS locations,
       collect(DISTINCT {npc: npc, location_id: npc_loc.id}) AS npcs,
       collect(DISTINCT {item: item, carried: carry IS NOT NULL}) AS items,
       p_loc.id AS player_location
```

Resume reconstructs from live Neo4j state — no separate snapshot store needed for v1.
The game resumes by calling `get_location_context()` for the player's current position.

If we later need checkpoint/rollback beyond "current state," we add a `game_snapshots`
table. That is post-v1.

#### NPC Knowledge Traversal

```cypher
MATCH (npc:NPC {id: $npc_id, session_id: $sid})-[k:KNOWS_ABOUT]->(target)
WHERE k.is_secret = false OR $player_trust > 5
RETURN target, k.detail, k.knowledge_type, labels(target) AS target_type
ORDER BY k.learned_at DESC
```

#### Movement Validation

```cypher
MATCH (from:Location {id: $from_id, session_id: $sid})
      -[conn:CONNECTS_TO {direction: $direction}]->
      (to:Location)
WHERE conn.is_locked = false AND to.is_accessible = true
RETURN to.id, to.name, conn.travel_time
```

Target: **< 10ms** (simple indexed lookup + single hop).

---

## 3. World Template Format

### 3.1 — Template JSON Schema

World templates are pre-authored JSON files that define the structural skeleton of a
world. Genesis-lite selects a template, then the LLM enriches it with names,
descriptions, and flavor text.

```python
class WorldTemplate(BaseModel):
    """Pydantic model for world template validation."""

    metadata: TemplateMetadata
    regions: list[TemplateRegion]
    locations: list[TemplateLocation]
    connections: list[TemplateConnection]
    npcs: list[TemplateNPC]
    items: list[TemplateItem]
    knowledge: list[TemplateKnowledge] = []

class TemplateMetadata(BaseModel):
    template_key: str                    # e.g., "quiet_village"
    display_name: str                    # e.g., "The Quiet Village"
    tags: list[str]                      # e.g., ["fantasy", "intimate", "medieval"]
    compatible_tones: list[str]          # ["dark", "hopeful", "whimsical"]
    compatible_tech_levels: list[str]    # ["primitive", "medieval"]
    compatible_magic: list[str]          # ["none", "rare", "common"]
    compatible_scales: list[str]         # ["intimate", "regional"]
    location_count: int                  # For quick filtering
    npc_count: int

class TemplateLocation(BaseModel):
    key: str                             # e.g., "loc_tavern"
    region_key: str                      # FK to TemplateRegion.key
    type: str                            # "interior", "exterior", etc.
    archetype: str                       # "tavern", "market", "forest_clearing"
    is_starting_location: bool = False   # Player begins here
    light_level: str = "lit"
    tags: list[str] = []

class TemplateConnection(BaseModel):
    from_key: str                        # FK to TemplateLocation.key
    to_key: str                          # FK to TemplateLocation.key
    direction: str                       # "north", "east", "in", etc.
    bidirectional: bool = True           # Create reverse connection too?
    is_locked: bool = False
    is_hidden: bool = False

class TemplateNPC(BaseModel):
    key: str                             # e.g., "npc_barkeep"
    location_key: str                    # FK to TemplateLocation.key
    role: str                            # "merchant", "quest_giver", etc.
    archetype: str                       # "gruff innkeeper", "mysterious stranger"
    disposition: str = "neutral"

class TemplateItem(BaseModel):
    key: str                             # e.g., "item_old_map"
    location_key: str | None = None      # In a location (mutually exclusive with npc_key)
    npc_key: str | None = None           # Owned by an NPC
    type: str                            # "key", "quest", "weapon", etc.
    archetype: str                       # "mysterious map", "rusty key"
    portable: bool = True
    hidden: bool = False

class TemplateKnowledge(BaseModel):
    npc_key: str                         # Who knows
    about_key: str                       # What they know about
    knowledge_type: str                  # "location", "item", "npc", "secret"
    is_secret: bool = False
```

### 3.2 — Example Template

```json
{
  "metadata": {
    "template_key": "quiet_village",
    "display_name": "The Quiet Village",
    "tags": ["fantasy", "intimate", "village", "mystery"],
    "compatible_tones": ["dark", "hopeful", "whimsical"],
    "compatible_tech_levels": ["primitive", "medieval"],
    "compatible_magic": ["none", "rare", "common"],
    "compatible_scales": ["intimate", "regional"],
    "location_count": 3,
    "npc_count": 2
  },
  "regions": [
    {"key": "reg_village", "archetype": "small settlement"}
  ],
  "locations": [
    {
      "key": "loc_square",
      "region_key": "reg_village",
      "type": "exterior",
      "archetype": "village center with a well or fountain",
      "is_starting_location": true,
      "tags": ["social", "safe"]
    },
    {
      "key": "loc_tavern",
      "region_key": "reg_village",
      "type": "interior",
      "archetype": "local tavern or inn",
      "tags": ["social", "safe", "shop"]
    },
    {
      "key": "loc_edge",
      "region_key": "reg_village",
      "type": "exterior",
      "archetype": "edge of settlement bordering wilderness",
      "light_level": "dim",
      "tags": ["transitional", "nature"]
    }
  ],
  "connections": [
    {"from_key": "loc_square", "to_key": "loc_tavern", "direction": "east", "bidirectional": true},
    {"from_key": "loc_square", "to_key": "loc_edge", "direction": "north", "bidirectional": true}
  ],
  "npcs": [
    {
      "key": "npc_keeper",
      "location_key": "loc_tavern",
      "role": "merchant",
      "archetype": "innkeeper who knows everyone's business",
      "disposition": "friendly"
    },
    {
      "key": "npc_stranger",
      "location_key": "loc_edge",
      "role": "quest_giver",
      "archetype": "mysterious figure who recently arrived",
      "disposition": "neutral"
    }
  ],
  "items": [
    {
      "key": "item_map",
      "location_key": null,
      "npc_key": "npc_stranger",
      "type": "quest",
      "archetype": "old map or document with a secret",
      "portable": true,
      "hidden": false
    },
    {
      "key": "item_key",
      "location_key": "loc_tavern",
      "type": "key",
      "archetype": "key or token that unlocks something",
      "portable": true,
      "hidden": true
    }
  ],
  "knowledge": [
    {
      "npc_key": "npc_keeper",
      "about_key": "npc_stranger",
      "knowledge_type": "npc",
      "is_secret": false
    },
    {
      "npc_key": "npc_stranger",
      "about_key": "item_map",
      "knowledge_type": "item",
      "is_secret": true
    }
  ]
}
```

### 3.3 — Template Library Organization

```
src/tta/world/templates/
├── __init__.py          # Template registry (load + tag-based lookup)
├── quiet_village.json
├── frontier_outpost.json
├── sunken_city.json
├── clockwork_tower.json
└── ...
```

Templates are loaded at startup and indexed by tags. The registry supports:

```python
class TemplateRegistry:
    def select(self, world_seed: WorldSeed) -> WorldTemplate:
        """Select best-matching template for a WorldSeed.

        Scores each template by counting matching tags across tone,
        tech_level, magic_presence, and scale. Returns highest score.
        Ties broken by random choice (adds replayability).
        """
```

### 3.4 — Template Validation Rules

Validation runs at startup (fail-fast) and before Genesis creates a world:

| Check | Error if violated |
|-------|-------------------|
| All `key` values unique within template | `DuplicateKeyError` |
| All `region_key` references exist in `regions` | `DanglingReferenceError` |
| All `location_key` references exist in `locations` | `DanglingReferenceError` |
| All `npc_key` / `about_key` references exist | `DanglingReferenceError` |
| Exactly one location has `is_starting_location: true` | `NoStartingLocationError` |
| All connections reference existing locations | `DanglingReferenceError` |
| No location has two exits in the same direction | `DirectionConflictError` |
| Each item has exactly one of `location_key` or `npc_key` set | `ItemPlacementError` |
| At least one location exists | `EmptyTemplateError` |
| Connected graph: all locations reachable from starting location | `DisconnectedGraphError` |

---

## 4. Genesis-Lite Workflow

### 4.1 — Scope

Genesis-lite is a **reduced v1 bootstrap path**, not the full 5-act Genesis experience
described in S02. S02's rich narrative onboarding (Acts I-V: Void → Shaping → Stranger
→ Ripple → Threshold) requires deeper LLM orchestration, state machines, and prompt
engineering. Genesis-lite gives us a working world-creation flow that can be expanded to
full S02 later.

**What Genesis-lite does:**
- 2-3 player prompts → WorldSeed parameters
- Template selection based on WorldSeed
- LLM enrichment of template → names, descriptions, flavor
- Neo4j graph creation from enriched template
- Player positioned at starting location, ready to play

**What Genesis-lite defers to full S02:**
- 5-act narrative structure
- Character emergence through narrative scenarios
- Mirror moment (character confirmation)
- Act-level persistence and mid-Genesis resume
- Prompt variation for returning players
- Content filtering during Genesis

### 4.2 — Prompt Sequence

**Prompt 1: World Tone** (maps to `tone`, `tech_level`, `magic_presence`)

System prompt:
> You are the world-builder for a text adventure game. Ask the player one evocative
> question to understand what kind of world they want. Do NOT ask about genre directly.
> Ask about a sensory detail, an emotion, or a moment. Keep it under 3 sentences.
> Then interpret their response to extract: tone (dark/hopeful/whimsical/austere),
> tech_level (primitive/medieval/industrial/futuristic), and
> magic_presence (none/rare/common/pervasive).
> Return JSON: {"narrative": "...", "tone": "...", "tech_level": "...", "magic_presence": "..."}

**Prompt 2: World Scale** (maps to `world_scale`, `player_position`, `power_source`)

System prompt:
> Given the player's previous response and the inferred world parameters, ask one
> question about the scope and nature of their world. Keep it under 3 sentences.
> Interpret to extract: world_scale (intimate/regional/continental/cosmic),
> player_position (outsider/local/authority/fugitive), and
> power_source (political/natural/magical/technological).
> Return JSON: {"narrative": "...", "world_scale": "...", "player_position": "...",
>               "power_source": "...", "defining_detail": "..."}

**Prompt 3: Character Hook** (optional — maps to character name + initial narrative hook)

System prompt:
> Given the world that's forming, ask the player who they are in this world. Keep it
> atmospheric and brief. Interpret to extract a character name (if offered) and a
> 1-sentence character concept.
> Return JSON: {"narrative": "...", "character_name": "...", "character_concept": "..."}

### 4.3 — Template Selection Logic

```python
async def select_template(
    world_seed: WorldSeed, registry: TemplateRegistry
) -> WorldTemplate:
    """Select best template for the player's WorldSeed.

    Scoring: each matching tag across tone, tech_level, magic_presence,
    and world_scale adds 1 point. Template with highest score wins.
    Ties broken randomly.
    """
    return registry.select(world_seed)
```

### 4.4 — LLM Enrichment

After template selection, the LLM generates names, descriptions, and flavor text for
every entity in the template. This is the "hybrid" from system.md §6.2.

**Enrichment prompt (uses `extraction` model role — structured output):**

```
You are enriching a world template for a text adventure game.

World parameters:
  Tone: {tone}
  Tech level: {tech_level}
  Magic: {magic_presence}
  Scale: {world_scale}
  Defining detail: {defining_detail}
  Character concept: {character_concept}

Template to enrich (each entity has an archetype — generate a name and description
that fits the world parameters):

{template_skeleton_json}

Return a JSON object with the same keys, but each entity now has:
- "name": a unique, evocative name fitting the world
- "description": 2-3 sentences of atmospheric narrative description
- "description_visited": 1 sentence for repeat visits (locations only)
- For NPCs, also: "personality", "dialogue_style"
- For knowledge entries: "detail" (what the NPC knows, 1-2 sentences)
```

**Validation of LLM output:**

```python
async def enrich_template(
    template: WorldTemplate,
    world_seed: WorldSeed,
    llm: LLMClient,
) -> EnrichedTemplate:
    prompt = _build_enrichment_prompt(template, world_seed)
    raw = await llm.generate(role=ModelRole.EXTRACTION, messages=[...])

    try:
        enrichment = EnrichedTemplate.model_validate_json(raw)
        _validate_enrichment_completeness(template, enrichment)
        return enrichment
    except ValidationError as e:
        # Retry once with error context
        retry_prompt = f"Previous output was invalid: {e}. Fix and return valid JSON."
        raw = await llm.generate(role=ModelRole.EXTRACTION,
                                 messages=[..., retry_prompt])
        try:
            return EnrichedTemplate.model_validate_json(raw)
        except ValidationError:
            # Fall back to template defaults
            log.warning("enrichment_fallback", template=template.metadata.template_key)
            return _default_enrichment(template)
```

### 4.5 — Graph Creation

Creates the Neo4j graph from the enriched template in a single transaction.

```python
async def create_world_graph(
    driver: AsyncDriver,
    session_id: str,
    template: WorldTemplate,
    enrichment: EnrichedTemplate,
    world_seed: WorldSeed,
    player_id: str,
) -> str:
    """Create the full world graph. Returns the World node ID."""
    world_id = generate_ulid()
    id_map: dict[str, str] = {}  # template_key → ULID

    async with driver.session() as neo_session:
        await neo_session.execute_write(
            _create_world_tx,
            session_id=session_id,
            world_id=world_id,
            template=template,
            enrichment=enrichment,
            world_seed=world_seed,
            player_id=player_id,
            id_map=id_map,
        )
    return world_id
```

**Transaction implementation** (order matches S13 §12.2):

1. Create World node
2. Create Region nodes + `CONTAINS_REGION` relationships
3. Create Location nodes + `CONTAINS_LOCATION` relationships
4. Create `CONNECTS_TO` relationships (bidirectional pairs if specified)
5. Create NPC nodes + `IS_AT` relationships
6. Create Item nodes + `IS_AT` or `OWNS` relationships
7. Create `KNOWS_ABOUT` relationships
8. Create PlayerSession node + `IS_AT` relationship to starting location

The `id_map` translates template keys (e.g., `loc_tavern`) to runtime ULIDs so
relationships reference the correct nodes.

### 4.6 — Error Handling

| Failure | Response |
|---------|----------|
| LLM enrichment returns invalid JSON | Retry once with error context. If still invalid, use template defaults (archetype as name, generic descriptions). |
| LLM enrichment timeout | Use template defaults. |
| Neo4j transaction fails | Return error to API layer. Game creation fails. Player can retry. |
| Template not found for WorldSeed | Fall back to a "universal" template (`default.json`) that works with any parameters. |
| Template validation fails at startup | Application refuses to start. Fix the template. |

### 4.7 — Genesis-Lite End State

After Genesis-lite completes, the following are true:

- Postgres: `game_sessions` row with `world_seed` JSONB and `status = 'active'`
- Neo4j: Full world graph — World, Regions, Locations, NPCs, Items, PlayerSession
- Neo4j: Player is `IS_AT` the starting location
- Redis: Active session state cached
- The next API call is `POST /games/{id}/turns` — normal gameplay begins

---

## 5. World State Management

### 5.1 — Mutation Lifecycle

World state changes during gameplay follow this path:

```
Player input
  → Pipeline Stage 1 (Input Understanding): parse intent
  → Pipeline Stage 2 (Context Assembly): get_location_context()
  → Pipeline Stage 3 (Generation): LLM produces narrative + WorldChange list
  → Pipeline Stage 3.5: apply_world_changes() — mutate Neo4j + log to Postgres
  → Pipeline Stage 4 (Delivery): stream narrative to player via SSE
```

The generation stage produces a `list[WorldChange]` alongside the narrative text. The
pipeline applies these changes before (or concurrently with) delivery.

### 5.2 — Event Model: Two Separate Concepts

| Concept | Storage | Purpose | Mutable? |
|---------|---------|---------|----------|
| **World Event** (Postgres `world_events`) | PostgreSQL | Mechanical changelog of state mutations. Used by `get_recent_events()` for narrative continuity. | Append-only |
| **Narrative Event** (Neo4j `Event` nodes) | Neo4j | Significant in-world happenings that NPCs remember, that alter the story. Linked to entities via `INVOLVED_IN`. | Append-only |

Not every Postgres `world_event` creates a Neo4j `Event` node. A minor property update
(NPC changed state from `idle` to `active`) is logged to Postgres but doesn't warrant a
narrative Event. Only changes marked `severity >= notable` by the generation stage create
Event nodes.

### 5.3 — WorldChange Type Reference

| Type | Neo4j Mutation | Postgres Event | Precondition |
|------|---------------|----------------|--------------|
| `player_moved` | Delete + create `IS_AT` | Yes | Valid `CONNECTS_TO`, not locked, target accessible |
| `item_taken` | Delete `IS_AT`, create `CARRIED_BY` | Yes | Item at player's location, portable, not hidden |
| `item_dropped` | Delete `CARRIED_BY`, create `IS_AT` | Yes | Item carried by player |
| `npc_moved` | Delete + create `IS_AT` | Yes | NPC exists and is alive |
| `npc_disposition_changed` | SET property | Yes | NPC exists and is alive |
| `npc_state_changed` | SET property | Conditional | NPC exists |
| `location_state_changed` | SET property | Yes | Location exists |
| `connection_locked` | SET `is_locked = true` | Yes | Connection exists |
| `connection_unlocked` | SET `is_locked = false` | Yes | Connection exists |
| `quest_status_changed` | SET `status` | Yes | Valid status transition |
| `item_visibility_changed` | SET `hidden` | Conditional | Item exists |

### 5.4 — State Consistency

**Invariant:** The Neo4j graph is the source of truth for current world state. Postgres
`world_events` is a log for narrative continuity.

If they disagree (Neo4j says NPC is at location B, but the last `world_event` says the
NPC moved to location A), Neo4j wins. The reconciliation path is: query Neo4j for current
state, compare with latest events, insert corrective events if needed.

### 5.5 — Save and Resume

**Save** (`POST /games/{id}/save`):
- Marks game session as `paused` in Postgres.
- No separate snapshot needed — world state lives in Neo4j.
- The `game_sessions.updated_at` timestamp marks the save point.

**Resume** (`POST /games/{id}/resume`):
- Marks game session as `active` in Postgres.
- Calls `get_location_context()` for the player's current location.
- Returns `GameState` to the client.
- No restoration step — the graph is already there.

**Why no snapshot?** For v1, Neo4j data is durable (volume-mounted). The graph persists
across restarts. A snapshot/restore mechanism is needed only for rollback (undo a bad
turn) or cold-storage archival — both are post-v1.

---

## 6. World Query Performance

### 6.1 — Performance Targets

| Query | Target | Measurement |
|-------|--------|-------------|
| Location context (depth=1) | < 50ms p95 | Integration test against real Neo4j |
| Location context (depth=2) | < 100ms p95 | system.md §5.1 target |
| Movement validation | < 10ms p95 | Single-hop indexed lookup |
| Full world state (save) | < 2s p95 | All nodes for a session |
| Graph creation (Genesis) | < 5s p95 | Full template load (3-10 locations) |

### 6.2 — Index Strategy

All queries filter by `session_id`. The per-label `session_id` indexes (§1.4) ensure
these filters are O(1) lookups, not full-label scans.

For `get_location_context()`, the critical path is:
1. `Location {id, session_id}` → uniqueness constraint (O(1))
2. `CONNECTS_TO` traversal from that location → relationship scan from single node
3. `NPC IS_AT → Location` → reversed relationship lookup

Neo4j's native graph storage makes step 2-3 constant-time relative to the node's
degree (number of connections), not the total graph size.

### 6.3 — Connection Pool Configuration

```python
# In src/tta/world/service.py
driver = AsyncGraphDatabase.driver(
    settings.neo4j_url,
    auth=(settings.neo4j_user, settings.neo4j_password),
    max_connection_pool_size=50,        # Default is 100; 50 sufficient for v1
    connection_acquisition_timeout=30,   # Seconds to wait for a connection
    max_transaction_retry_time=15,       # Auto-retry transient failures
)
```

### 6.4 — Query Profiling

During development, all Cypher queries are profiled with `EXPLAIN` and `PROFILE` to
verify index usage. The integration test suite includes performance assertions:

```python
@pytest.mark.integration
async def test_location_context_latency(neo4j_driver, seeded_world):
    """Location context query must complete in < 100ms."""
    start = time.monotonic()
    ctx = await world_service.get_location_context(
        session_id=seeded_world.session_id,
        location_id=seeded_world.starting_location_id,
        depth=1,
    )
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms < 100, f"Query took {elapsed_ms:.1f}ms"
    assert ctx.location is not None
```

---

## 7. Session Isolation

### 7.1 — Isolation Model

Multiple concurrent game sessions share one Neo4j instance. Isolation is enforced at
the application layer, not the database layer (Neo4j CE lacks role-based security).

**Three-layer isolation:**

1. **Property filter**: Every query includes `WHERE x.session_id = $sid` (indexed).
2. **Structural anchor**: Write operations match through `(:World {session_id: $sid})`
   to prevent accidentally mutating nodes in another session's subgraph.
3. **Test enforcement**: Integration tests verify that operations on session A cannot
   read or modify session B's nodes (see §8).

### 7.2 — Cleanup Strategy

**Game completion** (`status = 'completed'`):
- Neo4j nodes for the session are retained for 24 hours (player might want to review).
- After 24h, a background cleanup task deletes the subgraph.

**Game abandonment** (no activity for 90+ days):
- Detected by a scheduled task comparing `game_sessions.updated_at`.
- Postgres: session marked `archived`.
- Neo4j: subgraph deleted in batched transactions (§1.6 batch cleanup pattern).

**Cleanup implementation:**

```python
async def cleanup_session(driver: AsyncDriver, session_id: str) -> int:
    """Delete all nodes for a game session. Returns count of deleted nodes."""
    async with driver.session() as neo_session:
        result = await neo_session.execute_write(
            lambda tx: tx.run("""
                MATCH (w:World {session_id: $sid})
                OPTIONAL MATCH (w)-[*]->(n)
                WITH w, collect(n) AS nodes
                UNWIND nodes AS node
                DETACH DELETE node
                WITH w, size(nodes) AS count
                DETACH DELETE w
                RETURN count + 1 AS deleted
            """, sid=session_id)
        )
        record = await result.single()
        return record["deleted"] if record else 0
```

---

## 8. Testing Strategy

### 8.1 — Unit Tests (Mock Neo4j Driver)

Test query construction and parameter passing without a real database.

```python
# tests/unit/world/test_service.py

async def test_get_location_context_query_params():
    """Verify correct Cypher parameters are passed."""
    mock_driver = AsyncMock()
    mock_session = AsyncMock()
    mock_driver.session.return_value.__aenter__.return_value = mock_session

    service = WorldService(driver=mock_driver)
    await service.get_location_context(
        session_id="sess-123", location_id="loc-456", depth=1
    )

    # Verify the query was called with correct parameters
    call_args = mock_session.execute_read.call_args
    assert call_args is not None
    # Check parameter dict includes session_id and location_id
```

**What to unit test:**
- Query parameter construction for each WorldService method
- WorldChange dispatch logic (correct mutation selected for each type)
- Template validation (valid/invalid templates)
- Template selection scoring algorithm
- Enrichment prompt construction
- Enrichment validation and fallback logic
- ULID generation and ID mapping

### 8.2 — Integration Tests (Real Neo4j in Docker)

Full CRUD lifecycle against a real Neo4j instance.

```python
# tests/integration/test_neo4j.py

@pytest.fixture
async def neo4j_driver():
    """Provide a real Neo4j driver. Requires Docker Compose services."""
    driver = AsyncGraphDatabase.driver(
        "bolt://localhost:7687", auth=("neo4j", "password")
    )
    yield driver
    # Cleanup: delete all test data
    async with driver.session() as session:
        await session.run("MATCH (n) DETACH DELETE n")
    await driver.close()

@pytest.fixture
async def seeded_world(neo4j_driver):
    """Create a test world from the quiet_village template."""
    template = load_template("quiet_village")
    enrichment = _default_enrichment(template)
    world_id = await create_world_graph(
        neo4j_driver, session_id="test-session", template=template,
        enrichment=enrichment, world_seed=_test_seed(), player_id="test-player"
    )
    return SeededWorld(session_id="test-session", world_id=world_id, ...)
```

**Integration test matrix:**

| Test | Verifies |
|------|----------|
| `test_create_world_graph` | All nodes and relationships created correctly |
| `test_get_location_context_depth_1` | Returns location + exits + NPCs + items |
| `test_get_location_context_depth_2` | Returns nearby context |
| `test_player_movement` | IS_AT relationship updated atomically |
| `test_item_pickup` | IS_AT deleted, CARRIED_BY created |
| `test_item_drop` | CARRIED_BY deleted, IS_AT created |
| `test_npc_movement` | NPC IS_AT relationship updated |
| `test_property_update` | updated_at timestamp changes |
| `test_session_isolation_read` | Session A cannot read session B's nodes |
| `test_session_isolation_write` | Session A cannot modify session B's nodes |
| `test_cleanup` | All nodes deleted for a session |
| `test_movement_validation_locked` | Locked connection rejects movement |
| `test_item_pickup_not_portable` | Non-portable item rejects pickup |
| `test_location_context_latency` | < 100ms on seeded world |

### 8.3 — Template Validation Tests

```python
# tests/unit/world/test_templates.py

def test_valid_template_loads():
    template = WorldTemplate.model_validate_json(VALID_TEMPLATE_JSON)
    validate_template(template)  # No exception

def test_dangling_location_reference():
    template = _template_with(npcs=[{"key": "npc1", "location_key": "nonexistent"}])
    with pytest.raises(DanglingReferenceError):
        validate_template(template)

def test_no_starting_location():
    template = _template_with(locations=[{"key": "loc1", "is_starting_location": False}])
    with pytest.raises(NoStartingLocationError):
        validate_template(template)

def test_disconnected_graph():
    template = _template_with(
        locations=[
            {"key": "loc1", "is_starting_location": True},
            {"key": "loc2"},  # No connection to loc1
        ],
        connections=[],
    )
    with pytest.raises(DisconnectedGraphError):
        validate_template(template)

def test_all_shipped_templates_valid():
    """Every template in the templates directory passes validation."""
    for template_path in Path("src/tta/world/templates").glob("*.json"):
        template = WorldTemplate.model_validate_json(template_path.read_text())
        validate_template(template)
```

### 8.4 — Genesis Flow Tests (Mock LLM)

```python
# tests/unit/genesis/test_genesis_lite.py

async def test_genesis_lite_creates_world(mock_llm):
    """Full Genesis-lite flow with mocked LLM."""
    mock_llm.generate.side_effect = [
        '{"narrative": "...", "tone": "dark", ...}',      # Prompt 1
        '{"narrative": "...", "world_scale": "intimate", ...}',  # Prompt 2
        '{"narrative": "...", "character_name": "Kael"}',  # Prompt 3
        VALID_ENRICHMENT_JSON,                              # Enrichment
    ]

    result = await run_genesis_lite(
        player_id="test-player",
        session_id="test-session",
        llm=mock_llm,
        driver=mock_neo4j_driver,
        registry=template_registry,
    )

    assert result.world_seed.tone == "dark"
    assert result.world_id is not None
    assert result.starting_location_id is not None
```

### 8.5 — World Mutation Tests

```python
# tests/integration/test_world_mutations.py

async def test_player_move_updates_graph(world_service, seeded_world):
    """Player movement creates correct graph state."""
    # Get starting location
    ctx = await world_service.get_location_context(
        seeded_world.session_id, seeded_world.starting_location_id
    )
    target_exit = ctx.exits[0]

    # Move player
    await world_service.apply_world_changes(
        seeded_world.session_id,
        [WorldChange(type=WorldChangeType.PLAYER_MOVED,
                     payload={"direction": target_exit.direction})]
    )

    # Verify new location
    new_ctx = await world_service.get_location_context(
        seeded_world.session_id, target_exit.location_id
    )
    assert new_ctx.location.id == target_exit.location_id

async def test_item_pickup_and_verify_events(world_service, seeded_world, event_repo):
    """Item pickup updates Neo4j and creates Postgres event."""
    # ... pickup item ...

    # Verify Neo4j state
    # ... item no longer IS_AT location ...

    # Verify Postgres event
    events = await event_repo.get_recent(seeded_world.session_id, limit=1)
    assert events[0].event_type == "item_taken"
```

### 8.6 — BDD Tests (Gherkin)

For user-visible behavior tied to S04/S02 acceptance criteria:

```gherkin
Feature: World State Management

  Scenario: Player explores and world tracks visits
    Given a new game with the "quiet_village" template
    And the player is at the starting location
    When the player moves east
    Then the player is at the tavern
    And the starting location shows "visited: true"

  Scenario: Item pickup removes item from location
    Given the player is at a location with a visible, portable item
    When the player picks up the item
    Then the item is in the player's inventory
    And the item is no longer at the location
```

---

## Appendix A: Mapping to system.md

| system.md Reference | This Plan Section |
|---------------------|-------------------|
| §3.3 (Minimal Neo4j schema) | §1 (Extended with full properties) |
| §3.2 (`world_events` Postgres table) | §2.2, §5.2 (Event model separation) |
| §4.5 (`WorldService` protocol) | §2.1–2.3 (Cypher implementations) |
| §5.1 (Neo4j < 100ms p95) | §6 (Performance targets + profiling) |
| §6.2 (Hybrid template + LLM) | §3 (Template format), §4 (Genesis-lite) |
| §9 Wave 3 (World + Genesis) | Entire document |
| §10 (Open items: Cypher patterns, template schema, Genesis prompts) | §2, §3, §4 |

## Appendix B: Naming Reconciliation

| S13 Name | system.md §3.3 Name | Used in Neo4j | Used in Python |
|----------|---------------------|---------------|----------------|
| `location_id` | `id` | `id` | `LocationContext.location_id` (mapped) |
| `npc_id` | `id` | `id` | `NPC.npc_id` (mapped) |
| `PRESENT_IN` | `IS_AT` | `IS_AT` | — |
| `LOCATED_IN` | `IS_AT` | `IS_AT` | — |
| `CONTAINS` (Location→Item) | `IS_AT` | `IS_AT` | — |
| `PlayerSession` | `Player` | `PlayerSession` | `PlayerSession` |

system.md is authoritative. S13 names are used in this document only for cross-reference.
