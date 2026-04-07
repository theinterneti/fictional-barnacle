# S13 — World Graph Schema

> **Status**: 📝 Draft
> **Level**: 3 — Platform
> **Dependencies**: S04 (World Model)
> **Last Updated**: 2025-07-24

---

## 1. Purpose

This spec defines the Neo4j graph database schema that represents the game world. It is
the physical realization of the domain model described in S04 (World Model) — translating
abstract concepts like "a location connects to another location" into concrete node
labels, relationship types, and property schemas.

**Co-design with S04:** Every node type and relationship type in this schema maps to a
concept in the World Model. This spec adds the storage-level details that S04 deliberately
omits: data types, indexes, constraints, query patterns, and mutation rules.

---

## 2. Design Philosophy

### 2.1 Principles

- **The graph is the world**: the game world IS a graph. Locations connect to locations.
  NPCs inhabit locations. Items exist in locations or inventories. This is not a relational
  model force-fit into a graph — it is natively graph-shaped data.
- **Query-driven schema**: node and relationship types are designed around the queries the
  game needs to run, not around an abstract data model.
- **Typed and constrained**: every node label has a defined set of properties with types.
  Every relationship type has a defined direction and allowed endpoints.
- **Temporal by convention**: all mutable nodes carry `created_at` and `updated_at`
  timestamps. State changes can be traced.
- **Seed-friendly**: the schema supports bulk loading of initial world data from the
  Genesis system (see S04) as well as incremental mutations during gameplay.

### 2.2 Graph vs. Relational: Why Neo4j for World Data?

The game world is defined by **connections**. The core gameplay questions are:

- "What locations can the player reach from here?"
- "Who is in this room?"
- "What does this NPC know about that item?"
- "What path connects the player's location to the quest objective?"

These are graph traversal questions. In a relational database, they require recursive
CTEs or multiple JOINs. In a graph database, they are native single-query operations
that execute in constant time relative to the traversal depth (not the total graph size).

---

## 3. User Stories

> **US-13.1** — As the game engine, I can quickly determine what locations are reachable
> from the player's current position so I can present valid movement options.

> **US-13.2** — As the narrative generator, I can retrieve the full context of a location
> (description, NPCs present, items available, connected locations) in a single query so
> I can generate rich, accurate narrative.

