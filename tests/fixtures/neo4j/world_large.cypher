// world_large.cypher — 1 000-location world for performance tests.
// session_id is injected via string replacement before use.

// Constraints (idempotent)
CREATE CONSTRAINT location_unique IF NOT EXISTS
  FOR (l:Location) REQUIRE (l.session_id, l.location_id) IS UNIQUE;
CREATE CONSTRAINT npc_unique IF NOT EXISTS
  FOR (n:NPC) REQUIRE (n.session_id, n.npc_id) IS UNIQUE;

// World node
MERGE (w:World {session_id: '__SESSION_ID__'})
  ON CREATE SET w.created_at = datetime();

// Generate 20 regions × 50 locations each (done via UNWIND)
WITH range(0, 19) AS regions
UNWIND regions AS ri
  MERGE (reg:Region {
    session_id: '__SESSION_ID__',
    region_id: 'region_' + toString(ri),
    name: 'Region ' + toString(ri)
  });

WITH range(0, 19) AS regions
UNWIND regions AS ri
  WITH ri, range(0, 49) AS locs
  UNWIND locs AS li
    MERGE (loc:Location {
      session_id: '__SESSION_ID__',
      location_id: 'loc_' + toString(ri) + '_' + toString(li),
      name: 'Location ' + toString(ri) + '_' + toString(li),
      archetype: 'room',
      created_at: datetime(),
      updated_at: datetime()
    })
    WITH loc, ri
    MATCH (reg:Region {
      session_id: '__SESSION_ID__',
      region_id: 'region_' + toString(ri)
    })
    MERGE (loc)-[:IN_REGION]->(reg);

// Connect locations within each region (chain: loc_r_0 → loc_r_1 → … → loc_r_49)
WITH range(0, 19) AS regions
UNWIND regions AS ri
  WITH ri, range(0, 48) AS locs
  UNWIND locs AS li
    MATCH (a:Location {
      session_id: '__SESSION_ID__',
      location_id: 'loc_' + toString(ri) + '_' + toString(li)
    })
    MATCH (b:Location {
      session_id: '__SESSION_ID__',
      location_id: 'loc_' + toString(ri) + '_' + toString(li + 1)
    })
    MERGE (a)-[:EXIT {direction: 'north'}]->(b)
    MERGE (b)-[:EXIT {direction: 'south'}]->(a);

// 200 NPCs spread across first 200 locations
WITH range(0, 199) AS npcs
UNWIND npcs AS ni
  MATCH (loc:Location {
    session_id: '__SESSION_ID__',
    location_id: 'loc_' + toString(toInteger(ni / 10)) + '_' + toString(ni % 10)
  })
  MERGE (npc:NPC {
    session_id: '__SESSION_ID__',
    npc_id: 'npc_' + toString(ni),
    name: 'NPC ' + toString(ni),
    archetype: 'villager',
    created_at: datetime(),
    updated_at: datetime()
  })
  MERGE (npc)-[:PRESENT_IN]->(loc);

// 100 items spread across first 100 locations
WITH range(0, 99) AS items
UNWIND items AS ii
  MATCH (loc:Location {
    session_id: '__SESSION_ID__',
    location_id: 'loc_' + toString(toInteger(ii / 10)) + '_' + toString(ii % 10)
  })
  MERGE (item:Item {
    session_id: '__SESSION_ID__',
    item_id: 'item_' + toString(ii),
    name: 'Item ' + toString(ii),
    created_at: datetime(),
    updated_at: datetime()
  })
  MERGE (item)-[:AT_LOCATION]->(loc);

// Player starting at loc_0_0
MERGE (player:Player {session_id: '__SESSION_ID__', player_id: 'player_1'})
MERGE (loc0:Location {session_id: '__SESSION_ID__', location_id: 'loc_0_0'})
MERGE (player)-[:LOCATED_IN]->(loc0)
