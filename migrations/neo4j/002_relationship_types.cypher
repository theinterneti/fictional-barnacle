// TTA World Graph — Relationship Types & Extended Schema (002)
//
// Adds Event and Quest node constraints, relationship property
// indexes, and composite indexes per S13 §5.6-5.7, §6.5-6.7, §7.
//
// Neo4j CE constraints: only UNIQUE is supported.
// Property existence constraints require Enterprise — noted
// as comments.

// --- Event node (S13 §5.6) ---
// Properties: id (ULID, unique), type, description, severity,
//   is_public (bool), triggered_at (DateTime), session_id,
//   created_at

CREATE CONSTRAINT event_id_unique IF NOT EXISTS
FOR (e:Event) REQUIRE e.id IS UNIQUE;

CREATE INDEX event_session_id IF NOT EXISTS
FOR (e:Event) ON (e.session_id);

CREATE INDEX event_type IF NOT EXISTS
FOR (e:Event) ON (e.type);

CREATE INDEX event_triggered_at IF NOT EXISTS
FOR (e:Event) ON (e.triggered_at);

// --- Quest node (S13 §5.7) ---
// Properties: id (ULID, unique), name, description, status
//   ("active"/"completed"/"failed"/"abandoned"), difficulty,
//   xp_reward, session_id, created_at, updated_at

CREATE CONSTRAINT quest_id_unique IF NOT EXISTS
FOR (q:Quest) REQUIRE q.id IS UNIQUE;

CREATE INDEX quest_session_id IF NOT EXISTS
FOR (q:Quest) ON (q.session_id);

CREATE INDEX quest_status IF NOT EXISTS
FOR (q:Quest) ON (q.status);

// --- Composite indexes (S13 §7) ---

CREATE INDEX npc_location_state IF NOT EXISTS
FOR (n:NPC) ON (n.role, n.is_alive);

CREATE INDEX item_visibility IF NOT EXISTS
FOR (i:Item) ON (i.type, i.is_visible);

// --- Relationship property indexes ---
// Neo4j 5.x supports relationship property indexes.

// KNOWS_ABOUT (S13 §6.5)
// (NPC|Player)-[:KNOWS_ABOUT]->(NPC|Item|Location|Event)
// Required: knowledge_type (str), detail (str),
//   is_secret (bool), learned_at (DateTime)
CREATE INDEX knows_about_knowledge_type IF NOT EXISTS
FOR ()-[r:KNOWS_ABOUT]-() ON (r.knowledge_type);

CREATE INDEX knows_about_is_secret IF NOT EXISTS
FOR ()-[r:KNOWS_ABOUT]-() ON (r.is_secret);

// OWNS (S13 §6.6)
// (NPC|Player)-[:OWNS]->(Item)
// Required: acquired_at (DateTime)
// Optional: acquisition_method (str — "found"|"bought"|
//   "given"|"crafted"|"stolen")
CREATE INDEX owns_acquired_at IF NOT EXISTS
FOR ()-[r:OWNS]-() ON (r.acquired_at);

CREATE INDEX owns_acquisition_method IF NOT EXISTS
FOR ()-[r:OWNS]-() ON (r.acquisition_method);

// INVOLVED_IN (S13 §6.7)
// (NPC|Player|Location|Item)-[:INVOLVED_IN]->(Event|Quest)
// Required: role (str — "cause"|"witness"|"target"|"location")
CREATE INDEX involved_in_role IF NOT EXISTS
FOR ()-[r:INVOLVED_IN]-() ON (r.role);

// --- Property existence constraints (Enterprise only) ---
//
// CREATE CONSTRAINT event_id_exists IF NOT EXISTS
// FOR (e:Event) REQUIRE e.id IS NOT NULL;
//
// CREATE CONSTRAINT event_session_id_exists IF NOT EXISTS
// FOR (e:Event) REQUIRE e.session_id IS NOT NULL;
//
// CREATE CONSTRAINT quest_id_exists IF NOT EXISTS
// FOR (q:Quest) REQUIRE q.id IS NOT NULL;
//
// CREATE CONSTRAINT quest_session_id_exists IF NOT EXISTS
// FOR (q:Quest) REQUIRE q.session_id IS NOT NULL;
//
// --- Relationship property existence (Enterprise only) ---
//
// KNOWS_ABOUT required: knowledge_type, detail, is_secret,
//   learned_at
// OWNS required: acquired_at
// INVOLVED_IN required: role

// --- Relationship types (documented, not enforceable) ---
//
// (NPC|Player)-[:KNOWS_ABOUT {knowledge_type, detail,
//   is_secret, learned_at}]->(NPC|Item|Location|Event)
// (NPC|Player)-[:OWNS {acquired_at,
//   acquisition_method?}]->(Item)
// (NPC|Player|Location|Item)-[:INVOLVED_IN
//   {role}]->(Event|Quest)
//
// All relationships carry a session_id property.
