// Large world fixture — 20 regions, 1 000 locations, 200 NPCs, 100 items, 1 player.
// session_id = __SESSION_ID__ (replaced at load time by neo4j_large_world fixture)
// Use UNWIND-based bulk creates to avoid one-statement-per-node overhead.

// ── Regions (region_0 … region_19) ───────────────────────────────────────────
UNWIND range(0, 19) AS i
CREATE (:Region {
  region_id:  'large-region-' + toString(i),
  name:       'Region ' + toString(i),
  session_id: '__SESSION_ID__',
  created_at: datetime(),
  updated_at: datetime()
});

// ── Locations (loc_R_L where R=0-19, L=0-49) — 1 000 total ──────────────────
UNWIND range(0, 19) AS r
UNWIND range(0, 49) AS l
CREATE (:Location {
  id:          'large-loc-' + toString(r) + '-' + toString(l),
  location_id: 'large-loc-' + toString(r) + '-' + toString(l),
  name:        'Location ' + toString(r) + '_' + toString(l),
  description: 'Location ' + toString(l) + ' in region ' + toString(r),
  type:        'interior',
  session_id:  '__SESSION_ID__',
  created_at:  datetime(),
  updated_at:  datetime()
});

// ── CONTAINS_LOCATION: region → all its locations ────────────────────────────
UNWIND range(0, 19) AS r
UNWIND range(0, 49) AS l
MATCH (reg:Region   {region_id:   'large-region-' + toString(r),               session_id: '__SESSION_ID__'})
MATCH (loc:Location {id: 'large-loc-' + toString(r) + '-' + toString(l), session_id: '__SESSION_ID__'})
CREATE (reg)-[:CONTAINS_LOCATION]->(loc);

// ── CONNECTS_TO chains: loc_R_L → loc_R_(L+1) (linear path within each region) ──
UNWIND range(0, 19) AS r
UNWIND range(0, 48) AS l
MATCH (a:Location {id: 'large-loc-' + toString(r) + '-' + toString(l),       session_id: '__SESSION_ID__'})
MATCH (b:Location {id: 'large-loc-' + toString(r) + '-' + toString(l + 1),   session_id: '__SESSION_ID__'})
CREATE (a)-[:CONNECTS_TO]->(b);

// ── NPCs (npc_0 … npc_199), each IS_AT loc_(i%20)_(i%50) ─────────────────
UNWIND range(0, 199) AS i
CREATE (:NPC {
  id:         'large-npc-' + toString(i),
  npc_id:     'large-npc-' + toString(i),
  name:       'NPC ' + toString(i),
  description: 'A test NPC number ' + toString(i),
  disposition: 'neutral',
  alive:      true,
  session_id: '__SESSION_ID__',
  created_at: datetime(),
  updated_at: datetime()
});

UNWIND range(0, 199) AS i
MATCH (npc:NPC      {npc_id:      'large-npc-' + toString(i),                               session_id: '__SESSION_ID__'})
MATCH (loc:Location {id: 'large-loc-' + toString(i % 20) + '-' + toString(i % 50), session_id: '__SESSION_ID__'})
CREATE (npc)-[:IS_AT]->(loc);

// ── Items (item_0 … item_99), each IS_AT loc_(i%20)_(i%50) ─────────────
UNWIND range(0, 99) AS i
CREATE (:Item {
  id:         'large-item-' + toString(i),
  item_id:    'large-item-' + toString(i),
  name:       'Item ' + toString(i),
  description: 'A test item number ' + toString(i),
  hidden:     false,
  session_id: '__SESSION_ID__',
  created_at: datetime(),
  updated_at: datetime()
});

UNWIND range(0, 99) AS i
MATCH (item:Item    {item_id:     'large-item-' + toString(i),                               session_id: '__SESSION_ID__'})
MATCH (loc:Location {id: 'large-loc-' + toString(i % 20) + '-' + toString(i % 50), session_id: '__SESSION_ID__'})
CREATE (item)-[:IS_AT]->(loc);

// ── Player (player_1) IS_AT loc_0_0 ────────────────────────────────────
MATCH (loc:Location {id: 'large-loc-0-0', session_id: '__SESSION_ID__'})
CREATE (:Player {
  id:         'large-player-1',
  player_id:  'large-player-1',
  name:       'Test Player',
  description: 'A test player',
  session_id: '__SESSION_ID__',
  created_at: datetime(),
  updated_at: datetime()
})-[:IS_AT]->(loc)
