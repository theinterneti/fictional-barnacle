# S29 — Universe as First-Class Entity

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 3 — Platform
> **Dependencies**: v1 S04, v1 S11, v1 S12, v1 S13
> **Last Updated**: 2026-04-21

---

## 1. Purpose

In v1, every game session implicitly created a world as a side effect. The world lived
and died with the session. There was no concept of a world that outlasted the player's
current run, could be picked up later, or could be referenced across contexts. This was
a correct v1 simplification.

v2 changes this. A **Universe** is a named, identifiable, independently-persistent
entity that **owns** its world — locations, NPCs, items, factions, conditions. Sessions
exist *within* a universe; they do not define it. When a session ends, the universe
persists. When a player returns, they re-enter the same universe they left.

This spec defines what a Universe is, what it contains, how its lifecycle is managed,
and how every world-scoped entity is tied to it via `universe_id`. It is the root
dependency of the entire v2 forward-compat architecture.

**Three orthogonal concerns** (each has its own spec):
- **S29** — *Identity*: a universe is a first-class entity with its own ID and boundary.
- **S33** — *Persistence*: the versioned envelope mechanism for storing universe state.
- **S39** — *Composition*: the content vocabulary (themes, tropes, archetypes) that
  fills a universe.

---

## 2. Design Philosophy

### 2.1 Principles

- **Universes outlive sessions**: a session is an ephemeral visit to a universe, not
  the container that holds it. This inversion — universe owns session context, not
  the reverse — is the central shift of this spec.
- **Forward-compat over convenience**: three intentional under-constraints (no DB
  UNIQUE on `session.universe_id`, denormalized `universe_id` on every entity, opaque
  `config` blob) protect v4+ from schema migrations at modest application-code cost.
  See Appendix B.
- **Identity without content**: this spec defines what a universe IS and its lifecycle.
  It deliberately avoids prescribing what fills it (S39) or how that state is stored
  in full detail (S33).
- **Minimal new surface**: S29 introduces one new entity (Universe) and one new field
  (`universe_id` on world-scoped entities). All other behavior — session lifecycle,
  world queries, persistence — is covered by existing specs, extended here.

---

## 3. User Stories

### Persistence & Ownership

> **US-29.1** — **As a** player, I can stop a game session and trust that my universe
> will be exactly as I left it when I return — the world does not reset.

> **US-29.2** — **As a** player, I can see a list of all my universes (active, paused,
> archived) and know which one I was last playing in.

> **US-29.3** — **As a** player, I can archive a universe I no longer want to play,
> removing it from my active list without losing its data.

### Isolation & Integrity

> **US-29.4** — **As a** player, I know that the entities I encounter in one universe
> (locations, NPCs, items) exist only there — a character from one story will never
> appear unexpectedly in another.

> **US-29.5** — **As the** platform, when a player has multiple concurrent sessions,
> each is unambiguously in its own universe with no world data crossing boundaries.

### Developer & Operator

> **US-29.6** — **As a** developer, I can query all world entities belonging to a
> specific universe using a single `universe_id` filter — no root-node traversal is
> required.

> **US-29.7** — **As an** operator, I can inspect a universe's identity, status, and
> config independently of any active session.

---

## 4. Functional Requirements

### FR-29.01 — Universe Identity Fields

A Universe MUST carry the following fields:

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `universe_id` | ULID | No | Globally unique identifier. Primary key. |
| `display_name` | String (1–100 chars) | No | Human-readable name set by the owner. |
| `owner_id` | ULID | No | The `player_id` of the owning player. |
| `status` | Enum | No | One of: `created`, `active`, `paused`, `archived`. |
| `config` | JSON object | No | Opaque config blob. Schema defined by S39. Default: `{}`. |
| `created_at` | Datetime (UTC) | No | Set at creation. Immutable thereafter. |
| `updated_at` | Datetime (UTC) | No | Updated on every status or config change. |

### FR-29.02 — Universe Uniqueness

- **FR-29.02a**: `universe_id` MUST be globally unique. Uniqueness MUST be enforced at
  the database level.
- **FR-29.02b**: A player MAY have multiple universes with the same `display_name`. The
  canonical identifier is `universe_id`, not `display_name`.

### FR-29.03 — Universe Ownership

- **FR-29.03a**: Every universe MUST be owned by exactly one player (`owner_id`).
- **FR-29.03b**: Ownership transfer is out of scope for v2 (see §10).
- **FR-29.03c**: When a player account is deleted, all universes owned by that player
  MUST be processed per the data retention rules in S17.

