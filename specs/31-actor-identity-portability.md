# S31 — Actor Identity Portability

> **Status**: ✅ Approved
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 3 — Platform
> **Dependencies**: v2 S29, v1 S06, v1 S11
> **Last Updated**: 2026-04-21

---

## 1. Purpose

In v1, the player character was implicitly coupled to a session. Character state was
stored in `game_snapshots` as part of the per-turn world blob — there was no independent
identity for "the player's in-world self." A player was their character, and their
character was their session.

v2 separates two concepts that v1 conflated:

- **Actor**: the player's in-world persona — a stable, globally unique entity with its
  own identity record. An actor exists independently of any universe or session.
- **Character state**: the universe-scoped attributes that represent *how the actor
  exists in a particular universe* — traits, reputation, inventory, conditions, and
  relationships that evolved through play.

This separation is the minimum footwork required to enable S51 (Cross-Universe Travel)
in v4+: when an actor travels between universes, the actor identity is preserved while
the character state is transferred, reset, or translated per rules defined in S51.

v2 constraint: in v2, each player has exactly one actor, and each actor exists in at
most one universe at a time. The data model does **not** enforce this — it is
deliberately designed to accommodate v4+, where one actor may have character states in
multiple universes simultaneously (multi-universe residency).

This spec **extends** v1 S06 (Character System) by introducing the Actor identity layer.
v1 S06's character state fields (traits, inventory, conditions, emotional state,
reputation, relationships) become the content of `CharacterState` in v2. S06 remains the
authority on what those fields *mean*; S31 governs *where* they are stored and *how* the
actor-universe separation is maintained.

---

## 2. Design Philosophy

**Identity is universe-agnostic**: `actor_id` is stable regardless of which universe
is being queried. The same actor can exist across many universes; the actor identity
record itself carries no universe reference.

**State is universe-scoped**: character state is a function of (actor, universe). The
same actor may be a revered scholar in Universe A and a hunted fugitive in Universe B.
These are distinct `CharacterState` records, not variants of a single record.

**One-way linkage**: `CharacterState` references both `actor_id` and `universe_id`, but
neither `Actor` nor `Universe` references `CharacterState` directly. This prevents
circular schema dependencies and preserves clean deletion cascades.

**v2 simplification without v4+ lock-in**: one actor per player is enforced at
application level; the schema carries no such constraint. Adding a second actor per
player in v4+ is an additive migration.

---

## 3. User Stories

### Identity & Portability

- **US-31.1** — **As a** player, **I want** my actor identity to be stable across all
  my universes, **so that** I know I'm "the same traveler" even when my characters have
  diverged between worlds.

- **US-31.2** — **As a** player, **I want** my character's state (traits, reputation,
  inventory) to reflect my play in this specific universe, **so that** each universe
  feels like a distinct experience, not a copy.

### Developer & Operator

- **US-31.3** — **As a** developer, **I want** to look up all character states for a
  given actor across all universes, **so that** I can support export, backup, and
  cross-universe transfer (S51) without full-table scans.

- **US-31.4** — **As a** developer, **I want** to look up all actors currently present
  in a given universe, **so that** I can support multi-actor worlds in v4+ without
  schema migration.

- **US-31.5** — **As an** operator, **I want** deleting an actor to cascade-delete all
  character states for that actor, **so that** no orphan state records exist after a
  player account deletion.

---

## 4. Functional Requirements

### FR-31.01 — Actor Identity Record

- **FR-31.01a**: Every player MUST have an `Actor` record with the following fields:

  | Field | Type | Required | Notes |
  |---|---|---|---|
  | `actor_id` | ULID | Yes | Globally unique; assigned at creation |
  | `player_id` | UUID FK | Yes | References `players.id`; NOT NULL |
  | `display_name` | String | Yes | Cross-universe handle; may differ from in-world character name |
  | `created_at` | Timestamp | Yes | When the actor record was created |

- **FR-31.01b**: `actor_id` MUST be a ULID (Universally Unique Lexicographically
  Sortable Identifier), independent of and not derived from `player_id`.
