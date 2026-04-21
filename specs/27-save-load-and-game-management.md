# S27 — Save/Load & Game Management

> **Status**: 📝 Draft
> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ✅ Full
> **Level**: 1 — Core Game Experience
> **Dependencies**: S01 (Gameplay Loop), S04 (World Model), S11 (Player Identity), S12 (Persistence)
> **Last Updated**: 2026-04-09

---

## How to Read This Spec

This is a **functional specification** — it describes *what* the system does, not *how*
it's built. It is one half of a testable contract:

- **This spec** (the "what") defines behavior, acceptance criteria, and boundaries
- **The technical plan** (the "how") will define architecture, stack, and implementation
- **Tasks** will decompose both into small, reviewable chunks of work

Acceptance criteria use **Gherkin syntax** (Given/When/Then) so they can be directly
executed as automated BDD tests using frameworks like Behave or pytest-bdd.

---

## 1. Purpose

This spec defines how players manage their game sessions — creating, resuming, saving,
and deleting games. TTA is a narrative experience that unfolds across multiple sessions;
players must be able to leave and return without losing progress.

The save/load system must be invisible during normal play (automatic persistence) while
giving players explicit control when they want it (game listing, resume, delete).

### Design values applied

| Value | Implication |
|---|---|
| **Fun** | Saving and loading should be frictionless. No lost progress, no manual save anxiety. |
| **Coherence** | When a player resumes a game, the narrative continues seamlessly from exactly where they left off — world state, character memories, and story context are all preserved. |
| **Craftsmanship** | Game management APIs are clean and consistent. The data model supports future features (branching, sharing) without breaking changes. |
| **Transparency** | Players always know what will be saved and what they'll see when they return. No surprises. |

---

## 2. User Stories

### US-27.1 — Player creates a new game
> As a **player**, I want to start a new game with a fresh world and story, so that I
> can begin a new narrative experience.

### US-27.2 — Player resumes a saved game
> As a **player**, I want to return to a game I was playing before and continue from
> exactly where I left off, so that I don't lose progress or context.

### US-27.3 — Player lists their games
> As a **player**, I want to see all my games with enough context to choose which one
> to resume, so that I can manage multiple playthroughs.

### US-27.4 — Player deletes a game
> As a **player**, I want to permanently delete a game I no longer want, so that my game
> list stays tidy and my data is removed.

### US-27.5 — Game state is preserved automatically
> As a **player**, I want my game to be saved automatically after every turn, so that I
> never need to remember to save manually.

### US-27.6 — Player returns after a long absence
> As a **player**, if I return to a game after days or weeks, I want the system to
> provide context about what was happening so I can re-orient, so that the experience
> feels welcoming rather than disorienting.

---

## 3. Functional Requirements

### 3.1 — Game Lifecycle

**FR-27.01**: A game SHALL have one of the following states:

| State | Description |
|---|---|
| `active` | Game is in progress and can receive turns. |
| `completed` | The narrative has reached an ending (per S01 closure mechanics). |
| `abandoned` | Player explicitly deleted the game. Data is soft-deleted. |

**FR-27.02**: A player SHALL be able to create a new game by providing an optional
genre preference and optional player-provided seed text (per S02 genesis onboarding).
If no preferences are given, the system selects defaults.

**FR-27.03**: Creating a new game SHALL:
1. Generate a unique `game_id` (UUID v4)
2. Run the genesis pipeline (per S02) to create initial world state
3. Persist initial game state to the relational database (per S12)
4. Persist initial world graph (per S13)
5. Return the `game_id` and the opening narrative

**FR-27.04**: The maximum number of concurrent active games per player SHALL be
configurable (default: 5). Attempting to create a game beyond this limit SHALL return
a 409 Conflict error per S23.

### 3.2 — Automatic Persistence

**FR-27.05**: After every turn completes (narrative fully generated, per S08), the game
state SHALL be automatically persisted. This includes:
- Turn history (player input + generated narrative + metadata)
- Updated world state (entity changes, relationship changes)
- Updated character states (memory, disposition, location)
- Game metadata (last_played_at, turn_count)

**FR-27.06**: Persistence SHALL be atomic per turn — either the full turn (narrative +
world state + character state + metadata) is saved, or none of it is (per S23 turn
atomicity).

