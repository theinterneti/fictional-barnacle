# S33 — Universe Persistence Schema

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 3 — Platform
> **Dependencies**: v2 S29, v2 S31, v1 S12, v1 S13
> **Last Updated**: 2026-04-21

---

## 1. Purpose

v1 had no explicit concept of a "universe." World state lived in three places:

- **PostgreSQL** `game_sessions.world_seed` — a JSONB blob encoding the initial world
  parameters used to generate the world at session start.
- **PostgreSQL** `game_snapshots.world_state` — a per-turn JSONB snapshot capturing the
  current world state for crash recovery.
- **Neo4j** — the live knowledge graph containing Location, NPC, Item, Region, Event,
  and Quest nodes, isolated per session via a `session_id` property.

There was no `universes` table, no `actors` table, and no `character_states` table. The
player's character state was implicit in the snapshot blob.

This spec defines:

1. The **new PostgreSQL tables** that v2 introduces for universe persistence:
   `universes`, `actors`, `character_states`, `universe_snapshots`.
2. The **v1 → v2 migration DDL** — the Alembic migration that adds the new tables,
   backfills data from existing v1 records, and adds the new FK columns to
   `game_sessions`.
3. The **Neo4j schema additions** that add `universe_id` indexing to all world-scoped
   graph nodes.
4. The **durable universe snapshot** mechanism (distinct from v1's per-turn
   `game_snapshots`) that captures cross-session world state at session end.

This spec does NOT define how the turn pipeline uses these tables (that is S08 / S12),
nor how genesis populates them (S40). This spec defines what exists in the database and
how v1 data is safely migrated to that state.

---

## 2. Design Philosophy

**Additive migration**: the v1 → v2 migration adds new tables and new FK columns. It
never drops or renames an existing column. The `world_seed` column on `game_sessions` is
preserved (read-only after migration), maintaining backward compatibility with v1
snapshot archives and audit logs.

**Source of truth for migration**: each v1 `game_sessions` row carries `world_seed`
(the world parameters) and is the source for one `universes` row. The `session_id` is
the bridge key between PostgreSQL and Neo4j during migration (since `World.session_id`
is unique in v1 Neo4j).

**One universe per v1 session**: in v1, each game session generated an independent
world from scratch. There was no universe continuity between sessions. Therefore each v1
`game_sessions` row becomes a distinct universe in v2, with the v1 session bound to
that universe (one-session history). This means v1 data does NOT demonstrate cross-
session universe continuity — it bootstraps the universe graph cleanly.

**ULID for universe_id**: universe IDs are ULIDs (text, 26 chars), matching the S29
design. PostgreSQL `gen_random_uuid()` is used for the UUIDs on actors and
character_states (ordinary entities), but `universe_id` uses a ULID generation function
(see Appendix A).

**No downtime migration**: all DDL steps are safe for rolling deployments:
(1) new tables with no FK constraints → (2) add nullable FK columns → (3) backfill →
(4) add NOT NULL constraint → (5) add indexes. Step 4 can be deferred to v2.1 if
backfill must run offline.

---

## 3. User Stories

### Migration Safety

- **US-33.1** — **As a** developer upgrading from v1 to v2, **I want** the migration to
  run without dropping data, **so that** all player histories and world states are
  preserved.

- **US-33.2** — **As a** developer, **I want** a dry-run / validation mode for the
  migration, **so that** I can verify the backfill row counts match before the final
  commit.

- **US-33.3** — **As an** operator, **I want** the migration to be idempotent, **so
  that** I can re-run it safely if it was interrupted.

### Cross-Session Durability

- **US-33.4** — **As a** player, **I want** my universe's state to persist between
  sessions even if the server restarts, **so that** my story is not lost.

- **US-33.5** — **As a** developer, **I want** to retrieve the last durable universe
  snapshot for a session, **so that** I can reconstruct the Neo4j graph after a cold
  restart without replaying all turns.

---

