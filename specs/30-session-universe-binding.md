# S30 — Session↔Universe Binding

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 3 — Platform
> **Dependencies**: v2 S29, v1 S11
> **Last Updated**: 2026-04-21

---

## 1. Purpose

v1 S11 defined game sessions with a `world_seed` blob that initiated world creation as
a side effect. The session implicitly owned its world — the two lived and died together,
with no explicit binding contract and no atomicity guarantee around their creation.

v2 changes this. With S29 introducing Universe as a first-class persistent entity, a
session must explicitly **bind** to a universe at creation time. S30 defines:

- What fields the session record carries to record the binding
- The atomicity guarantee that prevents two sessions from binding to the same universe
  simultaneously (the race-condition protection from S29 EC-29.07)
- The `actors` field structure that makes v4+ multi-actor sessions an additive schema
  change rather than a breaking migration
- How the universe's lifecycle status is kept in sync with the session's lifecycle

This spec **extends** v1 S11 — it does not replace it. The base session model (player
auth, JWT, session lifecycle states, rate limits, anonymous player handling) remains
governed by v1 S11. S30 governs only the universe-binding contract layer on top of that
model.

---

## 2. Design Philosophy

**Explicit binding**: no universe can become `active` without a session explicitly
claiming it. There is no implicit or deferred binding.

**Atomic check-and-set**: the "is the universe available?" check and the "mark it active"
write happen in a single database transaction. An application-level read-then-write is
explicitly prohibited (see FR-30.02c).

**Append-oriented `actors` list**: v2 creates sessions with exactly one actor
(`["<actor_id>"]`). v4+ creates sessions with multiple actors. The schema structure is
identical — only the application-level cardinality policy changes between versions.

**Session end is declarative**: when a session ends, the bound universe transitions to
`paused`. The session makes no assumption about what the player intends to do next —
the universe simply waits, ready for a new binding.

---

## 3. User Stories

- **US-30.1** — **As a** player, **I want** starting a game to exclusively claim my
  universe for the session, **so that** no other session or process modifies my world
  while I'm playing.

- **US-30.2** — **As a** player, **I want** ending a session to preserve my universe in
  a paused state, **so that** I can resume it in a future session.

- **US-30.3** — **As a** player, **I want** to be clearly told when my universe is
  already active, **so that** I do not accidentally create a second session for it.

- **US-30.4** — **As a** developer, **I want** any session record to carry both
  `universe_id` and `actors`, **so that** I can understand the full binding without
  joining multiple tables.

- **US-30.5** — **As a** developer, **I want** the invariant "if universe.status ==
  'active', exactly one non-terminal session references it" to be enforceable and
  auditable, **so that** I can detect and fix any binding inconsistencies.

---

## 4. Functional Requirements

### FR-30.01 — Session Record Extension

- **FR-30.01a**: Every `game_sessions` record MUST carry a `universe_id` FK referencing
  the `universes` table. This column is NOT NULL after v2 migration.
  (S29 FR-29.07 introduced the concept; S30 is the authoritative contract for its
  semantics and lifecycle.)
- **FR-30.01b**: Every `game_sessions` record MUST carry an `actors` column (JSONB array
  of ActorId strings). `actors` MUST be non-null and MUST default to an empty array
  (`'[]'::jsonb`) at the DB level.
- **FR-30.01c**: Both `universe_id` and `actors` are set at session creation time.
  Neither may be updated after the session row is inserted. Any attempt to update these
  fields MUST be rejected.

### FR-30.02 — Binding Atomicity

- **FR-30.02a**: Session creation MUST, within a single database transaction:
  1. Read the target universe's `status`
  2. Verify that `status` is NOT `active` AND NOT `archived`
  3. Set `universe.status = 'active'`
  4. Insert the new session row with `universe_id` and `actors` populated

- **FR-30.02b**: If step 2 fails (universe is `active` or `archived`), the transaction
  MUST be rolled back and the session MUST NOT be created. The appropriate error code
  is returned (`universe_already_active` or `universe_archived`).

- **FR-30.02c**: The check-and-set MUST use a database-level mechanism to prevent
  concurrent transactions from observing stale status. Acceptable approaches:
  `SELECT ... FOR UPDATE` on the universe row, or a conditional `UPDATE universes SET
  status = 'active' WHERE universe_id = ? AND status NOT IN ('active', 'archived')`
  with row-count verification. Application-level read-then-write (two separate
  transactions) is NOT sufficient.