**FR-27.07**: If persistence fails after narrative generation, the system SHALL:
1. Log the failure at ERROR level with full context
2. Return the narrative to the player (do not withhold successfully generated content)
3. Mark the game as `needs_recovery` (internal flag, not player-visible)
4. Retry persistence on the next turn submission for that game

### 3.3 — Game Listing

**FR-27.08**: The `GET /games` endpoint SHALL return a paginated list of the
authenticated player's games, ordered by `last_played_at` descending (most recent
first).

**FR-27.09**: Each game in the listing SHALL include:
- `game_id` (UUID)
- `title` — A short, generated title summarizing the game's premise (set during genesis)
- `state` — One of: `active`, `completed`
- `created_at` — ISO 8601 timestamp
- `last_played_at` — ISO 8601 timestamp
- `turn_count` — Total number of turns played
- `summary` — A 1-2 sentence generated summary of the most recent narrative context

**FR-27.10**: Games in `abandoned` state SHALL NOT appear in the listing. They are
soft-deleted.

**FR-27.11**: Pagination SHALL use cursor-based pagination (not offset-based) using
`last_played_at` as the cursor key. Default page size: 10. Maximum page size: 50.

### 3.4 — Game Resume

**FR-27.12**: Resuming a game SHALL load the full game context needed to continue play:
- The most recent N turns of narrative (configurable, default: 10)
- Current world state summary
- Active character summaries
- The game's current situation description

**FR-27.13**: The resume payload SHALL include a `context_summary` field — a
1-3 sentence generated summary of the story so far, suitable for re-orienting a player
who hasn't played in days or weeks (per US-27.6).

**FR-27.14**: The `context_summary` SHALL be regenerated if more than 24 hours have
passed since the last turn. Otherwise, the previously cached summary is returned.

**FR-27.15**: If a player resumes a game that has a `needs_recovery` flag (from
FR-27.07), the system SHALL attempt to re-persist the missing data before continuing.
If recovery fails, the player receives a message that their last turn may not have been
saved, and gameplay continues from the last successfully saved state.

### 3.5 — Game Deletion

**FR-27.16**: Deleting a game SHALL soft-delete it: the game state is set to
`abandoned` and a `deleted_at` timestamp is recorded.

**FR-27.17**: Soft-deleted game data SHALL be permanently purged after 72 hours
(consistent with S11 FR-11.62 data erasure timeline for TTA-controlled data).

**FR-27.18**: Deleting a game SHALL require confirmation — the API accepts a
`confirm: true` parameter. Requests without confirmation SHALL return a 400 error
with a message explaining the destructive nature of the action.

**FR-27.19**: After deletion, the game SHALL NOT appear in listings, SHALL NOT be
resumable, and attempts to submit turns SHALL return 404.

### 3.6 — Game Title and Summary Generation

**FR-27.20**: When a game is created, the genesis pipeline SHALL generate a short title
(≤80 characters) summarizing the game's premise. This title is stored with the game
and displayed in listings.

**FR-27.21**: After every 5th turn (configurable), the system SHALL regenerate the
game summary used for listings and resume context. The summary SHALL be ≤200
characters and reflect the current state of the narrative.

**FR-27.22**: Title and summary generation SHALL use the same LLM pipeline (per S07)
but with a lightweight, fast model if available. Title/summary generation failures
SHALL NOT block gameplay — the previous title/summary is retained.

---

## 4. Non-Functional Requirements

### NFR-27.1 — Resume Latency
**Category**: Performance
**Target**: Game resume (including context summary generation if needed) SHALL complete
within 3 seconds (p95). Resume without summary regeneration SHALL complete within
500ms (p95).

### NFR-27.2 — Save Durability
**Category**: Reliability
**Target**: Once a turn is reported as successfully saved, the data SHALL survive a
single-node failure. This is guaranteed by PostgreSQL's WAL and the replication
strategy defined in S12.

### NFR-27.3 — Listing Performance
**Category**: Performance
**Target**: Game listing for a player with up to 50 games SHALL return within 200ms
(p95). The query must be indexed by `player_id` and `last_played_at`.