- **FR-31.01c**: In v2, the system MUST ensure exactly one `Actor` record per player.
  Creation occurs either at player registration (for new players) or lazily at first
  universe bind (for v1 players predating v2 and for any player whose actor row is
  absent). Both paths MUST flow through an idempotent `ActorService.get_or_create_for_player()`
  call. If actor creation fails at registration time, player registration MUST be
  rolled back entirely; if it fails during a lazy-create at bind time, the bind
  attempt MUST fail with `actor_not_available` and the session MUST NOT be created.
- **FR-31.01d**: The database schema MUST NOT enforce a uniqueness constraint on
  `actors.player_id`. The v2 "one actor per player" policy is enforced at application
  level only. (v4+ allows multiple actors per player without schema migration.)
- **FR-31.01e**: `actor_id` is immutable after creation. `display_name` and `player_id`
  are also immutable. No update path for actor records exists in v2.

### FR-31.02 — Character State Record

- **FR-31.02a**: Every actor that has participated in a universe MUST have at most one
  `CharacterState` record per (actor_id, universe_id) pair.

- **FR-31.02b**: A `CharacterState` record MUST carry the following fields:

  | Field | Type | Required | Notes |
  |---|---|---|---|
  | `id` | ULID | Yes | Surrogate PK. ULID-formatted. |
  | `actor_id` | ULID FK | Yes | References `actors.actor_id` |
  | `universe_id` | ULID FK (TEXT) | Yes | References `universes.universe_id` |
  | `character_name` | String | Yes | In-world name in this universe; may differ from `actor.display_name` |
  | `traits` | JSONB | Yes | From S06 FR-1.1; evolves through play |
  | `inventory` | JSONB | Yes | From S06 FR-1.1 |
  | `conditions` | JSONB | Yes | From S06 FR-1.1 (active states: injured, cursed, etc.) |
  | `emotional_state` | JSONB | Yes | From S06 FR-1.1 |
  | `reputation` | JSONB | Yes | From S06 FR-1.1 |
  | `relationships` | JSONB | Yes | `{npc_id: RelationshipDimensions}`; used by S38 NPC social layer |
  | `last_active_at` | Timestamp | Yes | When this CharacterState was last updated |

  The content structure of `traits`, `inventory`, `conditions`, `emotional_state`,
  `reputation`, and `relationships` is governed by v1 S06 and v2 S38. S31 governs where
  they are stored, not what they contain.

- **FR-31.02c**: Primary key is the surrogate ULID `id`. The pair `(actor_id,
  universe_id)` MUST be enforced by a database UNIQUE constraint. (Unlike the
  session↔universe binding in S30, this IS a hard uniqueness constraint — one
  character state per actor per universe is always true, regardless of the number of
  sessions that have occurred in that universe.) The surrogate PK preserves forward
  compatibility with v4+ multi-identity extensions that may add additional identity
  dimensions without requiring a primary-key migration.
- **FR-31.02d**: `CharacterState` is created lazily at the start of the actor's first
  session in a given universe. It is NOT created at actor registration time.
- **FR-31.02e**: `CharacterState` is updated after each turn completes. The turn
  pipeline writes the updated character state as part of the per-turn persistence cycle
  (S12 FR-12.18 sequence, step 8).
- **FR-31.02f**: `CharacterState` is NOT created for a universe in `archived` status.
  Attempting to open a session in an archived universe is rejected before character state
  creation is reached (S30 FR-30.02b).

### FR-31.03 — Separation Invariant

- **FR-31.03a**: No `Actor` record MUST carry a `universe_id` field. Actor identity is
  universe-agnostic.
- **FR-31.03b**: No `Universe` record MUST carry an `actor_id` field. Universe identity
  is actor-agnostic.
- **FR-31.03c**: The linkage between actors and universes MUST be expressed exclusively
  through: (1) `CharacterState(actor_id, universe_id)` for character data, and (2) the
  `actors` JSONB field on `game_sessions` for session-participation data.
