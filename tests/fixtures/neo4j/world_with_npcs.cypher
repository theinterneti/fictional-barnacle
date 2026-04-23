// World-with-NPCs fixture — 3 Locations, 2 NPCs, relationship edges.
// Used for NPC presence tests.

CREATE (u:Universe {
  world_id: 'test-world-002',
  name: 'NPC Test World',
  status: 'active',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (r:Region {
  region_id: 'test-region-001',
  name: 'Northern Reaches',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (loc1:Location {
  location_id: 'test-loc-101',
  name: 'Market Square',
  description: 'A busy marketplace.',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (loc2:Location {
  location_id: 'test-loc-102',
  name: 'Tavern',
  description: 'A rowdy tavern.',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (loc3:Location {
  location_id: 'test-loc-103',
  name: 'Blacksmith',
  description: 'A forge.',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (npc1:NPC {
  npc_id: 'test-npc-001',
  name: 'Merchant Greta',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (npc2:NPC {
  npc_id: 'test-npc-002',
  name: 'Guard Bjorn',
  created_at: datetime(),
  updated_at: datetime()
})

CREATE (u)-[:CONTAINS_REGION]->(r)
CREATE (r)-[:CONTAINS_LOCATION]->(loc1)
CREATE (r)-[:CONTAINS_LOCATION]->(loc2)
CREATE (r)-[:CONTAINS_LOCATION]->(loc3)
CREATE (loc1)-[:CONNECTS_TO]->(loc2)
CREATE (loc2)-[:CONNECTS_TO]->(loc3)
CREATE (npc1)-[:PRESENT_IN]->(loc1)
CREATE (npc2)-[:PRESENT_IN]->(loc1)
CREATE (npc1)-[:KNOWS_ABOUT]->(npc2)