> **US-13.3** — As the world builder agent, I can update world state (move an NPC, change
> a location's description, add a new item) as the result of player actions.

> **US-13.4** — As the Genesis system, I can seed an entire world graph from a definition
> file in a single bulk operation.

> **US-13.5** — As a developer, I can query the world graph to understand its structure
> and verify correctness during development.

> **US-13.6** — As the game engine, I can track what has changed in the world since a
> given point in time so I can send targeted state updates to connected players.

> **US-13.7** — As the AI pipeline, I can traverse NPC knowledge graphs to determine
> what an NPC knows and doesn't know, enabling realistic dialogue.

---

## 4. Co-Design Mapping: S04 → S13

This table maps every S04 World Model concept to its graph schema representation.

| S04 Concept | Graph Element | S13 Section |
|-------------|---------------|-------------|
| World | `:World` node | §5.1 |
| Region | `:Region` node | §5.2 |
| Location | `:Location` node | §5.3 |
| Connection | `:CONNECTS_TO` relationship | §6.1 |
| NPC | `:NPC` node | §5.4 |
| Item | `:Item` node | §5.5 |
| Event | `:Event` node | §5.6 |
| Quest | `:Quest` node | §5.7 |
| Player Position | `:LOCATED_IN` relationship | §6.4 |
| NPC Presence | `:PRESENT_IN` relationship | §6.4 |
| Item Location | `:CONTAINS` relationship | §6.3 |
| NPC Knowledge | `:KNOWS_ABOUT` relationship | §6.5 |
| Quest Progress | `:Quest` node state | §5.7 |
| World State | Node/relationship properties | §8 |

- FR-13.01: Every concept in S04 MUST have a corresponding representation in the graph
  schema.
- FR-13.02: The naming conventions in S13 MUST align with S04 domain language. If S04
  calls it a "Location," the node label is `:Location`, not `:Room` or `:Place`.

---

## 5. Node Types

### 5.1 World

The root node for a game world. Every other node in a world is reachable from this node.

| Property | Type | Required | Indexed | Description |
|----------|------|----------|---------|-------------|
| `world_id` | String (ULID) | Yes | Unique | Globally unique identifier |
| `name` | String | Yes | Yes | Human-readable world name |
| `description` | String | Yes | No | World summary for UI/narrative |
| `version` | String | Yes | No | Schema/content version of this world |
| `status` | String | Yes | No | "draft", "active", "archived" |
| `created_at` | DateTime | Yes | No | When this world was created |
| `updated_at` | DateTime | Yes | No | Last modification time |

**Constraints:**
- FR-13.03: `world_id` MUST be globally unique (uniqueness constraint).
- FR-13.04: A world MUST contain at least one Region and one Location to be "active".

### 5.2 Region

A thematic grouping of locations. Regions add organizational structure and can carry
shared properties (e.g., weather, danger level).

| Property | Type | Required | Indexed | Description |
|----------|------|----------|---------|-------------|
| `region_id` | String (ULID) | Yes | Unique | Globally unique identifier |
| `name` | String | Yes | Yes | Region name (e.g., "The Dark Forest") |
| `description` | String | Yes | No | Narrative description |
| `atmosphere` | String | No | No | Mood/tone descriptor for narrative generation |
| `danger_level` | Integer (0–10) | Yes | No | Relative danger for this area |
| `created_at` | DateTime | Yes | No | |
| `updated_at` | DateTime | Yes | No | |

**Relationships:**
- `(:World)-[:CONTAINS_REGION]->(:Region)` — a world contains regions
- `(:Region)-[:CONTAINS_LOCATION]->(:Location)` — a region contains locations

### 5.3 Location

The fundamental unit of space in the game world. Players exist in locations. Actions
happen in locations.

| Property | Type | Required | Indexed | Description |
|----------|------|----------|---------|-------------|
| `location_id` | String (ULID) | Yes | Unique | Globally unique identifier |
| `name` | String | Yes | Yes | Location name (e.g., "Town Square") |
| `description` | String | Yes | No | Base narrative description |
| `description_visited` | String | No | No | Shorter description for repeat visits |
| `type` | String | Yes | Yes | "interior", "exterior", "underground", "water" |
| `is_accessible` | Boolean | Yes | No | Can the player currently enter? |
| `light_level` | String | Yes | No | "dark", "dim", "lit", "bright" |
| `tags` | List[String] | No | No | Semantic tags for AI context (e.g., ["safe", "shop"]) |
| `created_at` | DateTime | Yes | No | |
| `updated_at` | DateTime | Yes | No | |

**Constraints:**
- FR-13.05: `location_id` MUST be globally unique.
- FR-13.06: Every location MUST belong to exactly one region (via `CONTAINS_LOCATION`).
- FR-13.07: A location's `description` MUST be at least 20 characters (meaningful
  narrative).

### 5.4 NPC (Non-Player Character)

Characters the player interacts with. NPCs have personalities, knowledge, and state.

| Property | Type | Required | Indexed | Description |
|----------|------|----------|---------|-------------|
| `npc_id` | String (ULID) | Yes | Unique | Globally unique identifier |
| `name` | String | Yes | Yes | NPC's name |
| `description` | String | Yes | No | Physical/personality description |
| `personality` | String | No | No | Personality traits for AI behavior |
| `role` | String | Yes | Yes | "merchant", "quest_giver", "companion", "ambient" |
| `disposition` | String | Yes | No | "friendly", "neutral", "hostile", "fearful" |
| `dialogue_style` | String | No | No | Speech pattern guidance for narrative AI |
| `is_alive` | Boolean | Yes | No | Can this NPC interact? |
| `state` | String | Yes | No | "idle", "active", "busy", "sleeping", "traveling" |
| `tags` | List[String] | No | No | Semantic tags for AI context |
| `created_at` | DateTime | Yes | No | |
| `updated_at` | DateTime | Yes | No | |

**Constraints:**
- FR-13.08: `npc_id` MUST be globally unique.
- FR-13.09: Every NPC MUST be located in exactly one location at any given time (via
  `PRESENT_IN`).

### 5.5 Item

Objects that exist in the world. Items can be in locations, owned by NPCs, or in a
player's inventory.

