// TTA World Graph — Initial Schema (001)
//
// Node labels: Location, NPC, Item, Connection, World
// All nodes carry a session_id property for multi-session isolation.
//
// Neo4j CE constraints: only UNIQUE is supported.
// Property existence constraints require Enterprise — noted as comments.

// --- Uniqueness constraints ---

CREATE CONSTRAINT location_id_unique IF NOT EXISTS
FOR (l:Location) REQUIRE l.id IS UNIQUE;

CREATE CONSTRAINT npc_id_unique IF NOT EXISTS
FOR (n:NPC) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT item_id_unique IF NOT EXISTS
FOR (i:Item) REQUIRE i.id IS UNIQUE;

// --- Session-scoped indexes for query performance ---

CREATE INDEX location_session_id IF NOT EXISTS
FOR (l:Location) ON (l.session_id);

CREATE INDEX npc_session_id IF NOT EXISTS
FOR (n:NPC) ON (n.session_id);

CREATE INDEX item_session_id IF NOT EXISTS
FOR (i:Item) ON (i.session_id);

CREATE INDEX connection_session_id IF NOT EXISTS
FOR (c:Connection) ON (c.session_id);

CREATE INDEX world_session_id IF NOT EXISTS
FOR (w:World) ON (w.session_id);

// --- Property existence constraints (Neo4j Enterprise only) ---
// These document the required properties but cannot be enforced on CE.
//
// CREATE CONSTRAINT location_id_exists IF NOT EXISTS
// FOR (l:Location) REQUIRE l.id IS NOT NULL;
//
// CREATE CONSTRAINT location_session_id_exists IF NOT EXISTS
// FOR (l:Location) REQUIRE l.session_id IS NOT NULL;
//
// CREATE CONSTRAINT npc_id_exists IF NOT EXISTS
// FOR (n:NPC) REQUIRE n.id IS NOT NULL;
//
// CREATE CONSTRAINT npc_session_id_exists IF NOT EXISTS
// FOR (n:NPC) REQUIRE n.session_id IS NOT NULL;
//
// CREATE CONSTRAINT item_id_exists IF NOT EXISTS
// FOR (i:Item) REQUIRE i.id IS NOT NULL;
//
// CREATE CONSTRAINT item_session_id_exists IF NOT EXISTS
// FOR (i:Item) REQUIRE i.session_id IS NOT NULL;

// --- Relationship types (documented, not enforceable via DDL) ---
//
// (Location)-[:CONNECTS_TO {direction, distance}]->(Location)
// (NPC)-[:LOCATED_AT]->(Location)
// (Item)-[:LOCATED_AT]->(Location)
// (Item)-[:HELD_BY]->(NPC)
//
// All relationships carry a session_id property.
