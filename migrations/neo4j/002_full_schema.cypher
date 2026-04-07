// Migration 002: Full Wave 3 schema extensions
// Adds constraints and indexes for Region, Event, Quest, PlayerSession
// and lookup indexes for all node types.
// All statements use IF NOT EXISTS for idempotency.

// --- Uniqueness constraints (new node types) ---

CREATE CONSTRAINT world_id_unique IF NOT EXISTS
  FOR (w:World) REQUIRE w.id IS UNIQUE;

CREATE CONSTRAINT world_session_unique IF NOT EXISTS
  FOR (w:World) REQUIRE w.session_id IS UNIQUE;

CREATE CONSTRAINT region_id_unique IF NOT EXISTS
  FOR (r:Region) REQUIRE r.id IS UNIQUE;

CREATE CONSTRAINT event_id_unique IF NOT EXISTS
  FOR (e:Event) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT quest_id_unique IF NOT EXISTS
  FOR (q:Quest) REQUIRE q.id IS UNIQUE;

CREATE CONSTRAINT player_session_unique IF NOT EXISTS
  FOR (ps:PlayerSession) REQUIRE ps.session_id IS UNIQUE;

// --- Session isolation indexes (new node types) ---

CREATE INDEX region_session IF NOT EXISTS
  FOR (r:Region) ON (r.session_id);

CREATE INDEX event_session IF NOT EXISTS
  FOR (e:Event) ON (e.session_id);

CREATE INDEX quest_session IF NOT EXISTS
  FOR (q:Quest) ON (q.session_id);

// --- Lookup indexes ---

CREATE INDEX location_name IF NOT EXISTS
  FOR (l:Location) ON (l.name);

CREATE INDEX location_type IF NOT EXISTS
  FOR (l:Location) ON (l.type);

CREATE INDEX npc_name IF NOT EXISTS
  FOR (n:NPC) ON (n.name);

CREATE INDEX npc_role IF NOT EXISTS
  FOR (n:NPC) ON (n.role);

CREATE INDEX item_name IF NOT EXISTS
  FOR (i:Item) ON (i.name);

CREATE INDEX item_type IF NOT EXISTS
  FOR (i:Item) ON (i.item_type);

CREATE INDEX event_type IF NOT EXISTS
  FOR (e:Event) ON (e.type);

CREATE INDEX event_triggered_at IF NOT EXISTS
  FOR (e:Event) ON (e.triggered_at);

CREATE INDEX quest_status IF NOT EXISTS
  FOR (q:Quest) ON (q.status);

CREATE INDEX player_session_world IF NOT EXISTS
  FOR (ps:PlayerSession) ON (ps.world_id);

// --- Schema version tracking ---

MERGE (v:_SchemaVersion {version: 2})
  ON CREATE SET
    v.applied_at = datetime(),
    v.description = 'Full Wave 3 schema: Region, Event, Quest, PlayerSession + lookup indexes'
  ON MATCH SET
    v.reapplied_at = datetime();