### FR-29.04 — Universe Lifecycle

Universe status transitions are:

```
          ┌────────────────────────────────────┐
          │                                    │
(new) ──► created ──► active ──► paused ──► active  (resume loop)
                         │         │
                         │         ▼
                         └───► archived ◄─── paused
                                    │
                                    ▼
                                 paused  (explicit unarchival)
```

| Transition | From | To | Trigger |
|---|---|---|---|
| Creation | _(none)_ | `created` | Universe entity is created (before any session). |
| First open | `created` | `active` | A session is opened in this universe (see S30). |
| Session end | `active` | `paused` | The active session ends (completed or abandoned). |
| Resume | `paused` | `active` | A new session is opened in this universe. |
| Archive | `created` or `paused` | `archived` | Explicit archival by the owner. |
| Unarchive | `archived` | `paused` | Explicit unarchival by the owner. |

- **FR-29.04a**: Ending a session MUST NOT delete the universe or any of its world
  entities. The session end MUST transition the universe from `active` to `paused`.
- **FR-29.04b**: Archival MUST be an explicit owner action — it MUST NOT occur
  automatically on session end or inactivity.
- **FR-29.04c**: An `archived` universe MUST NOT accept a new session without explicit
  unarchival first.

### FR-29.05 — World-Entity Universe Scoping

All **world-scoped entity types** as defined in S04 FR-1.1 (Location, Region, NPC,
Item, Event, Faction, Condition) MUST carry a non-nullable `universe_id` field.

- **FR-29.05a**: `universe_id` on a world entity MUST reference a valid, existing
  Universe record.
- **FR-29.05b**: The system MUST reject creation of any world-scoped entity that lacks
  a valid `universe_id`. Error code: `universe_id_required`.
- **FR-29.05c**: `universe_id` on a world entity is immutable after creation. Entities
  cannot be reassigned to a different universe (cross-universe travel is out of scope;
  see §10).

**Relationship to v1 `world_id`**: In v1, S13 defined a `World` Neo4j node with
`world_id` as its root identifier, serving implicitly as the universe boundary. In v2,
`universe_id` is the canonical root identifier. `world_id` and `universe_id` are
semantically equivalent; migration from `world_id` to `universe_id` is specified in
S33. See also Appendix A.

### FR-29.06 — Cross-Universe Isolation

- **FR-29.06a**: Creating a relationship between world entities from different universes
  is FORBIDDEN. The system MUST reject such attempts. Error code:
  `cross_universe_entity_reference`.
- **FR-29.06b**: All world-context queries (nearby, history, diff, region) MUST be
  scoped to a single universe. A query without a `universe_id` scope is invalid.
- **FR-29.06c**: No world entity MAY appear in context queries for a universe it does
  not belong to.

### FR-29.07 — Session↔Universe Association

- **FR-29.07a**: Every game session record MUST carry a `universe_id` FK referencing
  the universe the session is running in.
- **FR-29.07b**: `universe_id` on a session record is set at session creation and is
  immutable thereafter.

**v2 Singleton Policy**: At application level, a universe in `active` status MUST be
associated with at most one `active` game session at any given time.

- **FR-29.07c**: The database schema MUST NOT enforce uniqueness on `session.universe_id`.
  The singleton policy is enforced in application code only. This forward-compat design
  permits multiple simultaneous sessions per universe in v4+ without a schema migration.
- **FR-29.07d**: Attempting to open a session in a universe that is already `active`
  MUST return an error. Error code: `universe_already_active`.
- **FR-29.07e**: The atomic status-check-and-bind protocol (read `active` status, open
  session, update universe status — race-condition-safe) is specified in S30.

### FR-29.08 — Universe Config

- **FR-29.08a**: The `config` field MUST accept any valid JSON object and persist it
  without modification.
- **FR-29.08b**: S29 does not validate the `config` field's contents. Schema validation
  is deferred to S39 (Universe Composition Model). S29 reserves the field only.
- **FR-29.08c**: The `config` field MUST be preserved unchanged across all session
  lifecycle transitions (session open, end, resume).
- **FR-29.08d**: An empty config (`{}`) is always a valid `config` value.

### FR-29.09 — Universe Enumeration and Lookup

- **FR-29.09a**: The system MUST support enumerating all universes owned by a player,
  filterable by `status`.
- **FR-29.09b**: The system MUST support fetching a single universe by `universe_id`.
  An owner can always access their own universes.