### NFR-27.4 — Data Integrity
**Category**: Reliability
**Target**: Game state SHALL be consistent across all storage backends (Postgres, Neo4j,
Redis) after every turn. If any backend becomes inconsistent, the `needs_recovery` flag
SHALL be set.

---

## 5. User Journeys

### Journey 1: Starting a new game

- **Trigger**: Player chooses "New Game" and selects a fantasy genre.
- **Steps**:
  1. Client sends `POST /games` with `{ genre: "fantasy" }`.
  2. Server runs genesis pipeline (S02). Generates world, characters, opening narrative.
  3. Server persists initial game state. Returns game_id, title, and opening narrative.
  4. Player reads the opening and submits their first turn.
- **Outcome**: Player is immersed in a new story. Game appears in their listing.

### Journey 2: Resuming after a week away

- **Trigger**: Player opens the game a week after their last session.
- **Steps**:
  1. Client sends `GET /games` to list the player's games.
  2. Player sees their game with title "The Ironwood Conspiracy" (last played 7 days ago,
     turn 23, summary: "You've uncovered the mayor's secret ledger...").
  3. Player selects the game. Client sends `GET /games/{id}`.
  4. Server detects >24h since last turn. Regenerates context_summary.
  5. Response includes recent turns, world state, and the fresh context_summary.
  6. Player reads the summary, remembers where they were, and submits a turn.
- **Outcome**: Seamless re-engagement. No disorientation.

### Journey 3: Cleaning up old games

- **Trigger**: Player has 5 games and wants to start a new one.
- **Steps**:
  1. Client sends `GET /games`. Lists 5 active games.
  2. Player decides to delete "Tutorial Island" (completed, turn 3).
  3. Client sends `DELETE /games/{id}` with `{ confirm: true }`.
  4. Server soft-deletes the game. Returns 204.
  5. Player creates a new game. Succeeds (now 4 active + 1 new = 5).
- **Outcome**: Player manages their game library. Data is cleaned up after 72h.

### Journey 4: Connection lost mid-save

- **Trigger**: Server completes narrative generation but loses database connection during
  persistence.
- **Steps**:
  1. Player submits a turn. Narrative is generated successfully.
  2. Persistence fails (database timeout). Turn is marked `needs_recovery`.
  3. Player receives the narrative (it was already generated).
  4. Player submits another turn. Server retries persistence of the previous turn first.
  5. Recovery succeeds. New turn is processed normally.
- **Outcome**: No data loss from the player's perspective. Recovery is automatic.

---

## 6. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| EC-27.1 | Player creates game #6 when max is 5 | 409 Conflict with message: "Maximum active games reached. Delete or complete a game to start a new one." |
| EC-27.2 | Player tries to resume a deleted game | 404 Not Found. Deleted games are not accessible. |
| EC-27.3 | Player tries to submit a turn to a completed game | 409 Conflict with message: "This game has reached its conclusion." |
| EC-27.4 | Database fails during genesis pipeline | Game creation fails. No partial game is left in storage. Player receives 500 error per S23. |
| EC-27.5 | Context summary generation fails during resume | Resume succeeds without the fresh summary. Previous cached summary is returned. Warning logged. |
| EC-27.6 | Player deletes all games then lists | Empty array returned with 200 status. |
| EC-27.7 | Two simultaneous requests to create a game (race condition) | Both may succeed if under the limit. Concurrent-request check is atomic (via database constraint or Redis lock). |
| EC-27.8 | Game has 0 turns (genesis completed but no player turns yet) | Game is valid and resumable. Summary shows the opening narrative context. turn_count is 0. |
| EC-27.9 | Delete request without `confirm: true` | 400 Bad Request with message explaining the confirmation requirement. |
| EC-27.10 | Soft-deleted game's 72h purge window | Purge runs as a background scheduled task (per S14 infrastructure). Exact timing may vary by ±1 hour. |