- **FR-31.03d**: The turn pipeline MUST always reference character state via
  `(actor_id, universe_id)` — never via a session-scoped query alone. This ensures
  the character state is portable even if session IDs change between sessions.

### FR-31.04 — Actor and Character State Lookup

- **FR-31.04a**: The system MUST support lookup of an actor by `actor_id` (indexed).
- **FR-31.04b**: The system MUST support lookup of the actor(s) belonging to a given
  `player_id` (indexed on `actors.player_id`).
- **FR-31.04c**: The system MUST support lookup of all `CharacterState` records for a
  given `actor_id`, across all universes (indexed on `character_states.actor_id`).
- **FR-31.04d**: The system MUST support lookup of the single `CharacterState` for a
  given `(actor_id, universe_id)` pair (composite index, unique).
- **FR-31.04e**: The system MUST support lookup of all `CharacterState` records for a
  given `universe_id`, across all actors (indexed on `character_states.universe_id`).
  This query supports multi-actor universe loading in v4+.

### FR-31.05 — Deletion Cascades

- **FR-31.05a**: Deleting a player (S11 FR-11.60 GDPR path) MUST cascade-delete all
  `Actor` records for that player.
- **FR-31.05b**: Deleting an actor MUST cascade-delete all `CharacterState` records for
  that actor.
- **FR-31.05c**: Deleting a universe (operator action, S26) MUST cascade-delete all
  `CharacterState` records for that universe. `Actor` records are NOT deleted — the
  actor exists independently and may have character states in other universes.
- **FR-31.05d**: Deletion cascades MUST be enforced by database-level `ON DELETE
  CASCADE` foreign key constraints, not application-level cascade logic.

---

## 5. Non-Functional Requirements

- **NFR-31.A** — Actor lookup by `actor_id` MUST complete within 10 ms (p95), B-tree
  indexed primary key query.
- **NFR-31.B** — `CharacterState` lookup by `(actor_id, universe_id)` MUST complete
  within 10 ms (p95), composite unique index query.
- **NFR-31.C** — All `CharacterState` records for a given actor (cross-universe index)
  MUST be retrievable in under 50 ms for a player with up to 100 universes.
- **NFR-31.D** — Actor creation as part of player registration MUST add no more than
  50 ms to registration latency (p95).

---

## 6. User Journeys

### Journey 1: Player Registers — Actor Created Automatically

**Trigger**: `POST /api/v1/auth/register`

1. Player registration creates a `players` row.
2. Within the same transaction, a `actors` row is created:
   `actor_id = new_ulid()`, `player_id = new_player.id`,
   `display_name = player.handle` (or player-chosen name at registration).
3. Transaction commits; player and actor are created atomically.
4. JWT contains `player_id`; `actor_id` is retrievable via `GET /api/v1/me/actor`.

### Journey 2: Player Opens First Session in Universe X — CharacterState Created

**Trigger**: Session created (S30) for the actor's first time in Universe X.

1. Session creation (S30) completes; session row has `actors = ["actor_01..."]`.
2. System checks: does `CharacterState(actor_id="actor_01...", universe_id=X)` exist?
3. It does not. System creates `CharacterState` with default empty fields.
4. Genesis flow (S40) populates `character_name`, initial `traits`, etc.
5. `CharacterState` is updated with genesis output.

### Journey 3: Player Resumes Universe X in a New Session — CharacterState Reused

**Trigger**: Player opens second session in Universe X (previous session `ended`).

1. Session creation (S30) succeeds; universe transitions from `paused` to `active`.
2. System checks: does `CharacterState(actor_id="actor_01...", universe_id=X)` exist?
3. It does. System loads existing `CharacterState` from DB into hot cache.
4. The player resumes exactly where they left off in terms of character state.
5. No new `CharacterState` row is created.

### Journey 4: Developer Queries Actor's Cross-Universe History

**Trigger**: `GET /api/v1/actors/{actor_id}/character-states`

1. System retrieves all `CharacterState` records for `actor_id`.
2. Response includes: for each universe — `universe_id`, `character_name`,
   `traits`, `last_active_at`.