- **FR-29.09c**: The system MUST support querying world entities filtered by
  `universe_id` as a top-level predicate (not as a derived traversal from a root node).

---

## 5. Non-Functional Requirements

- **NFR-29.A** — `universe_id` MUST be indexed on all world-scoped entity node labels
  in Neo4j and on all world-scoped entity tables in PostgreSQL.
- **NFR-29.B** — Universe entity creation MUST complete within 200 ms (p95) under
  normal operating load.
- **NFR-29.C** — Universe enumeration for a player (up to 100 universes) MUST complete
  within 100 ms (p95).
- **NFR-29.D** — A `universe_id`-filtered "Nearby" query (see S04 FR-7.2) MUST meet
  the same 200 ms SLA defined in S04 NFR-4.1.

---

## 6. User Journeys

### Journey 1: Player Pauses and Resumes a Universe

1. Player ends a session in universe "The Iron Coast." Session completes.
2. Universe transitions: `active → paused`. All locations, NPC states, faction
   standings, and world conditions are persisted intact.
3. One week later, the player opens the universe list. "The Iron Coast" appears as
   `paused` with a last-played timestamp.
4. Player selects it and opens a new session. Universe transitions: `paused → active`.
5. The turn pipeline reads world context from the persisted universe. The narrative
   engine resumes from the correct state — no reset, no re-generation.

### Journey 2: Player Manages Multiple Concurrent Universes

1. Player has three universes: "The Iron Coast" (paused), "Shattered Peaks" (paused),
   "The Endless Library" (archived).
2. Player opens a session in "The Iron Coast." Universe: `paused → active`.
3. Player ends that session. Universe: `active → paused`.
4. Player opens a session in "Shattered Peaks." Universe: `paused → active`.
5. Player tries to open a second simultaneous session in "The Iron Coast" (from a
   different device). "The Iron Coast" is `paused`, not `active` — this succeeds.
6. Both universes are now `active` simultaneously, each in its own session. No world
   data crosses universes.

### Journey 3: Developer Queries by Universe

1. Developer needs all NPCs in universe `01HX3ABC`. A single Neo4j query:
   `MATCH (n:NPC {universe_id: "01HX3ABC"}) RETURN n`
2. No World root-node traversal needed. The `universe_id` index makes this O(1)
   at any world size.
3. Developer verifies isolation: no NPC from universe `01HX3DEF` appears.

---

## 7. Edge Cases & Failure Modes

| ID | Scenario | Expected Behavior |
|----|----------|-------------------|
| EC-29.01 | Universe status transition (`active → paused`) fails mid-write | Universe remains `active`. Subsequent session-open is blocked by singleton policy. Operator can reset via admin API. Status inconsistency is detectable. |
| EC-29.02 | Player archives a universe while it is `active` | System rejects with `universe_already_active`. Player must end the session first. |
| EC-29.03 | World entity created without `universe_id` | System rejects with `universe_id_required`. Entity is not persisted. |
| EC-29.04 | `universe_id` on world entity references a non-existent universe | System rejects with `universe_not_found`. Universe must exist before any entity can be created in it. |
| EC-29.05 | Player account deleted while a universe is `active` | The active session is force-ended. Universe and its entities are queued for retention processing per S17. No orphan entities remain. |
| EC-29.06 | Session attempts to use a universe owned by a different player | System rejects with `universe_not_owned`. Cross-player universe access is out of scope for v2. |
| EC-29.07 | Race condition: two sessions simultaneously attempt to open in the same universe | The atomic check-and-bind in S30 ensures only one succeeds. The second returns `universe_already_active`. |
| EC-29.08 | Runtime integrity error: session references universe A but a world entity has universe B | This MUST be impossible by construction (FR-29.05a, FR-29.07b). If detected, the turn pipeline MUST fail with `universe_integrity_error` and log the inconsistency. |

---

## 8. Acceptance Criteria