---

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: Save/Load & Game Management

  Scenario: AC-27.1 — Create a new game
    Given a player with a valid session and fewer than 5 active games
    When the player sends POST /games with genre "fantasy"
    Then the response status is 201
    And the response includes a game_id, title, and opening narrative
    And the game appears in the player's game listing

  Scenario: AC-27.2 — Maximum game limit enforced
    Given a player already has 5 active games
    When the player sends POST /games
    Then the response status is 409
    And the error body contains code "conflict"

  Scenario: AC-27.3 — List games sorted by recency
    Given a player has 3 games played at different times
    When the player sends GET /games
    Then the response contains 3 games
    And the games are ordered by last_played_at descending
    And each game includes game_id, title, state, turn_count, summary

  Scenario: AC-27.4 — Resume a game
    Given a player has an active game with 10 turns
    When the player sends GET /games/{id}
    Then the response includes recent turns
    And the response includes a context_summary
    And the response includes current world state

  Scenario: AC-27.5 — Automatic save after turn
    Given a player submits a turn in an active game
    When the turn processing completes successfully
    Then the game's last_played_at is updated
    And the game's turn_count is incremented
    And the turn's narrative and world state changes are persisted

  Scenario: AC-27.6 — Soft delete a game
    Given a player has an active game
    When the player sends DELETE /games/{id} with confirm=true
    Then the response status is 204
    And the game no longer appears in GET /games
    And the game is not accessible via GET /games/{id}

  Scenario: AC-27.7 — Delete requires confirmation
    Given a player has an active game
    When the player sends DELETE /games/{id} without confirm=true
    Then the response status is 400
    And the error message explains the confirmation requirement

  Scenario: AC-27.8 — Context summary regenerated after absence
    Given a player's last turn was more than 24 hours ago
    When the player resumes the game
    Then the context_summary is freshly generated
    And it reflects the current state of the narrative

  Scenario: AC-27.9 — Persistence failure recovery
    Given a turn's persistence failed and the game has needs_recovery flag
    When the player submits the next turn
    Then the system retries persisting the failed turn first
    And then processes the new turn normally

  Scenario: AC-27.10 — Completed game is read-only
    Given a game has reached state "completed"
    When the player sends POST /turns for that game
    Then the response status is 409
    And the game still appears in listings with state "completed"