3. Developer can compare how the actor evolved across their parallel universes.

---

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| EC-31.01 | Actor creation fails at registration | Player registration rolls back entirely. Both player and actor rows are absent. |
| EC-31.02 | `CharacterState` creation fails at first session open | Session creation fails; no orphan session row. `CharacterState` is also absent. |
| EC-31.03 | Duplicate `CharacterState` creation attempt (race or retry) | DB UNIQUE constraint on `(actor_id, universe_id)` rejects the duplicate. System returns existing `CharacterState` (idempotent). |
| EC-31.04 | Actor referenced in `game_sessions.actors` but actor record deleted | Integrity violation: `actor_not_found`. Operator action required. |
| EC-31.05 | Player deleted (GDPR) — cascades | All actor records deleted; all `CharacterState` records for each actor deleted. `game_sessions.actors` JSONB is not FK-constrained (JSONB array); clean-up verified by GDPR job (S17). |
| EC-31.06 | v1 player with no actor record | The S33 migration (FR-33.03 Step 3) backfills one actor row per existing player at upgrade time. If an actor row is nonetheless absent for a given player — e.g. registrations that race the migration, a partial re-run, or greenfield deployments where the backfill steps are not applicable — `ActorService.get_or_create_for_player()` creates the row lazily and idempotently on first access. Both the eager migration path and the lazy service-layer path MUST produce identical actor records for the same `player_id`. |
| EC-31.07 | Two universes share the same actor's CharacterState (impossible by unique constraint) | Cannot occur. If detected, constitutes DB corruption. |

---

## 8. Acceptance Criteria

```gherkin
Feature: Actor Identity Portability

  Scenario: AC-31.01 — Player registration creates an actor record
    Given a new player registers
    When the registration transaction commits
    Then an Actor row exists with a unique actor_id
    And the Actor row's player_id matches the new player's id

  Scenario: AC-31.02 — actor_id is independent of player_id
    Given an actor row
    When the actor_id is inspected
    Then actor_id is a ULID distinct from player_id
    And the actor_id contains no derivation of player_id

  Scenario: AC-31.03 — CharacterState created lazily on first session in a universe
    Given an actor with no prior sessions in Universe X
    When a session is opened in Universe X
    Then a CharacterState row exists for (actor_id, universe_id = X)
    And the CharacterState was not present before session creation

  Scenario: AC-31.04 — Second session in same universe reuses existing CharacterState
    Given an actor with an existing CharacterState in Universe X
    When a second session is opened in Universe X (prior session ended)
    Then no new CharacterState row is created
    And the session reads from the existing CharacterState for (actor_id, universe X)

  Scenario: AC-31.05 — Composite unique key prevents duplicate CharacterState
    Given an existing CharacterState for (actor_id = A, universe_id = X)
    When the system attempts to create a second CharacterState for (A, X)
    Then the insert is rejected by the DB UNIQUE constraint
    And the existing CharacterState is preserved unchanged

  Scenario: AC-31.06 — Deleting an actor cascade-deletes all CharacterStates
    Given an actor with CharacterState records in 3 universes
    When the actor is deleted
    Then all 3 CharacterState rows are deleted
    And no orphan CharacterState rows reference the deleted actor_id

  Scenario: AC-31.07 — Deleting a universe cascade-deletes CharacterState; actor intact
    Given universe U with a CharacterState for actor A
    When universe U is deleted (operator action)
    Then the CharacterState for (actor A, universe U) is deleted
    And the Actor row for actor A is NOT deleted
    And any CharacterState records for actor A in other universes are NOT deleted

  Scenario: AC-31.08 — Actor lookup by player_id returns correct actor(s)
    Given a player P with exactly one actor A
    When the system looks up actors by player_id = P
    Then the result contains exactly Actor A

  Scenario: AC-31.09 — CharacterState lookup returns correct universe-scoped state
    Given actor A with CharacterState in Universe X (character_name = "Serin")
    And actor A with CharacterState in Universe Y (character_name = "Dust")
    When the system looks up CharacterState for (actor_id = A, universe_id = X)
    Then the result has character_name = "Serin"
    And the Universe Y CharacterState is not included
```