## 4. Functional Requirements

### FR-33.01 — New PostgreSQL Tables

#### FR-33.01a: `universes` table

The migration MUST create the `universes` table with the following columns:

| Column | Type | Required | Notes |
|---|---|---|---|
| `universe_id` | TEXT | Yes | ULID, PK; 26-char format |
| `config` | JSONB | Yes | World parameters (migrated from `world_seed`) |
| `status` | TEXT | Yes | `created` / `active` / `paused` / `archived`; default `paused` |
| `created_at` | TIMESTAMPTZ | Yes | Defaults to `now()` |
| `updated_at` | TIMESTAMPTZ | Yes | Updated on status change |

No FK columns reference other tables. `universe_id` is the root of the v2 object graph.

The `status` default for backfilled rows is `paused` (because v1 sessions are all
historical — none are currently active).

#### FR-33.01b: `actors` table

The migration MUST create the `actors` table with the following columns:

| Column | Type | Required | Notes |
|---|---|---|---|
| `actor_id` | TEXT | Yes | ULID, PK; 26-char format |
| `player_id` | UUID | Yes | FK → `players.id` ON DELETE CASCADE; NOT NULL |
| `display_name` | TEXT | Yes | Copied from `players.handle` during backfill |
| `created_at` | TIMESTAMPTZ | Yes | Defaults to `now()` |

There is NO UNIQUE constraint on `actor_id, player_id` combination. (See S31
FR-31.01d.)

#### FR-33.01c: `character_states` table

The migration MUST create the `character_states` table with the following columns:

| Column | Type | Required | Notes |
|---|---|---|---|
| `actor_id` | TEXT | Yes | FK → `actors.actor_id` ON DELETE CASCADE; part of PK |
| `universe_id` | TEXT | Yes | FK → `universes.universe_id` ON DELETE CASCADE; part of PK |
| `character_name` | TEXT | Yes | In-world name; default `'Traveler'` for backfilled v1 rows |
| `traits` | JSONB | Yes | From S06; default `'{}'::jsonb` for v1 rows |
| `inventory` | JSONB | Yes | Default `'[]'::jsonb` for v1 rows |
| `conditions` | JSONB | Yes | Default `'[]'::jsonb` for v1 rows |
| `emotional_state` | JSONB | Yes | Default `'{}'::jsonb` for v1 rows |
| `reputation` | JSONB | Yes | Default `'{}'::jsonb` for v1 rows |
| `last_active_at` | TIMESTAMPTZ | Yes | From `game_sessions.updated_at` during backfill |

Primary key: `(actor_id, universe_id)` — enforces the S31 FR-31.02c uniqueness
constraint.

#### FR-33.01d: `universe_snapshots` table

The migration MUST create the `universe_snapshots` table with the following columns:

| Column | Type | Required | Notes |
|---|---|---|---|
| `id` | UUID | Yes | PK; `gen_random_uuid()` |
| `universe_id` | TEXT | Yes | FK → `universes.universe_id` ON DELETE CASCADE; NOT NULL |
| `session_id` | UUID | Yes | FK → `game_sessions.id` ON DELETE SET NULL; NOT NULL |
| `snapshot_type` | TEXT | Yes | `session_end` / `manual` / `checkpoint`; NOT NULL |
| `world_state` | JSONB | Yes | Full Neo4j graph export at snapshot time |
| `narrative_digest` | TEXT | No | Optional summary hash for integrity checking |
| `created_at` | TIMESTAMPTZ | Yes | Defaults to `now()` |

**Distinction from v1 `game_snapshots`**: `game_snapshots` is a per-turn, per-session
crash-recovery mechanism. `universe_snapshots` is a per-universe, per-session-boundary
durability record that captures the world graph state at the moment a session ends. It is
the source for cold-restart reconstruction and cross-session continuity.

Note: no `universe_snapshots` rows are created during the v1 → v2 migration. They begin
accumulating with v2 operation.

