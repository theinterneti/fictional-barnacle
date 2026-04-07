# S12 — Persistence Strategy

> **Status**: 📝 Draft
> **Level**: 3 — Platform
> **Dependencies**: S04 (World Model), S13 (World Graph Schema)
> **Last Updated**: 2025-07-24

---

## 1. Purpose

This spec defines TTA's storage requirements and maps them to technology choices. It
answers: what data does TTA store, how is it accessed, what guarantees does it need, and
which storage engines satisfy those requirements?

**Requirements first, technology second.** Each section describes what the system needs
before prescribing how to achieve it. This ensures technology choices are justified by
requirements, not by habit.

---

## 2. Design Philosophy

### 2.1 Principles

- **Right tool for the right data**: no single database fits all access patterns. Use
  graph storage for graph data, relational storage for relational data, and caches for
  hot data.
- **Durability where it matters**: player progress must survive crashes. Cache misses are
  tolerable. The distinction must be explicit.
- **Simplicity at v1 scale**: TTA v1 targets hundreds of concurrent players, not millions.
  Optimize for developer experience and operational simplicity first.
- **Schema-driven**: all persistent data has a defined schema, even JSON blobs. No
  "throw it in a JSONB column and figure it out later."
- **Migration-ready**: every storage engine must support schema evolution without downtime
  for v1 scale.

### 2.2 Anti-Patterns to Avoid

- Storing relational data in a graph database (player profiles, auth credentials)
- Using the graph database as a key-value store
- Treating Redis as a durable store
- Storing session conversation history only in cache
- Coupling application logic to database-specific query syntax

---

## 3. User Stories

> **US-12.1** — As a player, my game progress is saved automatically so I never lose
> work due to a server restart or crash.

> **US-12.2** — As a player, when I resume a paused game, the experience is seamless —
> the world remembers where I was and what I was doing.

> **US-12.3** — As a developer, I can understand which database stores which data by
> reading a single document, and the mapping is consistent.

> **US-12.4** — As an operator, I can back up all player data and restore it in the event
> of a catastrophic failure.

> **US-12.5** — As a developer, I can evolve the database schema without taking the
> service offline.

> **US-12.6** — As a player on a slow connection, the game still responds quickly because
> hot data is served from cache, not disk.

---

## 4. Data Categories

### 4.1 Overview

| Category | Examples | Nature | Durability |
|----------|----------|--------|------------|
| **World Graph** | Locations, NPCs, items, connections | Graph/relational | Durable — defines the game world |
| **Player Data** | Profiles, preferences, credentials | Relational | Durable — GDPR-regulated |
| **Session Data** | Turn history, game metadata | Relational | Durable — player's progress |
| **Game State** | Current location, inventory, NPC states | Structured | Hot cache + durable snapshot |
| **System Data** | Prompts, config, content assets | Relational/file | Durable — defines system behavior |
| **Ephemeral Data** | SSE buffers, turn locks, rate limits | Key-value | Ephemeral — can be lost |

### 4.2 World Graph Data

**What:** The static and dynamic structure of the game world — locations, NPCs, items,
events, and the connections between them. This is the data that makes "what's near the
player?" and "who knows about this item?" answerable.