| Property | Type | Required | Indexed | Description |
|----------|------|----------|---------|-------------|
| `item_id` | String (ULID) | Yes | Unique | Globally unique identifier |
| `name` | String | Yes | Yes | Item name |
| `description` | String | Yes | No | Narrative description |
| `type` | String | Yes | Yes | "weapon", "tool", "key", "consumable", "quest", "ambient" |
| `is_portable` | Boolean | Yes | No | Can the player pick this up? |
| `is_visible` | Boolean | Yes | No | Is this item currently visible/discoverable? |
| `is_usable` | Boolean | Yes | No | Can this item be used? |
| `use_effect` | String | No | No | Description of what happens when used |
| `weight` | Float | No | No | Weight for inventory management (if applicable) |
| `tags` | List[String] | No | No | Semantic tags |
| `created_at` | DateTime | Yes | No | |
| `updated_at` | DateTime | Yes | No | |

**Constraints:**
- FR-13.10: `item_id` MUST be globally unique.
- FR-13.11: An item MUST be in exactly one location (via `CONTAINS`) OR owned by exactly
  one entity (NPC or player, via `OWNS`) at any given time — never both, never neither.

### 5.6 Event

Significant things that have happened in the world. Events create a temporal log of
world history and can trigger narrative callbacks.

| Property | Type | Required | Indexed | Description |
|----------|------|----------|---------|-------------|
| `event_id` | String (ULID) | Yes | Unique | Globally unique identifier |
| `type` | String | Yes | Yes | "narrative", "combat", "trade", "discovery", "quest" |
| `description` | String | Yes | No | What happened |
| `severity` | String | Yes | No | "minor", "notable", "major", "critical" |
| `is_public` | Boolean | Yes | No | Visible to all, or only to involved parties? |
| `triggered_at` | DateTime | Yes | Yes | When this event occurred |
| `created_at` | DateTime | Yes | No | |

**Constraints:**
- FR-13.12: Events are append-only. Once created, an event MUST NOT be modified or
  deleted.
- FR-13.13: Every event MUST be linked to at least one other node (location, NPC, item)
  via an `INVOLVED_IN` relationship.

### 5.7 Quest

A structured objective with progress tracking.

| Property | Type | Required | Indexed | Description |
|----------|------|----------|---------|-------------|
| `quest_id` | String (ULID) | Yes | Unique | Globally unique identifier |
| `name` | String | Yes | Yes | Quest title |
| `description` | String | Yes | No | Quest description/objective |
| `status` | String | Yes | Yes | "available", "active", "completed", "failed" |
| `difficulty` | String | No | No | "easy", "medium", "hard" |
| `xp_reward` | Integer | No | No | Experience points on completion |
| `created_at` | DateTime | Yes | No | |
| `updated_at` | DateTime | Yes | No | |

**Constraints:**
- FR-13.14: Valid quest status transitions: `available` → `active` → `completed`|`failed`.
- FR-13.15: A completed or failed quest MUST NOT transition back to active.

---

## 6. Relationship Types

### 6.1 CONNECTS_TO (Location → Location)

Represents a traversable path between two locations.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `direction` | String | Yes | "north", "south", "east", "west", "up", "down", "in", "out" |
| `description` | String | No | Narrative description of the passage |
| `is_locked` | Boolean | Yes | Is this path currently blocked? |
| `lock_description` | String | No | Why it's locked, hints for unlocking |
| `required_item_id` | String | No | Item needed to unlock (FK to Item) |
| `is_hidden` | Boolean | Yes | Must be discovered before it's usable? |
| `travel_time` | Integer | No | Narrative time units to traverse |

- FR-13.16: `CONNECTS_TO` MUST be directional. A two-way path requires two relationships.
- FR-13.17: The `direction` property MUST use a controlled vocabulary: "north", "south",
  "east", "west", "up", "down", "in", "out", "northeast", "northwest", "southeast",
  "southwest".
- FR-13.18: A location MUST NOT have two `CONNECTS_TO` relationships with the same
  `direction`.

### 6.2 CONTAINS_REGION / CONTAINS_LOCATION

Structural containment relationships.

- `(:World)-[:CONTAINS_REGION]->(:Region)` — no properties
- `(:Region)-[:CONTAINS_LOCATION]->(:Location)` — no properties