### FR-33.02 — Modifications to Existing Tables

#### FR-33.02a: `game_sessions.universe_id` column

The migration MUST add a `universe_id TEXT` column to `game_sessions`:

- Initially nullable (to allow online migration with backfill step).
- After backfill, a `NOT NULL` constraint is added in a subsequent migration step
  (or deferred to v2.1 online migration).
- FK: `REFERENCES universes(universe_id) ON DELETE SET NULL` (soft link — deleting a
  universe sets the session's universe_id to NULL rather than cascade-deleting old
  sessions).

#### FR-33.02b: `game_sessions.actors` column

The migration MUST add an `actors JSONB` column to `game_sessions`:

- Default: `'[]'::jsonb`
- Initially nullable for migration safety; `NOT NULL DEFAULT '[]'::jsonb` added after
  backfill.
- Backfilled for v1 sessions: `[{"actor_id": "<backfilled_actor_id>"}]` for each
  session's player.
- Content schema is defined by S30 FR-30.03.

#### FR-33.02c: `world_seed` column

The existing `game_sessions.world_seed` column MUST NOT be dropped or renamed. It is
preserved as a historical read-only column after migration. Its contents are copied to
`universes.config` during backfill.

### FR-33.03 — Backfill Logic

The backfill MUST execute in the following sequence within the migration:

**Step 1 — Create universes from game_sessions**

For each distinct `game_sessions` row (ordered by `created_at` ASC):

```
INSERT INTO universes (universe_id, config, status, created_at, updated_at)
SELECT
  gen_ulid(),                      -- new ULID per session
  world_seed,                      -- copy world_seed blob verbatim
  'paused',                        -- all historical universes are paused
  game_sessions.created_at,
  game_sessions.updated_at
FROM game_sessions
ORDER BY created_at ASC;
```

Because v1 had no concept of universe continuity, each `game_sessions` row gets a
distinct `universes` row. This is a 1:1 backfill.

**Step 2 — Backfill game_sessions.universe_id**

```
UPDATE game_sessions gs
SET universe_id = u.universe_id
FROM universes u
WHERE u.created_at = gs.created_at
  AND u.config::text = gs.world_seed::text;
```

Note: if two sessions have identical `world_seed` AND identical `created_at`, this
UPDATE could match the wrong universe row. The migration MUST add a stable surrogate
key to the join. See Appendix A for the recommended approach using a temporary mapping
table.

**Step 3 — Create one actor per player**

```
INSERT INTO actors (actor_id, player_id, display_name, created_at)
SELECT
  gen_ulid(),
  id,
  handle,
  created_at
FROM players
ORDER BY created_at ASC;
```

**Step 4 — Backfill game_sessions.actors JSONB**

```
UPDATE game_sessions gs
SET actors = jsonb_build_array(
  jsonb_build_object('actor_id', a.actor_id)
)
FROM actors a
WHERE a.player_id = gs.player_id;
```

**Step 5 — Create character_states for all historical sessions**

```
INSERT INTO character_states
  (actor_id, universe_id, character_name, traits, inventory,
   conditions, emotional_state, reputation, last_active_at)
SELECT
  a.actor_id,
  gs.universe_id,
  'Traveler',          -- default name; v1 had no character name concept
  '{}'::jsonb,
  '[]'::jsonb,
  '[]'::jsonb,
  '{}'::jsonb,
  '{}'::jsonb,
  gs.updated_at
FROM game_sessions gs
JOIN actors a ON a.player_id = gs.player_id
WHERE gs.universe_id IS NOT NULL;
```

The `character_states.traits` etc. are left empty for v1 rows because v1 did not persist
character state as a separate entity. The character state exists in the `game_snapshots`
blob; an optional v2.1 backfill job may extract and populate these fields from the last
snapshot per session.

### FR-33.04 — Neo4j Schema Additions

#### FR-33.04a: `universe_id` property and index on all world-scoped nodes