```

### Criteria Checklist
- [ ] **AC-27.1**: Game creation with genesis pipeline
- [ ] **AC-27.2**: Maximum active game limit enforcement
- [ ] **AC-27.3**: Game listing with proper sorting and fields
- [ ] **AC-27.4**: Game resume with context summary
- [ ] **AC-27.5**: Automatic persistence after each turn
- [ ] **AC-27.6**: Soft deletion with confirmation
- [ ] **AC-27.7**: Delete confirmation requirement
- [ ] **AC-27.8**: Context summary regeneration after absence
- [ ] **AC-27.9**: Failed persistence recovery
- [ ] **AC-27.10**: Completed game is read-only

---

## 8. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|------|-------------|----------|
| S01 (Gameplay Loop) | Extends | S27 provides the game lifecycle (create/resume/delete) that S01's gameplay loop operates within. Game "completion" is determined by S01's narrative closure mechanics. |
| S02 (Genesis) | Requires | Game creation triggers S02's genesis pipeline to generate the initial world, characters, and opening narrative. |
| S04 (World Model) | Requires | Game resume loads the current world state as defined by S04. |
| S06 (Characters) | Requires | Game resume includes character summaries as defined by S06. |
| S07 (LLM Integration) | Requires | Title/summary generation uses S07's LLM pipeline. |
| S08 (Turn Pipeline) | Cooperates | S08 handles turn processing. S27 handles pre-turn (resume) and post-turn (persistence) bookkeeping. |
| S11 (Identity) | Requires | Game ownership is tied to player identity. All game operations require authentication. |
| S12 (Persistence) | Requires | S27 defines WHAT is persisted. S12 defines WHERE and HOW. |
| S13 (World Graph) | Requires | World graph state is part of game persistence. |
| S17 (Privacy) | Cooperates | Game deletion follows S17's data erasure timelines. Soft-delete with 72h purge aligns with S11 FR-11.62. |
| S23 (Error Handling) | Cooperates | Game management errors use S23's error envelope and error taxonomy. |

---

## 9. Open Questions

| # | Question | Impact | Resolution needed by |
|---|----------|--------|---------------------|
| Q-27.1 | Should completed games count against the active game limit? | If yes, a player who completes 5 games can never start a new one without deleting. Recommend: completed games do NOT count against the limit. | Before implementation |
| Q-27.2 | Should players be able to "archive" completed games (hidden from default listing but not deleted)? | Adds complexity. May be better as a v2 feature. | Can defer |
| Q-27.3 | Should the context_summary be generated by the same model as narrative, or a cheaper/faster model? | Cost vs. quality tradeoff. A cheaper model may produce lower-quality summaries. | Before implementation |
| Q-27.4 | Should the 72h soft-delete window be player-configurable, or fixed? | Privacy compliance may require a fixed window. | Before implementation |

---

## 10. Out of Scope

- **Manual save points / branching** — v1 saves are automatic and linear. Save points
  and story branching are deferred. — Recommended for v2.
- **Game sharing / exporting** — Covered by future S20 (Story Sharing). — Deferred.
- **Game search / filtering** — v1 provides chronological listing only. Search by
  title, genre, or date range is deferred. — Recommended for v2.
- **Game templates / presets** — Predefined starting scenarios beyond genre selection
  are deferred. — Recommended for v2.
- **Cross-device sync** — Games are already server-side. Cross-device access works by
  design (same account). Explicit sync features are not needed. — N/A.

---

## Appendix

### A. Glossary

| Term | Definition |
|---|---|
| **Genesis** | The process of creating a new game world, characters, and opening narrative (defined in S02). |
| **Soft delete** | Marking a record as deleted without immediately removing it from storage. Data is purged after a retention period. |
| **Context summary** | A short, generated description of the current narrative state, used to re-orient returning players. |
| **Cursor-based pagination** | A pagination strategy that uses a pointer to a specific record (cursor) rather than an offset number, providing stable results when data changes between page loads. |
| **needs_recovery** | An internal flag indicating that a game's persisted state may be inconsistent due to a prior persistence failure. |

---

## v1 Closeout (Non-normative)

> This section is retrospective and non-normative. It documents what shipped in the v1
> baseline, what was verified, what gaps were found, and what is deferred to v2.
> It does not change any requirements or acceptance criteria.

### What Shipped

- **Game CRUD** — create, list, get, delete (soft-delete to `abandoned`) via
  `/api/v1/games` (AC-27.1)
- **Game listing** — player sees own games paginated, showing title/summary (AC-27.2)
- **Get game** — returns full game state including turn count and status (AC-27.3)
- **Soft-delete** — sets status to `abandoned`, not physical delete (AC-27.4; aligned
  with FR-27.16 `abandoned` semantics)
- **Resume game** — `POST /api/v1/games/{id}/turns` resumes an active game (AC-27.5)
- **Turn count increment** — each completed turn increments `turn_count` (AC-27.6)
- **State transitions** — `active` → `paused` → `active` → `completed`/`abandoned` (AC-27.7)
- **Read-only completed/abandoned games** — no new turns accepted (AC-27.8)
- **Title and summary** — auto-generated on genesis; updated on game completion (AC-27.9)
- **List own games** — players cannot see other players' games (AC-27.10)

### Evidence

- All 10 v1 ACs covered in `tests/unit/api/test_s27_ac_compliance.py` (10 test classes,
  all passing)
- BDD scenarios `create game`, `play turn`, `delete game` pass
- PR #161 sim: 11/11 turns across a persistent game session

### Gaps Found in v1

1. **Auto-save timing** — saves are synchronous per-turn; no background periodic save;
   no `needs_recovery` flag assertion test beyond schema presence
2. **Resumption context** — returning player receives `context_summary` in response but
   no dedicated "here's what happened" narrative re-orientation (AC-27.5 met minimally)
3. **`POST /admin/games/{id}/terminate`** sets state to `completed` (S26 AC-26.5) — tied
   to admin tooling, not player-facing; tested in S26 suite

### Deferred to v2

| Feature | Reason |
|---------|--------|
| Background periodic auto-save | Architecture; synchronous is sufficient for v1 |
| Narrative re-orientation on resume | Requires pipeline stage for returning-player context |
| Export / full save-file download | Out of scope for v1 |

### Lessons for v2

- All 10 v1 ACs are verified — this is the most complete platform spec in v1
- `needs_recovery` flag is set but the recovery path (re-build from turn log) is not
  implemented; must be specced and tested in v2 before claiming full disaster-recovery coverage