- FR-13.19: Every Region MUST be contained in exactly one World.
- FR-13.20: Every Location MUST be contained in exactly one Region.

### 6.3 CONTAINS (Location → Item)

An item exists at a location.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `placed_at` | DateTime | Yes | When the item was placed here |
| `is_hidden` | Boolean | Yes | Must be discovered? |
| `discovery_hint` | String | No | Narrative clue for finding the item |

### 6.4 PRESENT_IN (NPC → Location) / LOCATED_IN (Player → Location)

Presence relationships for entities in locations.

**PRESENT_IN (NPC → Location):**
| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `arrived_at` | DateTime | Yes | When the NPC arrived |
| `activity` | String | No | What the NPC is doing ("guarding", "sleeping", "trading") |

**LOCATED_IN (Player → Location):**
| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `arrived_at` | DateTime | Yes | When the player arrived |
| `visited_count` | Integer | Yes | How many times the player has been here |

- FR-13.21: A player game session (represented by a `player_session_id`) MUST have
  exactly one `LOCATED_IN` relationship at any time.
- FR-13.22: An NPC MUST have exactly one `PRESENT_IN` relationship at any time.
- FR-13.23: When an NPC or player moves, the old relationship MUST be deleted and a new
  one created (not updated — to preserve the timestamp).

### 6.5 KNOWS_ABOUT (NPC → Any)

What an NPC knows about other entities. Used by the AI to generate contextually
accurate dialogue.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `knowledge_type` | String | Yes | "location", "item", "npc", "event", "secret" |
| `detail` | String | Yes | What the NPC knows (narrative text) |
| `is_secret` | Boolean | Yes | Would the NPC share this freely? |
| `learned_at` | DateTime | Yes | When the NPC acquired this knowledge |

- FR-13.24: `KNOWS_ABOUT` can point to any node type (Location, Item, NPC, Event, Quest).
- FR-13.25: The target of `KNOWS_ABOUT` MUST exist in the graph. Dangling references
  are not permitted.

### 6.6 OWNS (NPC → Item / PlayerSession → Item)

Possession of an item.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `acquired_at` | DateTime | Yes | When the item was acquired |
| `acquisition_method` | String | No | "found", "bought", "given", "crafted", "stolen" |

- FR-13.26: An item MUST have at most one `OWNS` relationship OR one `CONTAINS`
  relationship, not both.

### 6.7 INVOLVED_IN (Any → Event)

Links entities to events they participated in.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `role` | String | Yes | "cause", "witness", "target", "location" |

### 6.8 GIVES_QUEST / REQUIRES (Quest relationships)

- `(:NPC)-[:GIVES_QUEST]->(:Quest)` — NPC offers this quest
- `(:Quest)-[:REQUIRES]->(:Item|:Event)` — what's needed to complete the quest
- `(:Quest)-[:REWARDS]->(:Item)` — what the player receives on completion

---

## 7. Index Strategy

### 7.1 Uniqueness Constraints

These serve as both unique constraints and indexes.

```cypher
CREATE CONSTRAINT world_id_unique FOR (w:World) REQUIRE w.world_id IS UNIQUE;
CREATE CONSTRAINT region_id_unique FOR (r:Region) REQUIRE r.region_id IS UNIQUE;
CREATE CONSTRAINT location_id_unique FOR (l:Location) REQUIRE l.location_id IS UNIQUE;
CREATE CONSTRAINT npc_id_unique FOR (n:NPC) REQUIRE n.npc_id IS UNIQUE;
CREATE CONSTRAINT item_id_unique FOR (i:Item) REQUIRE i.item_id IS UNIQUE;
CREATE CONSTRAINT event_id_unique FOR (e:Event) REQUIRE e.event_id IS UNIQUE;
CREATE CONSTRAINT quest_id_unique FOR (q:Quest) REQUIRE q.quest_id IS UNIQUE;
```

### 7.2 Lookup Indexes

For properties frequently used in WHERE clauses.

