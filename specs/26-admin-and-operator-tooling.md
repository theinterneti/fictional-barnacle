# S26 — Admin & Operator Tooling

> **Status**: 📝 Draft
> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ⚠️ Partial
> **Level**: 4 — Operations
> **Dependencies**: S10 (API), S11 (Identity), S15 (Observability), S23 (Error Handling)
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

This spec defines the administrative and operational tooling required to run TTA in
production. Operators need visibility into system state, the ability to respond to
incidents, and tools for managing players and games without direct database access.

Admin tooling is **not player-facing** — it is accessed only by authenticated operators
through a separate API prefix (`/admin`). The tooling prioritizes safety (read-only
defaults, confirmation for destructive actions) and auditability (every admin action is
logged).

### Design values applied

| Value | Implication |
|---|---|
| **Craftsmanship** | Operators get first-class tooling, not afterthought scripts. APIs are consistent and well-documented. |
| **Transparency** | Every admin action is auditable. Operators can trace what happened, when, and why. |
| **Fun** | Good operator tooling protects the player experience by enabling fast incident response. |
| **Coherence** | Admin APIs follow the same conventions (error envelopes, pagination, auth) as player-facing APIs. |

---

## 2. User Stories

### US-26.1 — Operator inspects a game
> As an **operator**, I want to view the full state of a specific game including turn
> history, world state, and player info, so that I can investigate reported issues.

### US-26.2 — Operator searches for a player
> As an **operator**, I want to find a player by their player_id or display name, so
> that I can look up their account and associated games for support purposes.

### US-26.3 — Operator terminates a game
> As an **operator**, I want to force-terminate a problematic game session, so that I
> can mitigate an active incident (e.g., a game stuck in a bad LLM loop).

### US-26.4 — Operator views system health
> As an **operator**, I want a single dashboard-friendly endpoint that reports the health
> of all subsystems, so that I can quickly assess system status during an incident.

### US-26.5 — Operator manages moderation flags
> As an **operator**, I want to review games and turns that have been flagged by the
> content moderation system (S24), so that I can take appropriate action.

### US-26.6 — Operator views rate-limit state
> As an **operator**, I want to see current rate-limit counters and cooldown states for
> a specific player or IP, so that I can investigate abuse reports or unblock legitimate
> players who were incorrectly throttled.

### US-26.7 — Operator audits admin actions
> As a **senior operator**, I want to review a log of all admin actions taken by the
> operator team, so that I can ensure proper use of admin privileges.

---

## 3. Functional Requirements

### 3.1 — Admin Authentication & Authorization

**FR-26.01**: All admin endpoints SHALL be prefixed with `/admin` and SHALL require
admin-level authentication, separate from player authentication.

**FR-26.02**: Admin authentication SHALL use the same token mechanism as player auth
(per S11) but SHALL require an `admin` role claim in the token. Tokens without the
`admin` role SHALL receive 403 Forbidden on all `/admin` endpoints.

**FR-26.03**: There SHALL be no self-service admin account creation. Admin accounts
are provisioned through environment configuration or a CLI tool — never through the
API.

**FR-26.04**: Failed admin authentication attempts SHALL be logged at WARN level with
the source IP, token subject (if available), and endpoint accessed.

### 3.2 — Player Management

**FR-26.05**: `GET /admin/players/{player_id}` SHALL return the player's profile,
including:
- `player_id`, `display_name`, `created_at`, `last_seen_at`
- Active game count
- Total game count (including completed and deleted)
- Account status (active, suspended)
- Rate-limit state (current counters, any active cooldowns)

**FR-26.06**: `GET /admin/players?search={query}` SHALL search players by display
name (prefix match) or exact player_id. Results are paginated (cursor-based, default
page size 20, max 100).

**FR-26.07**: `POST /admin/players/{player_id}/suspend` SHALL suspend a player
account. Suspended players:
- Cannot create new games or submit turns
- Can still read/list their existing games
- Receive a 403 Forbidden with `code: "account_suspended"` on write operations

**FR-26.08**: `POST /admin/players/{player_id}/unsuspend` SHALL restore a suspended
player account to active status.

**FR-26.09**: Suspend and unsuspend actions SHALL require a `reason` field in the
request body (minimum 10 characters). The reason is stored in the audit log.

### 3.3 — Game Inspection