The Neo4j migration MUST add `universe_id` as an indexed property to the following node
types: `World`, `Location`, `NPC`, `Item`, `Region`, `Event`, `Quest`, `Connection`.

```cypher
CREATE INDEX location_universe_id IF NOT EXISTS
  FOR (l:Location) ON (l.universe_id);
-- (and similar for each node type)
```

#### FR-33.04b: Backfill `universe_id` via session_id bridge

The Neo4j backfill MUST set `universe_id` on all existing world-scoped nodes by joining
on `session_id`:

```cypher
// For each session, get its universe_id from PG (via application-layer bridge)
// and MATCH all nodes with that session_id:
MATCH (n)
WHERE n.session_id = $session_id
  AND (n:Location OR n:NPC OR n:Item OR n:Region OR n:Event OR n:Quest
       OR n:World OR n:Connection)
SET n.universe_id = $universe_id
```

This Cypher is run per-session via an application-layer migration script that reads
`(session_id → universe_id)` mappings from PostgreSQL after the PG backfill completes.

#### FR-33.04c: Add `universe_id` UNIQUE constraint on `World` node

```cypher
CREATE CONSTRAINT world_universe_id_unique IF NOT EXISTS
  FOR (w:World) REQUIRE w.universe_id IS UNIQUE;
```

Note: the existing `world_session_unique` constraint (`w.session_id IS UNIQUE`) is
preserved. Both constraints co-exist.

#### FR-33.04d: Cross-universe index on world-scoped nodes

```cypher
CREATE INDEX location_universe_id IF NOT EXISTS
  FOR (l:Location) ON (l.universe_id);
-- Allows "all Locations in universe X" queries required by S29 FR-29.07c.
```

### FR-33.05 — Migration Idempotency

- **FR-33.05a**: The migration MUST be idempotent. Re-running after partial failure
  MUST NOT create duplicate `universes`, `actors`, or `character_states` rows.
- **FR-33.05b**: Each step MUST use `INSERT ... ON CONFLICT DO NOTHING` or
  `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` guards.
- **FR-33.05c**: The migration MUST record its completion in the Alembic revision table.
  On re-run, Alembic's standard mechanism prevents double-execution.

### FR-33.06 — Migration Validation

- **FR-33.06a**: After migration, the system MUST validate:
  - `COUNT(universes)` ≥ `COUNT(game_sessions)` (each session has a universe)
  - `COUNT(actors)` = `COUNT(players)` (each player has exactly one actor)
  - `COUNT(character_states)` = `COUNT(game_sessions WHERE universe_id IS NOT NULL)`
  - `COUNT(game_sessions WHERE universe_id IS NULL)` = 0
- **FR-33.06b**: A post-migration validation script MUST be provided in
  `scripts/migrate_validate_v2.py` that runs these assertions and exits non-zero on
  failure.
- **FR-33.06c**: If validation fails, the migration is marked as failed and the operator
  is notified with the assertion that failed and the discrepancy count.

---

## 5. Non-Functional Requirements

- **NFR-33.A** — The migration MUST complete within 60 minutes on a v1 database with
  100 000 game sessions, running on a PostgreSQL 16 instance with 4 vCPUs and 16 GB
  RAM.
- **NFR-33.B** — The migration MUST NOT acquire table-level locks for more than 1
  second on `game_sessions`, `players`, or `turns` during online operation. All heavy
  steps MUST use `CREATE INDEX CONCURRENTLY` and backfill in batches of 1000 rows.
- **NFR-33.C** — Post-migration read latency for `universes` by `universe_id` MUST be
  ≤ 5 ms (p95) with the PK index.
- **NFR-33.D** — Post-migration read latency for `character_states` by
  `(actor_id, universe_id)` MUST be ≤ 10 ms (p95) with the composite PK index.
- **NFR-33.E** — The Neo4j `universe_id` backfill script MUST process nodes in batches
  of 500 per transaction to avoid memory pressure on Neo4j CE.

---

