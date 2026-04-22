// TTA World Graph — Universe Extension (004)
//
// Wave v2A: Add universe_id property to all simulation nodes.
// Backfills universe_id from session_id for pre-v2 nodes.
// Adds composite indexes for universe-scoped queries.

// --- Backfill universe_id from session_id on World nodes ---
MATCH (n:World)
WHERE n.session_id IS NOT NULL AND n.universe_id IS NULL
SET n.universe_id = n.session_id;

// --- Backfill on Region nodes ---
MATCH (n:Region)
WHERE n.session_id IS NOT NULL AND n.universe_id IS NULL
SET n.universe_id = n.session_id;

// --- Backfill on Location nodes ---
MATCH (n:Location)
WHERE n.session_id IS NOT NULL AND n.universe_id IS NULL
SET n.universe_id = n.session_id;

// --- Backfill on NPC nodes ---
MATCH (n:NPC)
WHERE n.session_id IS NOT NULL AND n.universe_id IS NULL
SET n.universe_id = n.session_id;

// --- Backfill on Item nodes ---
MATCH (n:Item)
WHERE n.session_id IS NOT NULL AND n.universe_id IS NULL
SET n.universe_id = n.session_id;

// --- Backfill on Event nodes ---
MATCH (n:Event)
WHERE n.session_id IS NOT NULL AND n.universe_id IS NULL
SET n.universe_id = n.session_id;

// --- Backfill on Quest nodes ---
MATCH (n:Quest)
WHERE n.session_id IS NOT NULL AND n.universe_id IS NULL
SET n.universe_id = n.session_id;

// --- Index: universe_id on World (lookup root node for a universe) ---
CREATE INDEX world_universe_id IF NOT EXISTS
FOR (n:World) ON (n.universe_id);

// --- Index: universe_id on Region ---
CREATE INDEX region_universe_id IF NOT EXISTS
FOR (n:Region) ON (n.universe_id);

// --- Index: universe_id on Location ---
CREATE INDEX location_universe_id IF NOT EXISTS
FOR (n:Location) ON (n.universe_id);

// --- Index: universe_id on NPC ---
CREATE INDEX npc_universe_id IF NOT EXISTS
FOR (n:NPC) ON (n.universe_id);

// --- Index: universe_id on Item ---
CREATE INDEX item_universe_id IF NOT EXISTS
FOR (n:Item) ON (n.universe_id);

// --- Index: universe_id on Event ---
CREATE INDEX event_universe_id IF NOT EXISTS
FOR (n:Event) ON (n.universe_id);

// --- Index: universe_id on Quest ---
CREATE INDEX quest_universe_id IF NOT EXISTS
FOR (n:Quest) ON (n.universe_id);