---

## 9. Dependencies & Integration Boundaries

| Dependency | Spec | Integration Notes |
|---|---|---|
| Universe identity | v2 S29 | `CharacterState.universe_id` FK references the `universes` table defined in S29. |
| Session binding | v2 S30 | S30's `game_sessions.actors` JSONB contains ActorId values defined here. S30 FR-30.03d requires actor records to exist before session creation. |
| Character state content schema | v1 S06 | The fields within `traits`, `inventory`, `conditions`, `emotional_state`, and `reputation` are defined by S06 FR-1.1. S31 governs storage, not content semantics. |
| Player identity | v1 S11 | `Actor.player_id` FK references `players.id` (S11). Player registration and deletion lifecycles drive actor creation (FR-31.01c) and deletion (FR-31.05a). |
| GDPR deletion | v1 S17 | S17's right-to-erasure pipeline must cover actor and character_state records for deleted players. FR-31.05a cascade handles database-level removal; S17 governs any audit trail requirements. |
| Cross-universe travel | v4+ S51 | S31 creates the data model that S51 will use when defining which character state fields transfer, reset, or translate between universes. S51 is out of scope for v2. |
| Persistence migration | v2 S33 | S33 contains the migration DDL that creates the `actors` and `character_states` tables and backfills actor records for all existing players at upgrade time (FR-33.03 Step 3). `ActorService.get_or_create_for_player()` remains as an idempotent lazy-creation fallback for edge cases (see EC-31.06). |

---

## 10. Open Questions

| # | Question | Impact | Owner |
|---|---|---|---|
| OQ-31.01 | What is the source of `actor.display_name` at registration? Options: (a) same as `players.handle`, (b) player chooses a separate traveler name during registration, (c) generated. Choice affects Genesis v2 (S40) onboarding flow. | FR-31.01a `display_name` | S40 author / UX |
| OQ-31.02 | Should `CharacterState` include NPC relationship state (from S06 FR-5)? In v2, NPC relationships were stored per-world in Neo4j (not in the SQL character state blob). Migrating them to SQL `CharacterState` would enable cross-universe relationship portability in v4+, but adds scope. | FR-31.02b field list | S38 NPC Memory / S51 |
| OQ-31.03 | In v1, S06's OQ-6.4 asked about "persistent cross-world character identity" (deferred). S31 answers the identity question but defers the content-transfer question. Confirm that S51 (not S31) is the right home for content-transfer rules. | Boundary with S51 | S51 author |

---

## 11. Out of Scope

- **Content-transfer rules between universes** — which fields of `CharacterState`
  persist, reset, or translate when an actor crosses universes is governed by S51
  (Cross-Universe Travel Protocol), not this spec.
- **Multiple actors per player** — the mechanics of creating and managing a second actor
  for the same player are a v4+ concern. S31 only specifies the v2 policy (one actor per
  player) and the forward-compat schema (no DB uniqueness constraint on
  `actors.player_id`).
- **Actor-to-actor interactions** — how two actors in the same universe perceive or
  affect each other's character state is governed by S57 (Multi-Actor Universe Model,
  v4+).
- **NPC actor identity** — NPCs are not actors in the S31 sense. NPC identity and state
  are governed by v1 S06 and v2 S35 (NPC Autonomy). This spec covers player actors only.
- **Character creation UI** — how the player names and configures their character at
  Genesis is governed by S40 (Genesis v2). S31 specifies the storage contract; S40
  specifies the onboarding experience.
- **Actor soft-delete or account suspension** — disabling a player account without
  destroying actor records is governed by v1 S11 and S26. S31 only covers hard deletion
  cascades.

---

## Changelog

- 2026-04-21: Initial draft. Authored by GitHub Copilot continuing from Claude Code
  rate-limited session. Based on roadmap doc §3.1 S31 summary and v1 specs S06, S11.