## 6. User Journeys

### Journey 1: Operator Runs v1 → v2 Migration

1. Operator runs `uv run alembic upgrade 011` (migration 011 is the v2 migration).
2. Alembic applies: create `universes`, `actors`, `character_states`,
   `universe_snapshots` tables; add `universe_id`, `actors` columns to `game_sessions`.
3. Backfill runs in batches: `universes` from `game_sessions`, `actors` from `players`,
   `character_states` from session/actor join.
4. Alembic marks revision 011 as applied.
5. Operator runs `uv run python scripts/migrate_validate_v2.py` — all assertions pass.
6. Operator runs the Neo4j backfill script:
   `uv run python scripts/migrate_neo4j_universe_id.py`
7. All Neo4j world nodes now carry `universe_id`.
8. Operator marks v2 migration as complete; application upgraded to v2 image.

### Journey 2: Application Cold-Restart After Session End

1. v2 session ends; S30 FR-30.04a triggers universe status → `paused`.
2. The session-end handler writes a `universe_snapshots` row with the full Neo4j
   world-state JSON.
3. Service restarts; Neo4j is empty (ephemeral container restart scenario).
4. On next session open, the turn pipeline detects missing Neo4j nodes for the universe.
5. System reads the latest `universe_snapshots` row for the universe.
6. Neo4j graph is reconstructed from the snapshot JSON.
7. Session resumes; player experiences no data loss.

---

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| EC-33.01 | Two v1 game_sessions have identical world_seed AND created_at | Migration uses temporary mapping table (see Appendix A) to avoid UUID collision in the session→universe join. Each session gets its own unique universe row. |
| EC-33.02 | A player was deleted before migration runs (CASCADE-deleted session rows) | No orphan sessions; backfill produces correct counts. `COUNT(actors)` = `COUNT(players)` at migration time (post-GDPR deletion). |
| EC-33.03 | Migration interrupted mid-backfill | Re-run after fix: `ON CONFLICT DO NOTHING` prevents duplicate inserts. Alembic does not re-apply the revision. Operator re-runs migration after fixing root cause. |
| EC-33.04 | Neo4j backfill script fails mid-run | Re-runnable: nodes already set with `universe_id` are skipped via `WHERE n.universe_id IS NULL`. Script logs completion count per batch. |
| EC-33.05 | universe_id FK on game_sessions is NULL after backfill | Validation script catches this. Root cause: session row that had no matching universe (orphan session). Operator resolves before marking migration complete. |
| EC-33.06 | game_snapshots.world_state referenced for character_state backfill | v2.0 leaves character fields empty (`{}`/`[]`); a separate optional v2.1 job extracts S06 fields from the last snapshot per session. |
| EC-33.07 | universe_snapshots table queried before first v2 session ends | Returns empty result set. Turn pipeline falls back to full Neo4j graph query (no snapshot available). |

---

## 8. Acceptance Criteria