**FR-26.10**: `GET /admin/games/{game_id}` SHALL return the full game state including:
- All fields from the player-facing game response (per S27)
- `player_id` (the game owner)
- Full turn history (paginated, not just recent N turns)
- Current world state summary
- Moderation flags (if any, per S24)
- `needs_recovery` flag status

**FR-26.11**: `GET /admin/games/{game_id}/turns` SHALL return a paginated list of all
turns for a game, including:
- `turn_id`, `turn_number`, `player_input`, `generated_narrative`
- `created_at`, `processing_duration_ms`
- Moderation results (flag status, category if flagged)
- LLM metadata (model used, token count, cost estimate)

**FR-26.12**: `POST /admin/games/{game_id}/terminate` SHALL force-terminate an active
game. This:
1. Sets the game state to `completed` (not `abandoned` — that implies player choice)
2. Terminates any in-flight turn processing for the game
3. Closes any active SSE connections for the game
4. Records the termination reason in the audit log

**FR-26.13**: Game termination SHALL require a `reason` field (minimum 10 characters).

### 3.4 — System Health & Diagnostics

**FR-26.14**: `GET /admin/health` SHALL return a comprehensive health report including:

| Subsystem | Check |
|---|---|
| PostgreSQL | Connection pool status, active/idle connections, avg query latency |
| Redis | Connection status, memory usage, key count |
| Neo4j | Connection status, node/relationship counts |
| LLM provider | Last successful call timestamp, current circuit-breaker state (per S23) |
| Rate limiter | Backend status (Redis vs. in-memory fallback, per S25) |
| Turn pipeline | In-flight turn count, queue depth (if queued) |

**FR-26.15**: The health report SHALL include an overall status: `healthy`, `degraded`,
or `unhealthy` (per S23 FR-23.22 through FR-23.25).

**FR-26.16**: `GET /admin/metrics` SHALL expose Prometheus-format metrics. This
endpoint is the same as the existing `/metrics` endpoint but documents it under admin
tooling for completeness.

### 3.5 — Moderation Queue

**FR-26.17**: `GET /admin/moderation/flags` SHALL return a paginated list of moderation
flags (per S24), ordered by created_at descending. Filterable by:
- `status` (pending, reviewed, dismissed)
- `category` (per S24 content categories)
- `game_id` or `player_id`

**FR-26.18**: `POST /admin/moderation/flags/{flag_id}/review` SHALL mark a moderation
flag as reviewed. The request body SHALL include:
- `action` — one of: `dismiss` (false positive), `warn` (note but no action),
  `suspend_player` (triggers player suspension per FR-26.07)
- `notes` — operator notes (minimum 10 characters)

**FR-26.19**: Reviewing a flag with `action: suspend_player` SHALL automatically
suspend the owning player and record both the flag review and the suspension in the
audit log.

### 3.6 — Rate-Limit Management

**FR-26.20**: `GET /admin/rate-limits/player/{player_id}` SHALL return the current
rate-limit state for a player, including:
- Current counters per endpoint group
- Active cooldowns (if any) with expiration timestamps
- Anti-abuse flags (if any)

**FR-26.21**: `POST /admin/rate-limits/player/{player_id}/reset` SHALL clear all
rate-limit counters and cooldowns for a player. This is an emergency override for
legitimate players incorrectly throttled. Requires a `reason` field.

**FR-26.22**: `GET /admin/rate-limits/ip/{ip_address}` SHALL return the current
rate-limit state for an IP address, including counters and any active IP blocks.

**FR-26.23**: `POST /admin/rate-limits/ip/{ip_address}/unblock` SHALL remove an IP
block set by the anti-abuse system (per S25). Requires a `reason` field.

### 3.7 — Audit Log

**FR-26.24**: Every admin action (every non-GET request to `/admin/*`) SHALL be
recorded in an append-only audit log with:
- `admin_id` (who performed the action)
- `action` (endpoint + method)
- `target` (player_id, game_id, flag_id, etc.)
- `reason` (from request body where applicable)
- `timestamp` (ISO 8601 UTC)
- `source_ip` (of the admin request)

**FR-26.25**: `GET /admin/audit-log` SHALL return a paginated, filterable view of the
audit log. Filterable by:
- `admin_id`
- `action`
- `target`
- Date range (`since`, `until`)

