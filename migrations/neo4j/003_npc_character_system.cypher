// TTA World Graph — NPC Character System (002)
//
// Wave 5: Character depth fields, tier index, relationship tracking.
// Adds indexes for NPC tier queries and RELATES_TO relationships.

// --- NPC tier index ---
CREATE INDEX npc_tier IF NOT EXISTS
FOR (n:NPC) ON (n.tier);

// --- Relationship index (trust-based lookups) ---
CREATE INDEX rel_trust IF NOT EXISTS
FOR ()-[r:RELATES_TO]-() ON (r.trust);
