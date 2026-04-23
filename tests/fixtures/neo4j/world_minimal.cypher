// Minimal world fixture — 1 Universe, 1 Location, 1 Actor.
// Used for basic graph CRUD tests.

CREATE (u:Universe {
  world_id: 'test-world-001',
  name: 'Test World',
  status: 'active',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (loc:Location {
  location_id: 'test-loc-001',
  name: 'Starting Area',
  description: 'A quiet clearing.',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (actor:Actor {
  npc_id: 'test-actor-001',
  name: 'Test Actor',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (u)-[:CONTAINS_LOCATION]->(loc)
CREATE (actor)-[:LOCATED_IN]->(loc)