- **FR-30.02d**: If any step in the transaction fails after step 3 (universe marked
  active but session insert fails), the transaction MUST roll back. The universe returns
  to its pre-transaction status. No orphan "active" universes are permitted.

### FR-30.03 — v2 Actor Constraint

- **FR-30.03a**: In v2, the `actors` JSONB array on a new session MUST contain exactly
  one ActorId.
- **FR-30.03b**: The database schema MUST NOT enforce a cardinality constraint on the
  `actors` array (no check constraint on array length). The v2 cardinality policy is
  enforced at application level only, preserving forward-compat for v4+ multi-actor
  sessions.
- **FR-30.03c**: In v2, the application layer MUST reject session creation if the
  provided `actors` list is empty or contains more than one element, returning
  `actors_invalid`.
- **FR-30.03d**: The ActorId in `actors[0]` MUST correspond to an existing actor record
  (as defined in S31). The system MUST reject session creation with `actor_not_found` if
  the ActorId does not exist.

### FR-30.04 — Universe Status Sync on Session Termination

- **FR-30.04a**: When a session transitions to `ended`, the system MUST atomically
  transition the bound universe from `active` to `paused`, within the same database
  transaction as the session status update.
- **FR-30.04b**: When a session transitions to `abandoned` (v1 S11 FR-11.41), the system
  MUST atomically transition the bound universe from `active` to `paused`, within the
  same transaction.
- **FR-30.04c**: When a session transitions to `paused` (temporary player pause, not
  session end), the bound universe's status MUST remain `active`. A paused session still
  holds the exclusive claim on its universe. The universe is only released on session
  termination (`ended` or `abandoned`).
- **FR-30.04d**: If the universe status sync fails (e.g., universe record not found at
  transition time), the session status update MUST also fail. The operator must resolve
  the inconsistency via the admin API.

### FR-30.05 — Binding Invariant

- **FR-30.05a**: At no point MUST a universe in `active` status exist without a
  corresponding session in `created`, `active`, or `paused` state referencing it.
- **FR-30.05b**: At no point MUST two or more sessions in `created`, `active`, or
  `paused` state share the same `universe_id`. (This is the session-level enforcement of
  the S29 singleton policy.)
- **FR-30.05c**: A violation of FR-30.05a or FR-30.05b constitutes a `universe_integrity_error`.
  When detected, the system MUST log the violation at ERROR severity with the
  `universe_id`, `session_id(s)`, and observed statuses. Operator correction via admin
  API is required.

---

## 5. Non-Functional Requirements

- **NFR-30.A** — The atomic session-creation-and-universe-activation transaction MUST
  complete within 200 ms (p95) under normal load.
- **NFR-30.B** — The universe status sync on session termination MUST complete within
  100 ms (p95).
- **NFR-30.C** — The binding invariant check (FR-30.05) MUST be detectable via a
  lightweight query (O(sessions with non-terminal status)) to support periodic operator
  health audits without table scans.

---

## 6. User Journeys

### Journey 1: Player Opens First Session in a New Universe

**Trigger**: Player calls `POST /api/v1/games` with `{ universe_id: "univ_01...", actors: ["actor_01..."] }`

1. System validates player is authenticated and actor belongs to the player.
2. System begins a DB transaction.
3. `SELECT universe_id, status FROM universes WHERE universe_id = ? FOR UPDATE`
   → returns status `created`.
4. `UPDATE universes SET status = 'active' WHERE universe_id = ?`
5. `INSERT INTO game_sessions (player_id, universe_id, actors, status) VALUES (...)`
6. Transaction commits.
7. Response: `{ game_id: "...", universe_id: "...", actors: [...], status: "created" }`

### Journey 2: Player Attempts Second Session in an Active Universe

**Trigger**: Player calls `POST /api/v1/games` for a universe already owned by an active
session.

1. System begins transaction.
2. `SELECT ... FOR UPDATE` returns status `active`.
3. Transaction rolls back immediately.
4. Response: `400 Bad Request`, error `universe_already_active`.

### Journey 3: Player Ends a Session

**Trigger**: Player calls `POST /api/v1/games/{game_id}/end`

1. System verifies session belongs to calling player.
2. System begins transaction.
3. `UPDATE game_sessions SET status = 'ended', ended_at = now() WHERE id = ?`
4. `UPDATE universes SET status = 'paused', paused_at = now() WHERE universe_id = ?`
   (universe_id from session record)
5. S33's snapshot write executes (same transaction; see S33 FR-33.02b).
6. Transaction commits.
7. Universe is now `paused`, ready for a future session to bind to it.