```gherkin
Feature: Universe as First-Class Entity

  # ── Identity and Creation ──────────────────────────────────────────────────

  Scenario: AC-29.01 — Universe creation yields a unique, persistent entity
    Given a player is authenticated
    When the player creates a universe with display_name "The Iron Coast"
    Then a universe entity is created with a unique ULID universe_id
    And the universe status is "created"
    And the universe config is {}
    And created_at is set and is immutable
    And the universe is persisted independently of any session

  Scenario: AC-29.02 — Two universes with the same name are distinct
    Given a player has a universe with display_name "My World"
    When the player creates a second universe with display_name "My World"
    Then both universes are created successfully
    And they have distinct universe_ids
    And both appear when the player enumerates their universes

  # ── World-Entity Scoping ───────────────────────────────────────────────────

  Scenario: AC-29.03 — World entities carry the owning universe_id
    Given a universe U1 with universe_id "01HX3ABC"
    And a session is active in universe U1
    When the world engine creates a Location entity in universe U1
    Then the Location entity has universe_id = "01HX3ABC"
    And the Location cannot be saved without universe_id

  Scenario: AC-29.04 — World entity creation without universe_id is rejected
    When a world entity is created without a universe_id
    Then the system returns an error with code "universe_id_required"
    And the entity is not persisted

  Scenario: AC-29.05 — Cross-universe entity relationships are forbidden
    Given universe U1 containing Location L1
    And universe U2 containing NPC N1
    When the world engine attempts to create a relationship between L1 and N1
    Then the system returns an error with code "cross_universe_entity_reference"
    And the relationship is not created

  # ── Lifecycle ─────────────────────────────────────────────────────────────

  Scenario: AC-29.06 — Universe persists after session ends
    Given universe U1 is active in session S1
    And the world contains locations, NPCs, and items scoped to U1
    When session S1 ends (completed)
    Then universe U1 status becomes "paused"
    And all world entities with universe_id = U1 remain persisted
    And universe U1 is fetchable by universe_id

  Scenario: AC-29.07 — Paused universe can be resumed in a new session
    Given universe U1 with status "paused"
    When a player opens a new session in universe U1
    Then the session is created with universe_id = U1
    And universe U1 status becomes "active"
    And world entities previously created in U1 are accessible within the new session

  Scenario: AC-29.08 — Archival does not happen automatically on session end
    Given universe U1 is active in session S1
    When session S1 ends
    Then universe U1 status is "paused"
    And universe U1 status is NOT "archived"
    And an explicit archival call is required to reach "archived"

  # ── Singleton Policy ──────────────────────────────────────────────────────

  Scenario: AC-29.09 — Universe cannot be active in two sessions simultaneously
    Given universe U1 has status "active" bound to session S1
    When session S2 attempts to open in universe U1
    Then the system returns an error with code "universe_already_active"
    And session S2 is not created
    And universe U1 remains bound to session S1 only

  Scenario: AC-29.10 — Schema permits multiple session rows per universe
    Given universe U1 with one historical (ended) session S1
    When a developer inspects the session table schema
    Then no database-level UNIQUE constraint exists on the universe_id column
    And multiple session rows may reference the same universe_id
    And the singleton policy (AC-29.09) is enforced exclusively in application code

  # ── Config Persistence ────────────────────────────────────────────────────

  Scenario: AC-29.11 — Universe config survives session lifecycle transitions
    Given universe U1 with config {"genre": "gothic", "tone": "melancholic"}
    When session S1 is opened in U1, completes, and session S2 is subsequently opened
    Then universe U1 config is still {"genre": "gothic", "tone": "melancholic"} in S2
    And the config value is identical to what it was in S1

  # ── Enumeration ───────────────────────────────────────────────────────────

  Scenario: AC-29.12 — Player can enumerate their universes filtered by status
    Given a player owns universe U1 (active), U2 (paused), U3 (archived)
    When the player requests their universe list filtered by status "paused"
    Then the response contains U2 only
    And each entry includes universe_id, display_name, status, and created_at

  Scenario: AC-29.13 — World entities are queryable by universe_id
    Given universe U1 containing 3 locations and universe U2 containing 2 locations
    When the system queries locations with universe_id = U1
    Then exactly 3 locations are returned
    And no locations from U2 appear in the result set
```

---

## 9. Dependencies & Integration Boundaries

| Boundary | Spec | Notes |
|----------|------|-------|
| World entity types | v1 S04 | FR-29.05 adds `universe_id` to all entity types in S04 FR-1.1. S29 does not modify any existing S04 FR or AC; it extends them. |
| Game session record | v1 S11 | FR-29.07 adds a `universe_id` FK to the session record defined in S11. |
| Persistence tier | v1 S12 | Universe is a new durable entity type. S12 §4.1 data-category table gains a "Universe" row (durable, PostgreSQL). |
| World graph schema | v1 S13 | `universe_id` aligns with and supersedes v1 `world_id`. S29 establishes the semantic equivalence. Full migration DDL is in S33. |
| Session↔Universe binding | S30 | S29 defines the Universe entity and singleton policy. S30 defines the atomic binding contract, lifecycle handshake, and race-condition-safe status check. |
| Actor portability | S31 | S29 defines the universe boundary. S31 defines how actor IDs remain universe-agnostic and how actor state is scoped per universe. |
| Universe persistence schema | S33 | S29 defines the Universe entity semantics. S33 defines the full DDL, migration path from `world_id`, and state envelope format. |
| Universe composition | S39 | S29 reserves the `config` field without specifying its schema. S39 defines the config content (themes, tropes, archetypes). |
| Privacy / data retention | v1 S17 | Universe deletion on account deletion is governed by S17. S29 establishes `owner_id` as the FK S17 needs to identify universe records scoped to a player. |