```cypher
CREATE INDEX location_name FOR (l:Location) ON (l.name);
CREATE INDEX location_type FOR (l:Location) ON (l.type);
CREATE INDEX npc_name FOR (n:NPC) ON (n.name);
CREATE INDEX npc_role FOR (n:NPC) ON (n.role);
CREATE INDEX item_name FOR (i:Item) ON (i.name);
CREATE INDEX item_type FOR (i:Item) ON (i.type);
CREATE INDEX event_type FOR (e:Event) ON (e.type);
CREATE INDEX event_triggered FOR (e:Event) ON (e.triggered_at);
CREATE INDEX quest_status FOR (q:Quest) ON (q.status);
CREATE INDEX world_name FOR (w:World) ON (w.name);
```

### 7.3 Composite Indexes

For multi-property queries.

```cypher
CREATE INDEX npc_location_state FOR (n:NPC) ON (n.role, n.is_alive);
CREATE INDEX item_visibility FOR (i:Item) ON (i.type, n.is_visible);
```

- FR-13.27: All indexes MUST be created by the schema migration script, not manually.
- FR-13.28: Index creation MUST be idempotent (use `CREATE ... IF NOT EXISTS` or
  equivalent).

---

## 8. Common Query Patterns

### 8.1 Location Context (most frequent query)

"Give me everything about where the player is."

```cypher
// Get location details, connected locations, NPCs present, and items here
MATCH (loc:Location {location_id: $location_id})
OPTIONAL MATCH (loc)-[conn:CONNECTS_TO]->(adj:Location)
OPTIONAL MATCH (npc:NPC)-[pin:PRESENT_IN]->(loc) WHERE npc.is_alive = true
OPTIONAL MATCH (loc)-[cont:CONTAINS]->(item:Item) WHERE item.is_visible = true
RETURN loc, collect(DISTINCT {location: adj, connection: conn}) AS exits,
       collect(DISTINCT {npc: npc, activity: pin.activity}) AS npcs,
       collect(DISTINCT item) AS items
```

- FR-13.29: This query MUST execute in under 50ms.
- FR-13.30: This is the primary query for the AI pipeline's context assembly step.

### 8.2 Movement (second most frequent)

"Can the player move in this direction? If so, where do they end up?"

```cypher
MATCH (from:Location {location_id: $from_id})-[conn:CONNECTS_TO {direction: $direction}]->(to:Location)
WHERE conn.is_locked = false AND to.is_accessible = true
RETURN to, conn
```

- FR-13.31: This query MUST execute in under 10ms.

### 8.3 NPC Knowledge Lookup

"What does this NPC know about the player's current situation?"

```cypher
MATCH (npc:NPC {npc_id: $npc_id})-[k:KNOWS_ABOUT]->(target)
WHERE k.is_secret = false OR $trust_level > 5
RETURN target, k.detail, k.knowledge_type
```

### 8.4 Nearby Entities (2-hop)

"What's within two moves of the player?"

```cypher
MATCH (start:Location {location_id: $location_id})
      -[:CONNECTS_TO*1..2]->(nearby:Location)
WHERE nearby.is_accessible = true
OPTIONAL MATCH (npc:NPC)-[:PRESENT_IN]->(nearby) WHERE npc.is_alive = true
RETURN nearby, collect(npc) AS npcs
```

- FR-13.32: This query MUST execute in under 200ms.

### 8.5 Event History

"What significant events have happened at this location recently?"

```cypher
MATCH (loc:Location {location_id: $location_id})<-[:INVOLVED_IN {role: "location"}]-(event:Event)
WHERE event.triggered_at > $since
RETURN event ORDER BY event.triggered_at DESC LIMIT 10
```

### 8.6 Quest Status

"What quests are available or active for the player?"

```cypher
MATCH (npc:NPC)-[:GIVES_QUEST]->(quest:Quest)
WHERE quest.status IN ['available', 'active']
  AND npc.is_alive = true
OPTIONAL MATCH (quest)-[:REQUIRES]->(req)
RETURN quest, npc, collect(req) AS requirements
```

### 8.7 Item Search

"Where is a specific item?"

```cypher
MATCH (item:Item {item_id: $item_id})
OPTIONAL MATCH (loc:Location)-[:CONTAINS]->(item)
OPTIONAL MATCH (owner)-[:OWNS]->(item)
RETURN item, loc, owner
```

---

## 9. State Mutation Rules

### 9.1 Player Movement

When a player moves from one location to another:

1. Verify the `CONNECTS_TO` relationship exists, is not locked, and target is accessible.
2. Delete the `LOCATED_IN` relationship from the old location.
3. Create a new `LOCATED_IN` relationship to the new location with `arrived_at = now()`
   and incremented `visited_count`.
4. Create an Event node for the movement.

- FR-13.33: All movement operations MUST be executed within a single Neo4j transaction.
- FR-13.34: If any step fails, the entire transaction MUST roll back.

### 9.2 Item Pickup

When a player picks up an item:

1. Verify the item exists at the player's current location (`CONTAINS` relationship).
2. Verify the item is portable (`is_portable = true`) and visible (`is_visible = true`).
3. Delete the `CONTAINS` relationship (Location → Item).
4. Create an `OWNS` relationship (PlayerSession → Item).
5. Create an Event node for the pickup.

- FR-13.35: The pickup MUST be atomic — either all steps succeed or none do.

### 9.3 Item Drop

Reverse of pickup:
1. Delete the `OWNS` relationship.
2. Create a `CONTAINS` relationship to the player's current location.
3. Create an Event node.

### 9.4 NPC Movement

NPCs can move between locations (triggered by game logic or events):

1. Delete the `PRESENT_IN` relationship from the old location.
2. Create a new `PRESENT_IN` relationship to the new location.
3. Update the NPC's `state` property.
4. Optionally create an Event node.

### 9.5 State Property Updates

Many mutations are simple property updates:
- NPC disposition changes (neutral → friendly)
- Location description changes (after an event alters the location)
- Item visibility changes (item becomes visible after a puzzle is solved)
- Connection lock state changes (door unlocked)

- FR-13.36: All property updates MUST update the `updated_at` timestamp.
- FR-13.37: Property updates MUST be executed within a transaction.

### 9.6 World State Mutation Summary

| Mutation | Transaction Required | Event Created |
|----------|---------------------|---------------|
| Player movement | Yes | Yes |
| Item pickup/drop | Yes | Yes |
| NPC movement | Yes | Optional |
| Property update | Yes | No (unless significant) |
| New node creation | Yes | No |
| Connection lock/unlock | Yes | Yes |
| Quest status change | Yes | Yes |

---

## 10. Temporal Tracking

### 10.1 Approach

TTA uses **property-based temporal tracking** — every mutable node carries `created_at`
and `updated_at` timestamps. Events provide a detailed history log.

This is simpler than full temporal graph versioning (maintaining historical snapshots of
the entire graph) and sufficient for v1's needs.

### 10.2 What Is Tracked

| What | How |
|------|-----|
| When a node was created | `created_at` property |
| When a node was last modified | `updated_at` property |
| When an NPC arrived at a location | `arrived_at` on `PRESENT_IN` |
| When a player visited a location | `arrived_at` and `visited_count` on `LOCATED_IN` |
| When an item was placed/acquired | `placed_at` on `CONTAINS`, `acquired_at` on `OWNS` |
| When significant events occurred | `triggered_at` on `Event` nodes |
| What changed and who was involved | `Event` nodes + `INVOLVED_IN` relationships |

### 10.3 Rules

- FR-13.38: All `created_at` values MUST be set at node creation time and MUST NOT be
  modified afterward.
- FR-13.39: All `updated_at` values MUST be updated on every property modification.
- FR-13.40: All datetime values MUST be stored as ISO 8601 strings in UTC.
- FR-13.41: Event nodes MUST NOT be modified after creation (append-only log).

### 10.4 Change Detection Query

"What has changed in the world since time T?"

```cypher
MATCH (n)
WHERE n.updated_at > $since
RETURN labels(n) AS type, n
ORDER BY n.updated_at DESC
```

This query supports the `state_update` SSE event type (see S10).

---

## 11. Schema Evolution

### 11.1 Migration Strategy

Neo4j does not have a built-in schema migration system like Alembic for SQL. TTA uses
versioned Cypher scripts.

- FR-13.42: Migrations MUST be stored as numbered Cypher files:
  `migrations/neo4j/001_initial_schema.cypher`, `002_add_quest_nodes.cypher`, etc.
- FR-13.43: Each migration MUST be idempotent (safe to re-run).
- FR-13.44: A `SchemaVersion` node in Neo4j MUST track which migrations have been applied.