**FR-26.26**: The audit log SHALL be immutable — no update or delete operations are
permitted. Retention follows the same policy as application logs (per S15).

---

## 4. Non-Functional Requirements

### NFR-26.1 — Admin Endpoint Latency
**Category**: Performance
**Target**: All admin read endpoints SHALL respond within 1 second (p95). Admin write
endpoints (suspend, terminate, etc.) SHALL respond within 2 seconds (p95).

### NFR-26.2 — Audit Log Durability
**Category**: Reliability
**Target**: Audit log entries SHALL be persisted to the relational database (not
in-memory or Redis). They SHALL survive single-node failures.

### NFR-26.3 — Admin API Availability
**Category**: Availability
**Target**: Admin endpoints SHALL be available whenever the main application is
available. They share the same FastAPI process (per system architecture constraints).

### NFR-26.4 — Access Control
**Category**: Security
**Target**: All admin endpoints SHALL reject non-admin tokens with 403. All admin
actions SHALL be audit-logged. No admin endpoint SHALL be accessible without
authentication.

---

## 5. User Journeys

### Journey 1: Investigating a player report

- **Trigger**: Support receives a report about a player's game behaving oddly.
- **Steps**:
  1. Operator searches for the player: `GET /admin/players?search=CoolDragon42`.
  2. Finds the player. Views their profile to see active games.
  3. Opens the suspect game: `GET /admin/games/{id}`.
  4. Reviews turn history: `GET /admin/games/{id}/turns`.
  5. Finds a turn where the LLM generated an incoherent response.
  6. Checks the moderation flags — none were triggered.
  7. Files an internal note and closes the report.
- **Outcome**: Operator resolved the issue without needing database access.

### Journey 2: Responding to a moderation alert

- **Trigger**: S24 flags a game turn for `hate_speech` content.
- **Steps**:
  1. Operator views moderation queue: `GET /admin/moderation/flags?status=pending`.
  2. Reviews the flagged content and context.
  3. Determines it's a genuine violation (player deliberately injecting harmful input).
  4. Reviews the flag with `action: suspend_player`:
     `POST /admin/moderation/flags/{id}/review`.
  5. Player is automatically suspended. Both actions logged in audit trail.
- **Outcome**: Harmful content addressed. Full audit trail preserved.

### Journey 3: Unblocking a legitimate player

- **Trigger**: A player contacts support saying they can't play anymore.
- **Steps**:
  1. Operator looks up the player: `GET /admin/players/{id}`.
  2. Sees the player has an active rate-limit cooldown (triggered by network issues
     causing rapid reconnections).
  3. Resets rate limits: `POST /admin/rate-limits/player/{id}/reset` with
     `reason: "False positive — network issues caused reconnection storm"`.
  4. Player can play again immediately.
- **Outcome**: Legitimate player unblocked. Action logged for review.

---

## 6. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| EC-26.1 | Admin tries to suspend an already-suspended player | 409 Conflict with message: "Player is already suspended." |
| EC-26.2 | Admin tries to terminate a completed game | 409 Conflict with message: "Game is already completed." |
| EC-26.3 | Admin token expires mid-operation | 401 Unauthorized. Partial operations are not left in an inconsistent state (all admin writes are atomic). |
| EC-26.4 | Admin provides a reason shorter than 10 characters | 400 Bad Request with validation error. |
| EC-26.5 | Two admins simultaneously suspend the same player | First succeeds (200), second gets 409 Conflict. Audit log records the first action only. |
| EC-26.6 | Admin searches for a non-existent player | Empty results array returned with 200 status. |
| EC-26.7 | Admin views rate-limits for a player with no activity | All counters at 0, no cooldowns. Returned as normal response (not 404). |
| EC-26.8 | Audit log query with very wide date range | Enforced maximum result set (1000 entries). Cursor-based pagination for more. |