---

## 10. Open Questions

| ID | Question | Impact | Responsible |
|----|----------|--------|-------------|
| OQ-29.01 | Does `config: {}` have semantic meaning ("use platform defaults"), or must S39 always pre-populate at least a content type before a session can open in the universe? This affects the genesis flow that wires S29 and S39 together. | AC-29.11 and S39 composition spec. | S39 author |
| OQ-29.02 | Should `archived` universes be hard-deletable by the player? This intersects GDPR right-to-erasure (S17) and long-term storage costs. Soft-delete with a retention window may be sufficient. | S17 retention rules must explicitly cover universe records. | S17 / privacy review |
| OQ-29.03 | The roadmap specifies the singleton policy as app-level (no DB UNIQUE constraint). This question confirms that choice. If reversed, retrofitting a DB constraint is an additive migration; removing one later is harder. | FR-29.07c; architecture review. | Architecture review |

---

## 11. Out of Scope

The following are explicitly NOT part of S29:

| Topic | Spec |
|-------|------|
| Session↔Universe binding contract and atomic lifecycle handshake | S30 |
| Actor identity portability across universes | S31 |
| Transport abstraction (SSE → `NarrativeTransport` interface) | S32 |
| Universe persistence DDL and `world_id → universe_id` migration | S33 |
| Universe composition vocabulary (config schema, themes, tropes) | S39 |
| Concurrent universe loading in one process | S50 |
| Cross-universe actor travel | S51 |
| Nexus as a special universe type | S52, S53 |
| Multiplayer shared universes (multiple actors simultaneously) | S57–S59 |
| Universe ownership transfer between players | Future; single-owner in v2 |
| Universe-level analytics or operator dashboards | S26 (Admin & Operator Tooling) |

---

## 12. Appendix

### A — Relationship to v1 `world_id`

In v1, S13 defines a `World` Neo4j node with `world_id` (ULID) as its unique identifier.
That node was the implicit root of the game world. S29 formalizes and promotes this
concept:

| v1 concept | v2 equivalent | Change |
|---|---|---|
| `World` Neo4j node | `Universe` PostgreSQL entity (+ aligned Neo4j root node) | Promoted to first-class entity with lifecycle and ownership |
| `world_id` (S13) | `universe_id` | Renamed; semantically equivalent; migration DDL in S33 |
| Implicit per-session scope | Explicitly owned by a player; session is a visitor | Ownership and independent lifecycle added |
| No config | `config: JSON` | Config field reserved; schema defined in S39 |
| Status: "draft", "active", "archived" | Status: "created", "active", "paused", "archived" | Added `paused` to distinguish "session ended" from "explicitly archived" |

### B — Forward-compat design rationale

Three intentional under-constraints in S29 preserve v4+ optionality:

1. **No DB UNIQUE on `session.universe_id`** (FR-29.07c): In v4+, multiple actors from
   different sessions share one universe (multiplayer). Adding this without a DB
   migration requires no constraint was ever added.

2. **`universe_id` denormalized on every world entity** (FR-29.05): In v4+, cross-actor
   queries ("all NPCs in universe X who have met any actor") must be efficient.
   Traversal from a single World root is O(world size); a `universe_id` index lookup
   is O(1) regardless of world size.

3. **`config` is an opaque blob** (FR-29.08b): In v4+, universe composition may extend
   in unpredictable ways (Bleedthrough parameters, Resonance coefficients, cross-universe
   rules). An opaque blob with a versioned schema (governed by S39) never requires an
   ALTER COLUMN migration for new config keys.

---

## Changelog

- 2026-04-21: Initial draft. Authored by GitHub Copilot continuing from Claude Code
  rate-limited session. Based on roadmap doc §3.1 and v1 specs S04, S11, S12, S13.
