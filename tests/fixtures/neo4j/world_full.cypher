// Full world fixture — all S13 node types + all 7 uniqueness constraints.
// This fixture is loaded once per session (neo4j_db). It establishes
// schema constraints/indexes so they are present for all subsequent tests.

// ── Uniqueness constraints (S13 schema) ─────────────────────────────────────
CREATE CONSTRAINT universe_id_unique IF NOT EXISTS
  FOR (n:Universe) REQUIRE n.world_id IS UNIQUE;

CREATE CONSTRAINT region_id_unique IF NOT EXISTS
  FOR (n:Region) REQUIRE n.region_id IS UNIQUE;

CREATE CONSTRAINT location_id_unique IF NOT EXISTS
  FOR (n:Location) REQUIRE n.location_id IS UNIQUE;

CREATE CONSTRAINT npc_id_unique IF NOT EXISTS
  FOR (n:NPC) REQUIRE n.npc_id IS UNIQUE;

CREATE CONSTRAINT item_id_unique IF NOT EXISTS
  FOR (n:Item) REQUIRE n.item_id IS UNIQUE;

CREATE CONSTRAINT event_id_unique IF NOT EXISTS
  FOR (n:Event) REQUIRE n.event_id IS UNIQUE;

CREATE CONSTRAINT quest_id_unique IF NOT EXISTS
  FOR (n:Quest) REQUIRE n.quest_id IS UNIQUE;

// ── Lookup indexes ────────────────────────────────────────────────────────────
CREATE INDEX universe_status_idx IF NOT EXISTS FOR (n:Universe) ON (n.status);
CREATE INDEX location_name_idx   IF NOT EXISTS FOR (n:Location) ON (n.name);
CREATE INDEX npc_name_idx        IF NOT EXISTS FOR (n:NPC) ON (n.name);
CREATE INDEX item_name_idx       IF NOT EXISTS FOR (n:Item) ON (n.name);
CREATE INDEX event_type_idx      IF NOT EXISTS FOR (n:Event) ON (n.event_type);
CREATE INDEX quest_status_idx    IF NOT EXISTS FOR (n:Quest) ON (n.status);
CREATE INDEX region_name_idx     IF NOT EXISTS FOR (n:Region) ON (n.name);

// ── Full test world data ──────────────────────────────────────────────────────

CREATE (u:Universe {
  world_id: 'test-world-full-001',
  name: 'Full Test World',
  status: 'active',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (r1:Region {
  region_id: 'test-region-full-001',
  name: 'Eastern Province',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (r2:Region {
  region_id: 'test-region-full-002',
  name: 'Western Province',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (loc1:Location {
  location_id: 'test-loc-full-001',
  name: 'Capital City',
  description: 'The heart of the kingdom.',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (loc2:Location {
  location_id: 'test-loc-full-002',
  name: 'Ancient Ruins',
  description: 'Crumbling stone arches.',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (npc1:NPC {
  npc_id: 'test-npc-full-001',
  name: 'King Aldric',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (npc2:NPC {
  npc_id: 'test-npc-full-002',
  name: 'Sorceress Mira',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (item1:Item {
  item_id: 'test-item-full-001',
  name: 'Enchanted Sword',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (item2:Item {
  item_id: 'test-item-full-002',
  name: 'Ancient Tome',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (ev1:Event {
  event_id: 'test-event-full-001',
  event_type: 'npc_encounter',
  description: 'King met the sorceress.',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (q1:Quest {
  quest_id: 'test-quest-full-001',
  name: 'Find the Ancient Tome',
  status: 'active',
  created_at: datetime(),
  updated_at: datetime()
})

// Relationships
CREATE (u)-[:CONTAINS_REGION]->(r1)
CREATE (u)-[:CONTAINS_REGION]->(r2)
CREATE (r1)-[:CONTAINS_LOCATION]->(loc1)
CREATE (r2)-[:CONTAINS_LOCATION]->(loc2)
CREATE (loc1)-[:CONNECTS_TO]->(loc2)
CREATE (npc1)-[:PRESENT_IN]->(loc1)
CREATE (npc2)-[:PRESENT_IN]->(loc2)
CREATE (npc1)-[:KNOWS_ABOUT]->(npc2)
CREATE (item1)-[:LOCATED_IN]->(loc1)
CREATE (item2)-[:LOCATED_IN]->(loc2)
CREATE (npc2)-[:CONTAINS]->(item2)
CREATE (ev1)-[:LOCATED_IN]->(loc1)