### 11.2 Common Migration Patterns

**Adding a new node type:**
```cypher
// Idempotent: creating a constraint implicitly creates the label
CREATE CONSTRAINT new_type_id IF NOT EXISTS FOR (n:NewType) REQUIRE n.id IS UNIQUE;
```

**Adding a property to existing nodes:**
```cypher
// Add default value to all existing nodes that lack the property
MATCH (n:Location) WHERE n.light_level IS NULL
SET n.light_level = 'lit', n.updated_at = datetime();
```

**Adding a new relationship type:**
No schema change needed in Neo4j — relationships are schema-free. Just start creating
them. Application-level validation ensures correctness.

**Renaming a property:**
```cypher
MATCH (n:NPC) WHERE n.mood IS NOT NULL
SET n.disposition = n.mood
REMOVE n.mood
SET n.updated_at = datetime();
```

### 11.3 Rules

- FR-13.45: Migrations MUST NOT delete data without explicit confirmation (separate
  "destructive migration" category).
- FR-13.46: Every migration MUST be tested against a copy of production data before
  deployment.

---

## 12. Seed Data

### 12.1 World Seeding from Genesis

The Genesis system (see S04) generates world definitions. This section defines how those
definitions are loaded into the graph.

**Seed data format:** A structured document (JSON or YAML) containing:
- World metadata
- List of regions with their locations
- List of NPCs with their initial locations
- List of items with their initial locations
- List of connections between locations
- List of initial NPC knowledge entries

### 12.2 Seeding Process

1. Validate the seed data against the schema.
2. Create the World node.
3. Create all Region nodes with `CONTAINS_REGION` relationships.
4. Create all Location nodes with `CONTAINS_LOCATION` relationships.
5. Create all `CONNECTS_TO` relationships between locations.
6. Create all NPC nodes with `PRESENT_IN` relationships.
7. Create all Item nodes with `CONTAINS` relationships.
8. Create all `KNOWS_ABOUT` relationships.
9. Create all Quest nodes with related relationships.

- FR-13.47: The entire seeding operation MUST be executed within a single transaction. If
  any step fails, the entire world MUST NOT be partially created.
- FR-13.48: Seeding MUST be idempotent — running the seed on a world that already exists
  MUST fail with a clear error (not create duplicates).
- FR-13.49: Seed validation MUST check referential integrity (e.g., NPCs reference
  locations that exist in the seed data).

### 12.3 Seed Data Validation Rules

| Check | Description |
|-------|-------------|
| All IDs unique | No duplicate `*_id` values within the seed |
| All references valid | NPCs reference existing locations, connections reference existing locations |
| At least one location | A world must have at least one playable location |
| Connected graph | All locations are reachable from at least one other location (no orphans) |
| No direction conflicts | A location doesn't have two exits in the same direction |
| Required properties present | All required properties per node type are provided |

---

## 13. Player Session Representation in Graph

Player game sessions are represented minimally in the graph — just enough to support
game queries. The full session data lives in SQL (see S12).

### 13.1 PlayerSession Node

| Property | Type | Required | Indexed | Description |
|----------|------|----------|---------|-------------|
| `session_id` | String (ULID) | Yes | Unique | Maps to `game_id` in SQL |
| `player_id` | String (ULID) | Yes | Yes | Maps to player in SQL |
| `world_id` | String (ULID) | Yes | Yes | Which world this session is in |
| `created_at` | DateTime | Yes | No | |

**Relationships:**
- `(:PlayerSession)-[:LOCATED_IN]->(:Location)` — current position
- `(:PlayerSession)-[:OWNS]->(:Item)` — inventory
- `(:PlayerSession)-[:INVOLVED_IN]->(:Event)` — participation in events

- FR-13.50: PlayerSession nodes are lightweight pointers. Detailed session data (turn
  history, timestamps, status) lives in SQL.
- FR-13.51: When a game session ends (see S11), the PlayerSession node and all its
  relationships MAY be archived or deleted from the graph.
- FR-13.52: The `session_id` in Neo4j MUST match the `game_id` in SQL for cross-store
  lookups.

---

## 14. Acceptance Criteria

### Schema Correctness

- AC-13.01: A seeded world graph passes all referential integrity checks (no dangling
  references, no orphaned nodes, no duplicate IDs).