```gherkin
Feature: Universe Persistence Schema Migration

  Scenario: AC-33.01 — Migration creates universes table and backfills from game_sessions
    Given a v1 database with N game_sessions rows
    When migration 011 is applied
    Then the universes table contains exactly N rows
    And each universes row has universe_id as a ULID
    And each universes row has config equal to the corresponding game_sessions.world_seed
    And all universes rows have status = 'paused'

  Scenario: AC-33.02 — Migration creates one actor per player
    Given a v1 database with M players rows
    When migration 011 is applied
    Then the actors table contains exactly M rows
    And each actor row has player_id matching a players row
    And each actor has a unique actor_id ULID

  Scenario: AC-33.03 — game_sessions.universe_id is backfilled for all sessions
    Given N game_sessions rows
    When migration 011 completes backfill
    Then game_sessions.universe_id is NOT NULL for all N rows
    And each universe_id references an existing universes row

  Scenario: AC-33.04 — character_states created for all historical sessions
    Given N game_sessions rows after universe_id backfill
    When character_state backfill runs
    Then character_states contains exactly N rows
    And each character_state has actor_id from the session's player's actor
    And each character_state has universe_id from the session's universe_id

  Scenario: AC-33.05 — Migration is idempotent
    Given migration 011 was partially applied (interrupted)
    When migration 011 is re-run
    Then no duplicate universes, actors, or character_states rows are created
    And the migration completes without error

  Scenario: AC-33.06 — world_seed column is preserved after migration
    Given a game_sessions row with world_seed = {"genre": "noir"}
    When migration 011 runs
    Then game_sessions.world_seed still equals {"genre": "noir"}
    And universes.config also equals {"genre": "noir"} for the corresponding universe

  Scenario: AC-33.07 — universe_snapshots table exists and accepts writes
    Given migration 011 applied
    When a universe_snapshots row is inserted with valid universe_id and session_id
    Then the insert succeeds
    And the row is retrievable by universe_id

  Scenario: AC-33.08 — Deleting a universe cascade-deletes its universe_snapshots
    Given a universe with 3 universe_snapshots rows
    When the universe is deleted
    Then all 3 universe_snapshots rows are deleted
    And the game_sessions rows referencing that universe have universe_id = NULL

  Scenario: AC-33.09 — Neo4j nodes have universe_id after backfill
    Given a Neo4j graph with World, Location, NPC nodes for session_id = S
    When the Neo4j backfill script runs for session S mapped to universe U
    Then all nodes with session_id = S have universe_id = U
    And the universe_id UNIQUE constraint on World nodes passes validation

  Scenario: AC-33.10 — Validation script passes after clean migration
    Given migration 011 applied successfully
    When scripts/migrate_validate_v2.py is run
    Then the script exits with code 0
    And all four row-count assertions pass
```

---

## 9. Dependencies & Integration Boundaries

| Dependency | Spec | Integration Notes |
|---|---|---|
| Universe entity definition | v2 S29 | The `universes` table schema follows S29 FR-29.01's data model. S33 implements it in DDL. |
| Actor identity definition | v2 S31 | The `actors` and `character_states` table schemas follow S31 FR-31.01–02. S33 implements them in DDL. |
| Session binding | v2 S30 | S30's `game_sessions.universe_id` and `.actors` columns are added by S33's migration DDL. |
| Persistence strategy | v1 S12 | `universe_snapshots` complements (not replaces) v1 `game_snapshots`. The turn pipeline uses both tables per S12 FR-12.18's session-end sequence. |
| World graph schema | v1 S13 | Neo4j node structure (World, Location, NPC, etc.) is governed by S13. S33 adds `universe_id` indexes; it does not alter node properties governed by S13. |
| GDPR deletion | v1 S17 | The migration's ON DELETE CASCADE chains (player→actor→character_state) satisfy S17's right-to-erasure requirement for the new tables. |
| Genesis v2 | v2 S40 | S40 uses the tables defined here to write character state after universe creation. S33's backfill leaves character fields empty (`{}`); S40 populates them for new universes. |
| Admin tooling | v1 S26 | S26 operators DELETE universes; the ON DELETE CASCADE chain here ensures clean removal. |

---

## 10. Open Questions

| # | Question | Impact | Owner |
|---|----------|--------|-------|
| OQ-33.01 | Should v1 character state be extracted from `game_snapshots.world_state` JSONB during backfill (v2.0) or deferred to a v2.1 job? The snapshot blob structure was not formally specified in v1, so extraction logic may be fragile. | FR-33.03 Step 5; `character_states.traits` backfill | v2.0 PM / S12 author |
| OQ-33.02 | Should `universe_snapshots.world_state` store the full Neo4j export (large, potentially > 1 MB per universe) or a normalized format with node/edge lists? Full export is simpler but may stress PostgreSQL JSONB. | FR-33.01d; cold-restart reconstruction performance | S13 author / S40 |
| OQ-33.03 | The NOT NULL constraint on `game_sessions.universe_id` is deferred to v2.1 to allow online migration. Confirm the v2.0 API accepts sessions with null universe_id (fallback behavior) or whether the app should refuse to serve until migration is confirmed complete. | FR-33.02a nullability | v2 tech lead |