### Journey 4: Player Pauses (Not Ends) a Session

**Trigger**: Player calls `POST /api/v1/games/{game_id}/pause` or disconnects mid-turn.

1. `UPDATE game_sessions SET status = 'paused', paused_at = now() WHERE id = ?`
2. Universe status is NOT touched — remains `active`.
3. Player can resume by calling `POST /api/v1/games/{game_id}/resume`.
4. On resume: `UPDATE game_sessions SET status = 'active'` — universe already `active`,
   no universe update needed.

---

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| EC-30.01 | Universe is `archived` at session creation | Rejected: `universe_archived`. Player must unarchive first. |
| EC-30.02 | Universe is `paused` at session creation | SUCCEEDS: `paused → active` transition valid; new session creates and binds. |
| EC-30.03 | Universe does not exist | Rejected: `universe_not_found`. |
| EC-30.04 | Universe owned by different player | Rejected: `universe_not_owned`. |
| EC-30.05 | `actors` list is empty | Rejected: `actors_invalid`. |
| EC-30.06 | `actors[0]` references non-existent actor | Rejected: `actor_not_found`. |
| EC-30.07 | Transaction fails after universe marked `active` but before session insert | Transaction rolls back. Universe reverts to pre-transaction status. No orphan active universe. |
| EC-30.08 | Two concurrent session-creation requests for same universe | Exactly one succeeds (serialized by `SELECT FOR UPDATE`). Other returns `universe_already_active`. |
| EC-30.09 | Session end transaction fails | Session remains in prior status; universe remains `active`. Operator alert. No partial state committed. |
| EC-30.10 | Universe not found at session-end time (deleted out of band) | Session end rejected: `universe_not_found`. Integrity alarm raised; operator must resolve. |

---

## 8. Acceptance Criteria

```gherkin
Feature: Session↔Universe Binding

  Scenario: AC-30.01 — Session creation with universe in created status succeeds
    Given a universe in "created" status
    When a player creates a new session bound to that universe with 1 actor
    Then the session is created successfully
    And the universe status transitions to "active"
    And the session record carries universe_id and actors = [<actor_id>]

  Scenario: AC-30.02 — Session creation with universe in paused status succeeds (resume)
    Given a universe in "paused" status
    When a player creates a new session bound to that universe with 1 actor
    Then the session is created successfully
    And the universe status transitions to "active"

  Scenario: AC-30.03 — Session creation with universe already active is rejected
    Given a universe in "active" status
    When a player attempts to create a session bound to that universe
    Then the response is 400 Bad Request
    And the error code is "universe_already_active"
    And no new session row is inserted

  Scenario: AC-30.04 — Session creation with archived universe is rejected
    Given a universe in "archived" status
    When a player attempts to create a session bound to that universe
    Then the response is 400 Bad Request
    And the error code is "universe_archived"

  Scenario: AC-30.05 — universe_id on session is set at creation and is immutable
    Given an existing session S with universe_id = U
    When an API call attempts to update session S's universe_id to U2
    Then the update is rejected
    And session S still carries universe_id = U

  Scenario: AC-30.06 — actors list contains exactly one element in v2
    Given a valid universe and actor in v2
    When the player creates a new session
    Then the session's actors field contains exactly one ActorId

  Scenario: AC-30.07 — DB schema does not constrain actors array length
    Given the universe_snapshots schema
    When a row is inserted into game_sessions with actors = ["id1", "id2"]
    Then the insert succeeds (schema accepts arrays of any length)

  Scenario: AC-30.08 — Ending a session transitions universe to paused
    Given an active session bound to universe U (universe is "active")
    When the player ends the session
    Then the session status is "ended"
    And universe U status is "paused"
    And both changes occur in the same transaction

  Scenario: AC-30.09 — Pausing a session does not change universe status
    Given an active session bound to universe U (universe is "active")
    When the player pauses the session
    Then the session status is "paused"
    And universe U status remains "active"

  Scenario: AC-30.10 — Race condition: only one of two concurrent opens succeeds
    Given a universe in "paused" status
    When two concurrent session-creation requests arrive simultaneously
    Then exactly one session is created and the universe transitions to "active"
    And the other request returns 400 "universe_already_active"
```

---

## 9. Dependencies & Integration Boundaries