- AC-13.02: All uniqueness constraints prevent duplicate node creation (verified by
  attempting duplicate insertion).
- AC-13.03: All required properties are enforced (verified by attempting node creation
  with missing properties).

### Query Performance

- AC-13.04: Location context query (§8.1) completes in under 50ms on a world with 1,000
  locations.
- AC-13.05: Movement validation query (§8.2) completes in under 10ms.
- AC-13.06: 2-hop nearby entities query (§8.4) completes in under 200ms on a world with
  1,000 locations.

### State Mutation

- AC-13.07: Player movement atomically updates the `LOCATED_IN` relationship and creates
  an Event — verified by checking that on transaction failure, neither change persists.
- AC-13.08: Item pickup atomically transfers ownership from location to player — no
  state where the item belongs to neither or both.
- AC-13.09: No operation can create a state where an NPC has two `PRESENT_IN`
  relationships simultaneously.

### Seeding

- AC-13.10: A valid seed file produces a graph that matches the seed data exactly (all
  nodes, relationships, and properties present).
- AC-13.11: An invalid seed file (missing required property, dangling reference) is
  rejected with a descriptive error before any nodes are created.
- AC-13.12: Running the seed operation twice for the same world fails with a clear error
  on the second attempt.

### Temporal Tracking

- AC-13.13: After modifying an NPC's disposition, `updated_at` is newer than `created_at`.
- AC-13.14: A change detection query for "last 5 minutes" returns only nodes modified
  in that window.

### Cross-Store Consistency

- AC-13.15: The `session_id` on a PlayerSession node in Neo4j matches a `game_id` in
  the SQL games table.
- AC-13.16: Deleting a game session in SQL also removes (or archives) the corresponding
  PlayerSession node in Neo4j.

---

## 15. Edge Cases

- EC-13.01: A location has no exits (dead end). This is valid — the player may need to
  use an item or trigger an event to create an exit. The graph MUST allow locations with
  zero `CONNECTS_TO` relationships.

- EC-13.02: An NPC "dies" during gameplay. The NPC's `is_alive` property is set to false,
  but the node is NOT deleted (preserves event history and knowledge graph). The NPC stops
  appearing in location context queries.

- EC-13.03: A circular connection (Location A → Location B → Location A). This is valid
  and common. The query patterns handle cycles because they specify explicit depth limits.

- EC-13.04: Two NPCs at the same location both know about the same item but have
  different `KNOWS_ABOUT` details. This is expected — NPCs have independent knowledge.

- EC-13.05: A quest requires an item that has been dropped in an inaccessible location.
  The game logic (not the graph schema) must handle this gracefully. The graph schema
  MUST NOT prevent this state.

- EC-13.06: World seed data contains 10,000+ nodes. The seeding transaction MUST still
  complete within 30 seconds. For very large worlds, batch seeding (multiple transactions
  with rollback coordination) may be needed post-v1.

---

## 16. Open Questions

- OQ-13.01: Should `CONNECTS_TO` relationships be bidirectional by convention (always
  create both directions) or explicitly unidirectional? Current design: explicit — a
  one-way door is one relationship; a hallway is two. This is more expressive but
  requires careful seeding.

- OQ-13.02: Should player inventory be modeled in the graph (as `OWNS` relationships)
  or in SQL (as a JSON array on the game state)? Current design: graph, for consistency
  with world state queries. But this means cross-store coordination on item pickup.
  Worth revisiting.

- OQ-13.03: Should we track "visited locations" in the graph (via `LOCATED_IN`
  relationship history) or in the SQL game state? Current design: `visited_count` on the
  `LOCATED_IN` relationship, but historical visits are not retained. May need a
  `VISITED` relationship type if we want full history.

- OQ-13.04: How should procedurally generated world extensions (new locations discovered
  during gameplay) interact with the seed data model? The graph supports dynamic node
  creation, but the validation rules assume a static seed. Need a "dynamic extension"
  pattern.

- OQ-13.05: Should NPC knowledge be stored as properties on `KNOWS_ABOUT` relationships
  or as separate `Knowledge` nodes? Relationships are simpler. Separate nodes would
  support richer metadata (source, confidence, decay). Relationships are fine for v1.