---

## 11. Out of Scope

- **Turn pipeline integration** — how the turn pipeline reads/writes `CharacterState` or
  `universe_snapshots` during a live session is governed by S08 and S12.
- **Universe snapshot content format** — the schema of the JSON object stored in
  `universe_snapshots.world_state` is defined collaboratively by S13 (graph schema) and
  S40 (genesis/state format). S33 only specifies that the column exists and its type.
- **Cross-universe character state transfer** — governed by v4+ S51.
- **Performance tuning of Neo4j backfill script** — the batch size (500 per the NFR)
  is a recommendation. Actual tuning is operational, not spec-normative.
- **v2.1 character state extraction job** — extracting S06 fields from v1 snapshots
  is deferred post-v2.0. S33 only specifies the empty default for v1 rows.
- **Multi-tenant database isolation** — all tables use row-level isolation via FK
  constraints, not schema-level multi-tenancy.

---

## Changelog

- 2026-04-21: Initial draft. Authored by GitHub Copilot continuing from Claude Code
  rate-limited session. Based on roadmap §3.1 S33 summary, migration files 001–010,
  and Neo4j schema files 001–003.

---

## Appendix A — Recommended Backfill Approach (Mapping Table)

To avoid the edge case where two `game_sessions` rows have identical `world_seed` AND
`created_at`, the migration MUST use an explicit mapping table rather than a
content-join:

```sql
-- 1. Create temp mapping: session_id → new universe_id
CREATE TEMP TABLE _session_universe_map AS
SELECT
  gs.id AS session_id,
  gen_ulid()::text AS universe_id
FROM game_sessions gs;

-- 2. Insert universes using the mapping
INSERT INTO universes (universe_id, config, status, created_at, updated_at)
SELECT
  m.universe_id,
  gs.world_seed,
  'paused',
  gs.created_at,
  gs.updated_at
FROM _session_universe_map m
JOIN game_sessions gs ON gs.id = m.session_id
ON CONFLICT (universe_id) DO NOTHING;

-- 3. Backfill game_sessions using the mapping (never ambiguous)
UPDATE game_sessions gs
SET universe_id = m.universe_id
FROM _session_universe_map m
WHERE gs.id = m.session_id;
```

This approach guarantees a 1:1 mapping regardless of content collisions.

The `gen_ulid()` function must be registered in PostgreSQL before the migration runs.
A helper migration (011a) can create the function from the `pgulid` extension or an
embedded PL/pgSQL implementation.

---

## Appendix B — Schema Change Summary (v1 → v2)

| Object | Action | Notes |
|---|---|---|
| `universes` | **CREATE TABLE** | New root entity for S29 |
| `actors` | **CREATE TABLE** | New entity for S31 |
| `character_states` | **CREATE TABLE** | New entity for S31; PK is (actor_id, universe_id) |
| `universe_snapshots` | **CREATE TABLE** | Cross-session world durability; distinct from `game_snapshots` |
| `game_sessions.universe_id` | **ADD COLUMN** (TEXT, nullable → NOT NULL in v2.1) | FK → `universes.universe_id` ON DELETE SET NULL |
| `game_sessions.actors` | **ADD COLUMN** (JSONB, default `[]`) | Actor list per S30 FR-30.03 |
| `game_sessions.world_seed` | **PRESERVE** (read-only after migration) | Historical archive; not dropped |
| Neo4j `*.universe_id` | **ADD PROPERTY + INDEX** | All world-scoped nodes; backfilled via session_id bridge |
| Neo4j `World.universe_id` | **ADD UNIQUE CONSTRAINT** | `w.universe_id IS UNIQUE` (in addition to existing `w.session_id` constraint) |