---

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: Admin & Operator Tooling

  Scenario: AC-26.1 — Admin authentication required
    Given a request to any /admin endpoint
    When the request does not include a valid admin token
    Then the response status is 401 or 403

  Scenario: AC-26.2 — Player search by display name
    Given an admin with a valid admin token
    And a player with display_name "CoolDragon42" exists
    When the admin sends GET /admin/players?search=CoolDragon
    Then the response includes the player's profile

  Scenario: AC-26.3 — Suspend a player
    Given an admin with a valid admin token
    And an active player exists
    When the admin sends POST /admin/players/{id}/suspend with reason "Repeated TOS violations"
    Then the response status is 200
    And the player's status is "suspended"
    And the action is recorded in the audit log

  Scenario: AC-26.4 — Game inspection
    Given an admin with a valid admin token
    And a game with 5 turns exists
    When the admin sends GET /admin/games/{id}
    Then the response includes the full game state
    And the response includes the player_id
    And the response includes moderation flag status

  Scenario: AC-26.5 — Force-terminate a game
    Given an admin with a valid admin token
    And an active game exists
    When the admin sends POST /admin/games/{id}/terminate with reason "Stuck in LLM loop"
    Then the response status is 200
    And the game state is "completed"
    And the action is recorded in the audit log

  Scenario: AC-26.6 — Moderation flag review
    Given an admin with a valid admin token
    And a pending moderation flag exists
    When the admin sends POST /admin/moderation/flags/{id}/review with action "dismiss" and notes "False positive - player was quoting literature"
    Then the flag status is "reviewed"
    And the action is recorded in the audit log

  Scenario: AC-26.7 — Rate-limit reset
    Given an admin with a valid admin token
    And a player has active rate-limit cooldowns
    When the admin sends POST /admin/rate-limits/player/{id}/reset with reason "Network issues caused false positive"
    Then the player's rate-limit counters are cleared
    And the player's cooldowns are removed
    And the action is recorded in the audit log

  Scenario: AC-26.8 — Audit log records all admin writes
    Given an admin performs a suspend, terminate, and flag review
    When the admin sends GET /admin/audit-log
    Then the response includes entries for all three actions
    And each entry includes admin_id, action, target, reason, timestamp
```

### Criteria Checklist
- [ ] **AC-26.1**: Admin authentication and authorization
- [ ] **AC-26.2**: Player search functionality
- [ ] **AC-26.3**: Player suspension with audit trail
- [ ] **AC-26.4**: Full game state inspection
- [ ] **AC-26.5**: Force game termination
- [ ] **AC-26.6**: Moderation flag review workflow
- [ ] **AC-26.7**: Rate-limit reset override
- [ ] **AC-26.8**: Audit log completeness

---

## 8. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|------|-------------|----------|
| S10 (API & Streaming) | Extends | Admin endpoints follow S10's API conventions (versioning, SSE, error format). They share the same FastAPI application. |
| S11 (Identity) | Requires | Admin authentication extends S11's token system with an `admin` role claim. |
| S15 (Observability) | Cooperates | Admin health endpoint aggregates data from S15's monitoring infrastructure. Audit log integrates with S15's structured logging. |
| S23 (Error Handling) | Cooperates | Admin endpoints use S23's error envelope and taxonomy. Error codes are consistent across player and admin APIs. |
| S24 (Content Moderation) | Requires | Moderation queue endpoints consume S24's flag data. Flag review actions are defined here but moderation triggering is S24's responsibility. |
| S25 (Rate Limiting) | Cooperates | Rate-limit inspection and reset endpoints interact with S25's rate-limit state. Admin endpoints themselves are rate-limited (more permissive limits). |
| S27 (Save/Load) | Cooperates | Game inspection endpoints extend S27's game data model with additional admin-only fields. |

---

## 9. Open Questions

| # | Question | Impact | Resolution needed by |
|---|----------|--------|---------------------|
| Q-26.1 | Should there be multiple admin roles (e.g., read-only operator vs. full admin)? | Affects auth complexity. v1 could use a single `admin` role with all permissions. | Before implementation |
| Q-26.2 | Should the audit log support exporting (e.g., CSV/JSON download for compliance)? | Adds complexity. Log aggregation tools (S15) may already provide this. | Can defer |
| Q-26.3 | Should admin endpoints be on a separate port for network isolation? | Security benefit but adds operational complexity. Single-process constraint (system plan) makes this harder. | Before implementation |
| Q-26.4 | Should player suspension notify the player (email, in-game message)? | Requires notification infrastructure not yet specified. | Can defer |

---

## 10. Out of Scope

- **Admin UI / dashboard** — v1 provides API endpoints only. A web dashboard is
  deferred. Operators use curl, httpie, or custom scripts. — Recommended for v2.
- **Role-based access control (RBAC)** — v1 uses a single `admin` role. Fine-grained
  permissions (read-only operator, moderation reviewer, full admin) are deferred.
  — Recommended for v2.
- **Automated incident response** — Automatic actions (e.g., auto-suspend after N
  moderation flags) are deferred. S24 flags; humans act. — Recommended for v2.
- **Player communication** — Email notifications, in-game messages from operators, or
  ban appeal workflows are deferred. — Recommended for v2.
- **Bulk operations** — Batch suspend, batch game termination, etc. v1 handles one
  entity at a time. — Recommended for v2.

---

## Appendix

### A. Admin API Endpoint Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/players/{id}` | Player profile + metadata |
| GET | `/admin/players?search={query}` | Search players |
| POST | `/admin/players/{id}/suspend` | Suspend player account |
| POST | `/admin/players/{id}/unsuspend` | Unsuspend player account |
| GET | `/admin/games/{id}` | Full game inspection |
| GET | `/admin/games/{id}/turns` | Paginated turn history |
| POST | `/admin/games/{id}/terminate` | Force-terminate game |
| GET | `/admin/health` | System health report |
| GET | `/admin/metrics` | Prometheus metrics |
| GET | `/admin/moderation/flags` | Moderation flag queue |
| POST | `/admin/moderation/flags/{id}/review` | Review a flag |
| GET | `/admin/rate-limits/player/{id}` | Player rate-limit state |
| POST | `/admin/rate-limits/player/{id}/reset` | Reset player rate limits |
| GET | `/admin/rate-limits/ip/{ip}` | IP rate-limit state |
| POST | `/admin/rate-limits/ip/{ip}/unblock` | Unblock IP |
| GET | `/admin/audit-log` | Audit log viewer |