**Requirements:**
- REQ-12.01: MUST support graph traversal queries (e.g., "find all locations reachable
  from here within 2 hops").
- REQ-12.02: MUST support property queries on nodes and relationships (e.g., "find all
  NPCs in this location who are friendly").
- REQ-12.03: MUST support efficient neighborhood queries (a node and its immediate
  connections).
- REQ-12.04: MUST support schema-defined node types and relationship types (see S13).
- REQ-12.05: MUST support atomic mutations (add/remove nodes, update properties) within
  a transaction.
- REQ-12.06: World graph reads during gameplay MUST complete within 50ms for single-hop
  queries and 200ms for multi-hop queries (up to 3 hops).

**Access patterns:**
- Read-heavy during gameplay (10:1 read-to-write ratio)
- Writes happen on world state changes (NPC movement, item pickup, event triggers)
- Bulk writes happen during world initialization (Genesis seed data)
- Traversal queries are the primary read pattern

### 4.3 Player Data

**What:** Player identity, authentication credentials, profiles, and preferences.
Relational data with well-defined schemas and foreign key relationships.

**Requirements:**
- REQ-12.07: MUST support standard relational queries (filter, sort, paginate).
- REQ-12.08: MUST enforce uniqueness constraints (e.g., email).
- REQ-12.09: MUST support foreign key relationships (player → games).
- REQ-12.10: MUST support efficient single-record lookups by primary key and by email.
- REQ-12.11: MUST support GDPR deletion (complete erasure of a player's PII).
- REQ-12.12: Player lookups MUST complete within 10ms.

**Access patterns:**
- Single-record reads (login, profile fetch)
- Single-record writes (profile update, preference change)
- Rare bulk reads (admin: list players)
- Writes are infrequent relative to reads

### 4.4 Session / Game Data

**What:** Game session metadata and the full turn-by-turn conversation history. This is
the player's progress — the record of what happened.

**Requirements:**
- REQ-12.13: MUST support ordered retrieval of turns within a game (by turn number).
- REQ-12.14: MUST support efficient "recent turns" queries (last N turns for context).
- REQ-12.15: MUST support game listing with filtering (by status, by player).
- REQ-12.16: MUST store the full narrative response for every turn (not just references).
- REQ-12.17: Turn history MUST survive server restarts and crashes.
- REQ-12.18: Recent turns query (last 10) MUST complete within 20ms.

**Access patterns:**
- Append-heavy for turns (write once, read many)
- Single-record reads for game metadata
- Range reads for turn history (last N turns)
- Status-filtered listing for game management

### 4.5 Game State (Hot State)

**What:** The player's current position in the game world: location, inventory, active
NPC states, conversation context window. This is the data the AI pipeline reads on every
turn.

**Requirements:**
- REQ-12.19: MUST be readable in under 5ms during turn processing.
- REQ-12.20: MUST be writable atomically after each turn completes.
- REQ-12.21: MUST survive short outages (Redis restart) by being reconstructible from
  durable stores.
- REQ-12.22: MUST support TTL-based expiration (games that go idle should release cache).
- REQ-12.23: A durable snapshot of game state MUST be stored after every turn for
  crash recovery.

**Access patterns:**
- Read on every turn (hot path)
- Write after every turn (hot path)
- Expire after inactivity
- Reconstruct from SQL + Neo4j on cache miss

### 4.6 System Data

**What:** AI prompt templates, system configuration, content assets (world definitions,
narrative templates), feature flags.

**Requirements:**
- REQ-12.24: MUST support versioned retrieval (which version of this prompt is active?).
- REQ-12.25: MUST support efficient single-record lookup by key.
- REQ-12.26: Configuration changes MUST be picked up without service restart (hot reload
  from cache or polling).
- REQ-12.27: Prompt templates MUST be stored with their version history for audit.

**Access patterns:**
- Read-heavy, write-rare (prompts change infrequently)
- Cached aggressively (read once, serve from memory/cache)
- Bulk-loaded at startup or on configuration change

### 4.7 Ephemeral Data

**What:** SSE event buffers, turn processing locks, rate limit counters, auth token
deny-lists. Data that serves an operational purpose but can be lost without harm beyond
temporary disruption.

**Requirements:**
- REQ-12.28: MUST support key-value read/write in under 1ms.
- REQ-12.29: MUST support TTL-based automatic expiration.
- REQ-12.30: MUST support atomic increment (rate limit counters).
- REQ-12.31: MUST support pub/sub (for SSE event distribution).
- REQ-12.32: Data loss due to cache restart is acceptable; the system MUST recover
  gracefully (clients reconnect, locks are re-acquirable, rate limit counters reset).

**Access patterns:**
- High-frequency read/write (on every request)
- Short-lived data (seconds to hours)
- Pub/sub for real-time event distribution

---

## 5. Consistency Requirements

| Data Category | Consistency Model | Rationale |
|--------------|-------------------|-----------|
| Player credentials | Strong | Cannot serve stale password hashes |
| Player profile | Strong | Player sees own changes immediately |
| Game session metadata | Strong | State transitions must be authoritative |
| Turn history | Strong (per-game) | Turns are sequential and ordered |
| Game state (cache) | Eventual | Cache miss falls back to durable source |
| World graph (static) | Read-committed | Static structure rarely changes |
| World graph (dynamic) | Strong (per-transaction) | Mutations must be atomic |
| Ephemeral data | Best-effort | Acceptable to lose on restart |

- FR-12.01: All writes to SQL MUST use transactions to ensure atomicity.
- FR-12.02: Game state writes MUST follow write-through caching: write to SQL first, then
  update Redis. On failure, the cache entry MUST be invalidated.
- FR-12.03: World graph mutations MUST be executed within Neo4j transactions.

---

## 6. Durability Requirements

### 6.1 What MUST Survive a Crash

| Data | Recovery Method |
|------|----------------|
| Player accounts and credentials | SQL database (WAL + backups) |
| Game session metadata | SQL database |
| Turn history | SQL database |
| Game state snapshots | SQL database (JSON column per turn) |
| World graph structure | Neo4j (transaction log + backups) |
| AI prompt templates | SQL database + version control |

### 6.2 What CAN Be Rebuilt After a Crash

| Data | Rebuild Method |
|------|---------------|
| Hot game state (Redis) | Reconstruct from latest SQL snapshot + world graph |
| SSE event buffers | Lost; client reconnects and fetches state |
| Rate limit counters | Reset to zero; acceptable |
| Turn processing locks | Expire naturally via TTL |
| Auth token deny-list | Lost; affected tokens may be usable until natural expiry |

- FR-12.04: After a Redis restart, the first access to a game session MUST transparently
  reconstruct the hot state from SQL and Neo4j, with latency under 500ms.
- FR-12.05: The system MUST log a warning when cache reconstruction occurs, for
  operational monitoring.

---

## 7. Performance Requirements

### 7.1 Latency Targets (p95)

| Operation | Target | Storage |
|-----------|--------|---------|
| Player login (credential lookup) | < 50ms | SQL |
| Game state read (cache hit) | < 5ms | Redis |
| Game state read (cache miss) | < 500ms | SQL + Neo4j → Redis |
| Turn history read (last 10) | < 20ms | SQL |
| World graph single-hop query | < 50ms | Neo4j |
| World graph multi-hop query (≤3) | < 200ms | Neo4j |
| Turn state write (cache + SQL) | < 100ms | Redis + SQL |
| Rate limit check | < 1ms | Redis |
| SSE event buffer read | < 5ms | Redis |

### 7.2 Throughput Targets (v1)

| Metric | Target |
|--------|--------|
| Concurrent active games | 500 |
| Turns per second (system-wide) | 50 |
| Concurrent SSE connections | 1000 |
| Player registrations per hour | 100 |

These are v1 targets for a single-server deployment. Horizontal scaling is out of scope
but the architecture should not preclude it.

---

## 8. Scale Requirements (v1)

| Dimension | v1 Target | Notes |
|-----------|-----------|-------|
| Total registered players | 10,000 | Over the first year |
| Concurrent players | 200 | Peak |
| Active games | 500 | Games in `active` or `paused` state |
| Turns per game | 500 average | Wide variance expected |
| Total turns stored | 2,500,000 | 10K players × 500 turns × some games |
| World graph nodes | 10,000 | Across all worlds |
| World graph relationships | 50,000 | ~5 relationships per node |
| Redis memory | < 1 GB | Hot state + ephemeral data |
| SQL database size | < 10 GB | Player data + turn history |
| Neo4j database size | < 1 GB | World graph |

---

## 9. Technology Mapping

### 9.1 Decision Matrix

| Requirement | Graph DB (Neo4j) | Relational DB (SQLite/PostgreSQL) | Cache (Redis) |
|------------|------------------|----------------------------------|---------------|
| Graph traversal | ✅ Primary | ❌ Poor fit | ❌ Not applicable |
| Relational queries | ❌ Awkward | ✅ Primary | ❌ Not applicable |
| Key-value lookup | ❌ Overkill | ✅ Adequate | ✅ Fastest |
| TTL expiration | ❌ No native | ❌ Requires cron/trigger | ✅ Native |
| Pub/sub | ❌ No | ❌ LISTEN/NOTIFY (Postgres only) | ✅ Native |
| ACID transactions | ✅ Yes | ✅ Yes | ⚠️ Limited (MULTI/EXEC) |
| GDPR deletion | ❌ Manual graph cleanup | ✅ CASCADE delete | ✅ DEL key |
| Schema migration | ⚠️ Manual Cypher | ✅ Alembic/migration tools | N/A |

### 9.2 Final Mapping

| Data Category | Primary Store | Cache Layer | Rationale |
|--------------|---------------|-------------|-----------|
| **World Graph** | Neo4j | Redis (optional) | Graph traversal is the dominant access pattern |
| **Player Data** | SQL (SQLModel) | — | Relational data with constraints and GDPR |
| **Session Metadata** | SQL (SQLModel) | — | Relational, needs FK to players |
| **Turn History** | SQL (SQLModel) | — | Append-only, ordered, relational |
| **Game State (hot)** | Redis | — | Sub-5ms reads on the hot path |
| **Game State (durable)** | SQL (JSON column) | — | Crash recovery; snapshot per turn |
| **System Config** | SQL (SQLModel) | Redis | Write-rare, read-often |
| **Prompt Templates** | SQL (SQLModel) | Redis | Versioned, cached aggressively |
| **Ephemeral** | Redis | — | TTL, pub/sub, counters |

### 9.3 SQL Engine Choice

For v1, the SQL layer uses **SQLModel** (Pydantic + SQLAlchemy), which supports both
SQLite (development/testing) and PostgreSQL (production).

- FR-12.06: The application MUST be runnable with SQLite for local development and
  testing.
- FR-12.07: The production deployment MUST use PostgreSQL for durability and concurrent
  access guarantees.
- FR-12.08: Application code MUST NOT use database-specific SQL syntax. All queries MUST
  go through SQLModel/SQLAlchemy ORM.
- FR-12.09: The migration tool MUST be Alembic (integrated with SQLAlchemy).

### 9.4 Redis Configuration

- FR-12.10: Redis MUST be configured with `maxmemory-policy allkeys-lru` to handle
  memory pressure gracefully.
- FR-12.11: Redis persistence (RDB/AOF) SHOULD be enabled in production for faster
  restart recovery, but the system MUST NOT depend on it.
- FR-12.12: All Redis keys MUST use a namespaced prefix: `tta:{category}:{id}`
  (e.g., `tta:session:abc123`, `tta:ratelimit:player:def456`).
- FR-12.13: All Redis keys with dynamic data MUST have a TTL set at write time.

### 9.5 Neo4j Configuration

- FR-12.14: Neo4j MUST be configured in single-instance mode for v1 (no clustering).
- FR-12.15: The Neo4j schema MUST be defined in a migration script that is idempotent
  (safe to re-run).
- FR-12.16: All Neo4j queries MUST use parameterized Cypher (no string interpolation).
- FR-12.17: Neo4j indexes MUST be created for all properties used in MATCH/WHERE clauses
  (see S13).

---

## 10. Data Flow: Turn Processing

This section traces how data flows through storage during a single turn, the most
performance-critical operation.

```
Player submits turn
    │
    ├─ 1. Validate auth token                        [Redis: deny-list check]
    ├─ 2. Check rate limit                            [Redis: increment counter]
    ├─ 3. Acquire turn lock                           [Redis: SET NX with TTL]
    ├─ 4. Read hot game state                         [Redis: GET session:{id}]
    │     └─ (cache miss? Reconstruct from SQL+Neo4j)
    ├─ 5. Read world context (nearby locations, NPCs) [Neo4j: graph traversal]
    ├─ 6. Read recent turn history (context window)   [SQL: last N turns]
    │
    ├─ [AI Pipeline processes turn — out of scope for this spec]
    │
    ├─ 7. Write turn record                           [SQL: INSERT turn]
    ├─ 8. Write game state snapshot                    [SQL: UPDATE game state]
    ├─ 9. Update hot game state                       [Redis: SET session:{id}]
    ├─10. Update world graph if needed                [Neo4j: Cypher mutations]
    ├─11. Publish SSE events                          [Redis: PUBLISH + buffer]
    └─12. Release turn lock                           [Redis: DEL lock]
```

- FR-12.18: Steps 7–10 MUST be executed within a coordinated transaction. If the SQL
  write fails, the Redis cache and Neo4j MUST NOT be updated.
- FR-12.19: If the Redis cache update (step 9) fails after SQL success, the cache entry
  MUST be invalidated so the next read triggers reconstruction.
- FR-12.20: The turn lock (step 3) MUST have a TTL of 120 seconds to prevent deadlocks
  if the server crashes mid-turn.

---

## 11. Migration Strategy

### 11.1 SQL Migrations

- FR-12.21: All SQL schema changes MUST be managed via Alembic migration scripts.
- FR-12.22: Each migration MUST be reversible (include both `upgrade` and `downgrade`).
- FR-12.23: Migrations MUST be tested in CI before deployment.
- FR-12.24: Zero-downtime migrations are not required for v1 but the migration design
  SHOULD avoid locking entire tables.

### 11.2 Neo4j Migrations

- FR-12.25: Neo4j schema changes (new labels, new relationship types, new indexes) MUST
  be managed via versioned Cypher scripts.
- FR-12.26: Each script MUST be idempotent (safe to run multiple times).
- FR-12.27: A migration version tracker (e.g., a `SchemaMigration` node in Neo4j or a
  row in SQL) MUST record which migrations have been applied.

### 11.3 Redis Key Versioning

- FR-12.28: If the structure of cached data changes, the key prefix MUST be versioned
  (e.g., `tta:v2:session:{id}`).
- FR-12.29: Old-version keys MUST be allowed to expire naturally; no bulk migration.

---

## 12. Backup & Recovery

### 12.1 Backup Requirements

- FR-12.30: SQL database MUST be backed up daily with point-in-time recovery capability
  for the last 7 days.
- FR-12.31: Neo4j MUST be backed up daily.
- FR-12.32: Redis DOES NOT need backups (all data is reconstructible or ephemeral).
- FR-12.33: Backup integrity MUST be verified via automated restore tests at least
  monthly.

### 12.2 Recovery Time Objectives

| Scenario | RTO | RPO |
|----------|-----|-----|
| Redis restart | < 1 minute | 0 (reconstructible) |
| SQL database restore | < 1 hour | < 1 hour (WAL) |
| Neo4j restore | < 1 hour | < 24 hours (daily backup) |
| Full disaster recovery | < 4 hours | < 1 hour (SQL), < 24 hours (Neo4j) |

### 12.3 Recovery Procedures

- FR-12.34: Recovery procedures MUST be documented as runbooks, not just spec text.
- FR-12.35: Recovery MUST be testable in a staging environment.

---

## 13. Acceptance Criteria

### Data Integrity

- AC-12.01: A turn submitted by a player is retrievable from the turn history after a
  server restart.
- AC-12.02: After Redis is restarted, the next turn for any game completes successfully
  (cache reconstruction works transparently).
- AC-12.03: A GDPR deletion request removes all PII from SQL within 72 hours, verified
  by a direct database query.
- AC-12.04: Game state after 100 turns matches the accumulated effect of all 100 turn
  snapshots (no state drift).

### Performance

- AC-12.05: Game state read from Redis cache completes in under 5ms (p95).
- AC-12.06: Cache miss reconstruction from SQL + Neo4j completes in under 500ms (p95).
- AC-12.07: Turn processing (all storage operations, excluding AI) completes in under
  200ms (p95).
- AC-12.08: World graph traversal (2-hop) completes in under 200ms (p95).

### Migration

- AC-12.09: A new SQL migration can be applied to the production database without manual
  intervention beyond running the migration command.
- AC-12.10: A Neo4j migration script can be run on a database that already has the schema,
  without errors or side effects (idempotency).

### Operational

- AC-12.11: An operator can restore the SQL database from backup and have the service
  functional within 1 hour.
- AC-12.12: All Redis keys have a TTL set (no unbounded memory growth). Verified by
  monitoring.

---

## 14. Edge Cases

- EC-12.01: A player's game state is in Redis but the corresponding SQL snapshot is
  missing (data corruption). The system MUST detect the inconsistency and log an error;
  the game MUST be transitioned to an error state rather than serving stale data.

- EC-12.02: Neo4j is temporarily unreachable during a turn. The turn MUST fail with a
  clear error to the player ("World temporarily unavailable, please try again"). The
  system MUST NOT write partial state to SQL.

- EC-12.03: Two servers attempt to process the same turn concurrently (in a future
  multi-instance deployment). The Redis turn lock MUST prevent double-processing.

- EC-12.04: A player's turn record exceeds the expected size (very long AI response). The
  SQL schema MUST use a text column (unbounded) for narrative responses, not a
  varchar with a limit.

- EC-12.05: Redis memory reaches the configured limit. The `allkeys-lru` policy evicts
  the least-recently-used keys. The system MUST handle cache misses gracefully.

---

## 15. Open Questions

- OQ-12.01: Should game state snapshots be stored as full snapshots or diffs? Full
  snapshots are simpler but use more storage. At v1 scale, full snapshots are fine.
  Revisit at scale.

- OQ-12.02: Should we use Redis Streams instead of Pub/Sub for SSE event distribution?
  Streams offer persistence and consumer groups. Worth exploring but Pub/Sub is simpler
  for v1.

- OQ-12.03: Should prompt templates be stored in the database or in version-controlled
  files loaded at startup? Database is more dynamic; files are simpler. Current lean:
  database with version history, seeded from files.

- OQ-12.04: For SQLite in development — should we use a single file or in-memory? Single
  file for persistence across restarts; in-memory for faster tests. Both should be
  supported via configuration.

- OQ-12.05: Should the game state JSON snapshot in SQL be compressed? At v1 scale, no.
  Monitor size and revisit.