| Dependency | Spec | Integration Notes |
|---|---|---|
| Universe entity + lifecycle | v2 S29 | S30 consumes `universe.status` and the `universes` table. S29 FR-29.04 defines the lifecycle transitions; S30 enforces them atomically at session-create and session-end. |
| Session lifecycle model | v1 S11 | S30 adds `universe_id` and `actors` to the session schema defined in S11. S11's session state machine governs when sessions enter `ended`/`abandoned`; S30 adds the universe sync obligation at those transitions. |
| Actor identity | v2 S31 | S30 FR-30.03d requires actor records to exist (defined in S31). Actor creation is S31's responsibility; S30 only references actor_ids. |
| Snapshot write on session end | v2 S33 | FR-30.04 and S33 FR-33.02b specify that universe snapshot write is co-transactional with session end. S30 mandates the atomicity; S33 defines what is written. |
| Error taxonomy | v1 S23 | New error codes introduced by S30: `universe_already_active`, `universe_archived`, `universe_not_owned`, `actor_not_found`, `actors_invalid`, `universe_integrity_error` (shared with S29). |
| Admin API | v1 S26 | FR-30.05c requires operator resolution of binding invariant violations. S26 admin API must expose a universe binding audit endpoint. |

---

## 10. Open Questions

| # | Question | Impact | Owner |
|---|---|---|---|
| OQ-30.01 | Should the `SELECT ... FOR UPDATE` be at `SERIALIZABLE` isolation or `REPEATABLE READ` with explicit row lock? The two behave differently under concurrent workloads; `SERIALIZABLE` is safer but slower. | FR-30.02c atomicity guarantee | Architecture review |
| OQ-30.02 | When a session is `abandoned`, should the universe go to `paused` or back to `created`? The current spec says `paused` (since the universe was activated when the session was created). If genesis was never run, `created` might be more accurate semantically. | FR-30.04b | S40 Genesis v2 author |
| OQ-30.03 | What is the API surface for binding? Does `POST /api/v1/games` accept `universe_id` as a parameter, or does creating a game always create a new universe? If the latter, S30 and S29 need a "create universe and open session in one call" composite operation. | API design | v1 S10 / S29 |

---

## 11. Out of Scope

- **Universe creation during session open** — creating a universe as an implicit side
  effect of session creation is explicitly prohibited in v2. Universe creation is always
  a separate, explicit operation (S29). This spec does not cover that flow.
- **Multi-actor session semantics** — the `actors` list with more than one element is
  a v4+ concern. S30 only specifies the v2 cardinality policy and the forward-compat
  constraint (no DB uniqueness on actors count). v4+ multi-actor binding rules are
  governed by S57.
- **Actor-to-universe routing** — deciding which universe an actor enters, or listing
  which universes an actor has character states in, is covered by S31.
- **Session resume mechanics** — the "welcome back" narrative, context reconstruction,
  and hot-cache reload on resume are governed by v1 S11 FR-11.43 and S33 (snapshot
  load lifecycle).
- **Cross-universe session transfers** — an actor moving from Universe A to Universe B
  requires ending one session and opening another. The transfer mechanics, state
  translation, and arrival onboarding are governed by S51 (Cross-Universe Travel
  Protocol).
- **Session hijacking / device conflict** — multiple devices attempting to connect to
  the same session is governed by v1 S11 FR-11.52 (`session_taken` event).

---

## 12. Appendix

### A — Error Codes Introduced by S30

| Code | HTTP Status | When Returned |
|---|---|---|
| `universe_already_active` | 400 | Session creation attempted on an `active` universe |
| `universe_archived` | 400 | Session creation attempted on an `archived` universe |
| `universe_not_owned` | 403 | Session created for universe owned by different player |
| `actor_not_found` | 400 | `actors[0]` ActorId does not exist |
| `actors_invalid` | 400 | `actors` is empty or contains more than one element (v2) |
| `universe_integrity_error` | 500 | Binding invariant violated; operator action required |

### B — Session Schema Changes from v1 to v2

| Column | Change | Notes |
|---|---|---|
| `world_seed` (v1 JSONB) | Deprecated, kept for migration | v1 world configuration; superseded by `universe_id` FK + S33 snapshot mechanism |
| `universe_id` (new UUID FK) | Added — NOT NULL after backfill | References `universes.universe_id` |
| `actors` (new JSONB) | Added — default `'[]'::jsonb` | List of ActorId strings; length=1 in v2 |

Full migration DDL is in S33.

---

## Changelog

- 2026-04-21: Initial draft. Authored by GitHub Copilot continuing from Claude Code
  rate-limited session. Based on roadmap doc §3.1 S30 summary and v1 specs S11, S29.