### B. Glossary

| Term | Definition |
|---|---|
| **Operator** | A person with admin privileges who manages the TTA platform. Not a player. |
| **Soft suspension** | Player account is marked as suspended but not deleted. The player can still view their games but cannot create or play. |
| **Audit log** | An append-only record of all administrative actions, used for accountability and compliance. |
| **Moderation flag** | A record created by S24's content moderation system when content is classified as potentially violating content policies. |
| **Circuit-breaker state** | The current open/closed/half-open state of circuit breakers per S23, indicating whether a dependent service is available. |

---

## v1 Closeout (Non-normative)

> This section is retrospective and non-normative. It documents what shipped in the v1
> baseline, what was verified, what gaps were found, and what is deferred to v2.

### What Shipped

- **Admin routes** — `src/tta/api/routes/admin.py`; protected by `verify_admin_token`
  dependency
- **Player management** — `GET /admin/players/{id}`, `DELETE /admin/players/{id}` (AC-26.1)
- **Game termination** — `POST /admin/games/{id}/terminate` sets state to `completed`
  (AC-26.5; note: `completed` not `ended`/`abandoned`)
- **World management** — `GET /admin/worlds`, `DELETE /admin/worlds/{id}` (AC-26.3, AC-26.6)
- **Rate-limit reset** — `POST /admin/rate-limit-reset` (AC-26.7)
- **Metrics endpoint** — `GET /metrics` Prometheus scrape endpoint (AC-26.4)

### Evidence

- `tests/unit/api/test_s26_ac_compliance.py` — covers AC-26.1, AC-26.3, AC-26.4,
  AC-26.5, AC-26.6, AC-26.7

### Gaps Found in v1

1. **No player data export** — `GET /admin/players/{id}/export` (AC-26.2) is absent;
   no GDPR-compliant data portability
2. **No audit log** — operator actions (terminations, deletions) are not written to an
   immutable audit trail (AC-26.8)
3. **No admin UI** — all admin operations require direct API calls; no browser-based
   dashboard exists

### Deferred to v2

| Feature | Reason |
|---------|--------|
| Player data export (AC-26.2) | Requires GDPR pipeline; deferred with S17 deletion job |
| Immutable audit log (AC-26.8) | Requires append-only log store or event sourcing |
| Admin dashboard | v2 operator experience work |

### Lessons for v2

- The `verify_admin_token` dependency is simple and effective; consider migrating to
  role-based access control (RBAC) in v2 once multiple operator roles emerge
- Game termination correctly uses `completed` (not `ended`/`abandoned`) — this asymmetry
  is critical for the game lifecycle state machine; document it in v2 state diagrams
- Audit logs should be first-class in v2; every destructive admin action must be traceable
