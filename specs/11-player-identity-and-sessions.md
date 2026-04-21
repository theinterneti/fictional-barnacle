# S11 — Player Identity & Sessions

> **Status**: 📝 Draft
> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ⚠️ Partial
> **Level**: 3 — Platform
> **Dependencies**: S12 (Persistence Strategy)
> **Last Updated**: 2026-04-07

---

## 1. Purpose

This spec defines what a "player" is in TTA, how they prove their identity, what they're
allowed to do, and how their game sessions are managed from creation to completion.

TTA's identity model is designed for a **single-player game** — but with enough structure
to support multiplayer later. For v1, simplicity wins: email/password auth, simple RBAC,
stateless tokens, and a clean session lifecycle.

---

## 2. Design Philosophy

### 2.1 Principles

- **Low friction to play**: a player should be able to start a game within seconds of
  arriving. Anonymous play is supported for first contact.
- **Ownership over anonymity**: players who create accounts own their progress. Anonymous
  players can play but cannot save or resume.
- **Stateless auth**: the server does not store sessions for authentication. JWTs carry
  the identity. Game sessions are a different concept from auth sessions.
- **Privacy by default**: minimal data collection. No tracking. GDPR-ready from day one.
- **Roles, not permissions**: a small set of roles (player, admin) with well-defined
  capabilities. No fine-grained permission matrix for v1.

### 2.2 Key Distinction: Auth Sessions vs. Game Sessions

| Concept | Auth Session | Game Session |
|---------|-------------|--------------|
| What is it? | Proof of identity (JWT token) | An active playthrough |
| Lifetime | Until token expires or is revoked | Until player ends or abandons |
| Storage | Client-side (token) | Server-side (Redis + SQL) |
| Multiplicity | One per device | Multiple per player |

---

## 3. User Stories

### Identity

> **US-11.1** — **As a** new visitor, I can start playing immediately as an anonymous player
> so I can try the game without commitment.

> **US-11.2** — **As a** guest player, I can create an account mid-session and keep my
> current progress so I don't lose what I've done.

> **US-11.3** — **As a** returning player, I can log in with my email and password and see
> all my saved games.

> **US-11.4** — **As a** player, I can change my display name and preferences without
> affecting my game progress.

> **US-11.5** — **As a** player, I can delete my account and all associated data.

### Sessions

> **US-11.6** — **As a** player, I can have multiple games in progress simultaneously (up to
> a limit) and switch between them.

> **US-11.7** — **As a** player, I can pause a game, close my browser, and resume from
> exactly where I left off — even from a different device.

> **US-11.8** — **As a** player whose game has been idle for a long time, I receive a clear
> indication that the session has timed out, with the option to resume.

> **US-11.9** — **As a** player, I can explicitly end a game and it appears in my completed
> games history.

### Admin

> **US-11.10** — **As a** platform admin, I can view player accounts (without seeing passwords) for
> support and moderation purposes.

> **US-11.11** — **As a** platform admin, I can disable a player account if needed for safety or
> abuse reasons.

> **US-11.12** — **As a** platform admin, I can view active game sessions for monitoring purposes.

### Developer & Operator

> **US-11.13** — **As a** developer, I can run the full auth flow locally without external
> dependencies so that I can develop and test identity features offline.

> **US-11.14** — **As a** platform operator, I can monitor login failure rates and token refresh
> patterns so that I can detect brute-force attempts and session anomalies.

> **US-11.15** — **As a** developer, I can inspect session state transitions in logs so that
> I can debug lifecycle issues without accessing production data.

---

## 4. Player Identity

### 4.1 What Is a Player?

A player is a person who interacts with the TTA game. Every player — including anonymous
ones — has a server-side identity record.

### 4.2 Player Attributes

| Attribute | Type | Required | Mutable | Notes |
|-----------|------|----------|---------|-------|
| `player_id` | ULID | Yes | No | System-assigned, globally unique |
| `display_name` | String(1–50) | Yes | Yes | Shown in-game. Defaults to "Adventurer" |
| `email` | String | No* | Yes | Required for registered players |
| `password_hash` | String | No* | Yes | bcrypt hash. Required for registered players |
| `role` | Enum | Yes | Yes (admin only) | "player" or "admin" |
| `status` | Enum | Yes | Yes (admin only) | "active", "disabled", "deleted" |
| `is_anonymous` | Boolean | Yes | No† | True if no credentials attached |
| `preferences` | JSON | Yes | Yes | Player settings (see §4.4) |
| `created_at` | Timestamp | Yes | No | Account creation time |
| `last_login_at` | Timestamp | No | Yes | Last successful authentication |

*Required for registered (non-anonymous) players.
†Changes implicitly when an anonymous player registers (see §5.3).

### 4.3 Player Identity Rules

- FR-11.01: Every player MUST have a unique `player_id` assigned at creation time.
- FR-11.02: `player_id` MUST be a ULID (Universally Unique Lexicographically Sortable
  Identifier) to enable time-ordered queries.
- FR-11.03: Email addresses MUST be unique across all registered players.
- FR-11.04: Email addresses MUST be stored in lowercase, trimmed of whitespace.
- FR-11.05: Display names MUST be 1–50 characters. Allowed characters: letters, numbers,
  spaces, hyphens, underscores, periods.
- FR-11.06: Display names are NOT required to be unique (players are identified by ID,
  not name).

### 4.4 Player Preferences

Preferences are a structured JSON object stored with the player profile. They control
client-side behavior and some server-side behavior.

| Preference | Type | Default | Description |
|------------|------|---------|-------------|
| `text_speed` | Enum | "normal" | "slow", "normal", "fast" — affects SSE chunk delay |
| `theme` | Enum | "dark" | "dark", "light", "system" |
| `content_sensitivity` | Enum | "standard" | "mild", "standard", "mature" |
| `narration_style` | Enum | "balanced" | "brief", "balanced", "detailed" |
| `sound_enabled` | Boolean | true | Enable/disable sound effects |

- FR-11.07: Unknown preference keys MUST be silently ignored (forward compatibility).
- FR-11.08: Preference values MUST be validated against the allowed values for each key.
- FR-11.09: The `content_sensitivity` preference MUST be respected by the narrative
  generation pipeline (see S04).

---

## 5. Authentication

### 5.1 Authentication Methods

For v1, TTA supports two authentication methods:

| Method | Flow | Use Case |
|--------|------|----------|
| **Anonymous** | Client requests anonymous token | Try before you buy |
| **Email + Password** | Client sends credentials, receives token | Returning players |

Future methods (OAuth, magic links) are deferred to post-v1.

### 5.2 Auth Endpoints

#### `POST /api/v1/auth/anonymous`

Create an anonymous player and receive a token.

**Request:** No body required.

**Response:** `201 Created` with:
- `access_token`, `refresh_token`, `token_type` ("Bearer"), `expires_in` (seconds)
- `player_id`, `is_anonymous` (true)

**Behavior:**
- FR-11.10: Each call MUST create a new anonymous player record.
- FR-11.11: Anonymous tokens MUST have the same structure as registered player tokens.
- FR-11.12: Anonymous player records older than 30 days with no active games MUST be
  eligible for automated cleanup.

#### `POST /api/v1/auth/register`

Create a registered player account.

**Request shape:**
- `email` (string, required): valid email address
- `password` (string, required): 8–128 characters, at least one letter and one number
- `display_name` (string, optional): defaults to "Adventurer"

**Response:** `201 Created` with token set (same shape as anonymous).

**Behavior:**
- FR-11.13: If the email is already registered, return `409 Conflict` with error code
  `EMAIL_ALREADY_REGISTERED`.
- FR-11.14: Passwords MUST be hashed with bcrypt (cost factor ≥ 12) before storage.
- FR-11.15: The raw password MUST NOT appear in logs, error messages, or responses.
- FR-11.16: Password validation rules MUST be returned in the error details if the
  password is rejected.

#### `POST /api/v1/auth/login`

Authenticate with email and password.

**Request shape:**
- `email` (string, required)
- `password` (string, required)

**Response:** `200 OK` with token set.

**Behavior:**
- FR-11.17: Failed login attempts MUST return `401 Unauthorized` with a generic error
  message ("Invalid email or password"). The response MUST NOT indicate whether the
  email exists.
- FR-11.18: After 5 consecutive failed login attempts for the same email, the account
  MUST be temporarily locked for 15 minutes.
- FR-11.19: Login MUST update the `last_login_at` timestamp.

#### `POST /api/v1/auth/refresh`

Exchange a refresh token for a new access token.

**Request shape:**
- `refresh_token` (string, required)

**Response:** `200 OK` with new token set.

**Behavior:**
- FR-11.20: Refresh tokens MUST be single-use. After exchange, the old refresh token
  is invalidated.
- FR-11.21: Refresh token rotation: each refresh returns a new refresh token as well.
- FR-11.22: If a previously-used refresh token is presented, ALL tokens for that player
  MUST be invalidated (potential theft detection).

#### `POST /api/v1/auth/logout`

Invalidate the current token.

**Behavior:**
- FR-11.23: The access token and associated refresh token MUST be added to a deny-list
  (stored in Redis with TTL matching the token's remaining lifetime).

### 5.3 Anonymous-to-Registered Upgrade

#### `POST /api/v1/auth/upgrade`

Convert an anonymous player to a registered player.

**Request shape:**
- `email` (string, required)
- `password` (string, required)
- `display_name` (string, optional)

**Behavior:**
- FR-11.24: The anonymous player's `player_id` MUST be preserved.
- FR-11.25: All existing game sessions MUST be retained and associated with the new
  registered identity.
- FR-11.26: The `is_anonymous` flag MUST be set to false.
- FR-11.27: A new token set MUST be issued reflecting the upgraded identity.
- FR-11.28: If the email is already registered, return `409 Conflict`.

### 5.4 Token Structure

Tokens are JWTs (JSON Web Tokens) signed with a server-side secret.

**Access token claims:**
- `sub`: player_id
- `role`: "player" or "admin"
- `anon`: boolean — whether this is an anonymous player
- `iat`: issued at (Unix timestamp)
- `exp`: expires at (Unix timestamp)
- `jti`: unique token ID (for deny-listing)

**Token lifetimes:**
| Token | Lifetime |
|-------|----------|
| Access token | 1 hour |
| Refresh token | 30 days |
| Anonymous access token | 24 hours |
| Anonymous refresh token | 7 days |

- FR-11.29: Access tokens MUST be short-lived (1 hour for registered, 24 hours for
  anonymous).
- FR-11.30: Refresh tokens MUST be longer-lived but still expire.
- FR-11.31: Token signing MUST use HS256 with a server-side secret of at least 256 bits.
- FR-11.32: The signing secret MUST be configurable via environment variable and MUST NOT
  be committed to source code.

---

## 6. Authorization (RBAC)

### 6.1 Roles

| Role | Description |
|------|-------------|
| `player` | Default role. Can play games, manage own profile. |
| `admin` | Can manage players, view all sessions, access admin endpoints. |

Future role: `author` — can create and edit world content. Deferred to post-v1.

### 6.2 Permission Matrix

| Action | `player` | `admin` |
|--------|----------|---------|
| Create/play games | ✅ | ✅ |
| View own profile | ✅ | ✅ |
| Update own profile | ✅ | ✅ |
| Delete own account | ✅ | ✅ |
| View other players | ❌ | ✅ |
| Disable player accounts | ❌ | ✅ |
| View all game sessions | ❌ | ✅ |
| Access admin endpoints | ❌ | ✅ |
| Manage world content | ❌ | ✅ |

### 6.3 Authorization Rules

- FR-11.33: Every API request MUST be authorized based on the `role` claim in the JWT.
- FR-11.34: Players MUST only access their own resources. Attempts to access another
  player's resources MUST return `404 Not Found` (not `403`, to avoid leaking existence).
- FR-11.35: Admin endpoints MUST be grouped under a separate URL prefix (e.g.,
  `/api/v1/admin/`) and MUST return `404` for non-admin callers.
- FR-11.36: The first registered user MAY be automatically assigned the `admin` role
  (configurable, for self-hosted setups).
- FR-11.37: Role changes MUST only be performed by admins and MUST be audit-logged.

---

## 7. Session Lifecycle

### 7.1 Session States

```
  ┌──────────┐
  │  created  │──────────────────────────────────────┐
  └────┬─────┘                                       │
       │ (first turn submitted)                      │
       ▼                                             │
  ┌──────────┐     ┌──────────┐     ┌──────────┐    │
  │  active   │────▶│  paused  │────▶│  active  │    │
  └────┬─────┘     └────┬─────┘     └──────────┘    │
       │                │                            │
       │                │ (timeout: 30 days)         │
       │                ▼                            │
       │           ┌──────────┐                      │
       │           │ expired  │                      │
       │           └──────────┘                      │
       │                                             │
       ▼                                             ▼
  ┌──────────┐                                  ┌──────────┐
  │  ended   │                                  │ abandoned │
  └──────────┘                                  └──────────┘
       (player explicit end)                    (never had a turn + 24h)
```

| State | Description |
|-------|-------------|
| `created` | Game initialized but no turns played yet |
| `active` | Player has submitted at least one turn; game is in progress |
| `paused` | Player explicitly paused or client disconnected |
| `expired` | Paused game that exceeded the inactivity timeout |
| `ended` | Player explicitly ended the game |
| `abandoned` | Created but never played; cleaned up after 24 hours |

### 7.2 State Transition Rules

- FR-11.38: Valid transitions are:
  - `created` → `active` (first turn submitted)
  - `created` → `abandoned` (no turns within 24 hours)
  - `active` → `paused` (explicit pause or client disconnect)
  - `active` → `ended` (explicit end)
  - `paused` → `active` (explicit resume)
  - `paused` → `expired` (30 days of inactivity)
  - `paused` → `ended` (explicit end while paused)
- FR-11.39: All other transitions MUST be rejected with `422 Unprocessable Entity`.
- FR-11.40: Every state transition MUST be timestamped and logged.

### 7.3 Session Timeout

- FR-11.41: Games in `paused` state for more than 30 days MUST be automatically
  transitioned to `expired`.
- FR-11.42: Games in `created` state for more than 24 hours without a turn MUST be
  automatically transitioned to `abandoned`.
- FR-11.43: Expired games CAN be resumed by the player (transition back to `active`).
  The game state is preserved but the player sees a "welcome back" narrative.
- FR-11.44: Abandoned games MAY be cleaned up (data deleted) after an additional 7 days.
- FR-11.45: The timeout check MUST be performed by a background task, not on every
  API request.

---

## 8. Session State & Storage

### 8.1 What Is Stored in a Session?

| Data | Storage | Durability | Notes |
|------|---------|------------|-------|
| Session metadata | SQL | Durable | game_id, player_id, status, timestamps |
| Turn history | SQL | Durable | Full conversation log |
| Current game state | Redis + SQL | Hot cache + durable | Current location, inventory, NPC states |
| SSE event buffer | Redis | Ephemeral | For reconnection replay |
| Turn processing lock | Redis | Ephemeral | Prevents concurrent turns |

### 8.2 Session Data Shape

**Session record (SQL):**
- `game_id` (ULID)
- `player_id` (ULID, FK)
- `world_id` (string, FK)
- `status` (enum: created, active, paused, expired, ended, abandoned)
- `turn_count` (integer)
- `created_at`, `last_active_at`, `paused_at`, `ended_at` (timestamps)

**Turn record (SQL):**
- `turn_id` (ULID)
- `game_id` (ULID, FK)
- `turn_number` (integer)
- `player_input` (text)
- `narrative_response` (text — full assembled response)
- `game_state_snapshot` (JSON — state after this turn)
- `created_at`, `completed_at` (timestamps)
- `processing_time_ms` (integer)

**Hot session state (Redis):**
- Key: `session:{game_id}`
- TTL: 2 hours after last access
- Content: current location, inventory, recent context window, active NPC states

### 8.3 Storage Rules

- FR-11.46: Session metadata and turn history MUST be persisted to SQL for durability.
- FR-11.47: Hot session state MUST be cached in Redis for low-latency access during
  gameplay.
- FR-11.48: If the Redis cache is cold (miss), the system MUST reconstruct hot state
  from SQL and the world graph.
- FR-11.49: Cache reconstruction MUST be transparent to the player — no error, just
  slightly higher latency on the first turn after a cold start.
- FR-11.50: Turn records MUST store the complete narrative response, not just a reference
  to streaming chunks.

---

## 9. Multi-Device Support

- FR-11.51: A player MUST be able to log in from multiple devices simultaneously.
- FR-11.52: Only one device at a time MAY have an active SSE connection to a given game.
  A new connection MUST close the previous one with a `session_taken` event.
- FR-11.53: Game state MUST be consistent across devices — the last-written state wins.
- FR-11.54: When a player opens a game on a new device, the client MUST fetch the
  current game state via `GET /api/v1/games/{game_id}` to sync.

---

## 10. Anonymous Play

### 10.1 Capabilities

| Capability | Anonymous | Registered |
|------------|-----------|------------|
| Start a game | ✅ | ✅ |
| Play turns | ✅ | ✅ |
| Save progress | ❌ (auto-expires) | ✅ |
| Multiple games | 1 max | 5 max |
| Resume after browser close | ❌ (token in memory only) | ✅ |
| Preferences | Defaults only | Full customization |
| Account deletion (GDPR) | N/A (auto-cleanup) | ✅ |

### 10.2 Rules

- FR-11.55: Anonymous players MUST be able to play a complete game session without
  creating an account.
- FR-11.56: Anonymous players MUST be limited to 1 active game.
- FR-11.57: Anonymous game sessions MUST expire after 24 hours of inactivity (shorter
  than registered players).
- FR-11.58: When an anonymous player upgrades to a registered account (see §5.3), their
  active game MUST be seamlessly transferred.
- FR-11.59: Anonymous player records and their game data MUST be automatically cleaned
  up after 30 days of inactivity.

---

## 11. Account Deletion (GDPR)

### 11.1 Endpoint

#### `DELETE /api/v1/players/me`

**Behavior:**
- FR-11.60: Upon receiving a deletion request, the player's status MUST be set to
  "deleted" immediately.
- FR-11.61: All active game sessions MUST be ended.
- FR-11.62: The following data MUST be permanently erased within 72 hours:
  - Email address
  - Password hash
  - Display name
  - Player preferences
  - Turn history (player input and narrative responses)
  - Game state snapshots
- FR-11.63: The following data MAY be retained in anonymized form:
  - Aggregate gameplay statistics (turn counts, session durations)
  - World state changes caused by the player (for world continuity)
- FR-11.64: The `player_id` MUST be retained as a tombstone to prevent reuse.
- FR-11.65: Deletion MUST be irreversible. There is no "undo delete" flow.
- FR-11.66: The player MUST receive a confirmation response with a summary of what will
  be deleted and the timeline.

### 11.2 Edge Cases

- EC-11.01: If a player requests deletion while a game turn is in progress, the turn
  MUST be allowed to complete before deletion proceeds.
- EC-11.02: If a player requests deletion and then the deletion job fails, the system
  MUST retry automatically and alert an admin after 3 failures.

---

## 12. Security Considerations

- FR-11.67: Password hashing MUST use bcrypt with a cost factor of at least 12.
- FR-11.68: Passwords MUST be validated for minimum complexity (8+ characters, at least
  one letter and one number).
- FR-11.69: Failed login attempt counts MUST be stored in Redis with a TTL of 15 minutes.
- FR-11.70: Account lockout MUST be temporary (15 minutes) and MUST NOT require admin
  intervention to unlock.
- FR-11.71: All authentication events (login, logout, registration, upgrade, deletion)
  MUST be logged with timestamp, player_id, IP address (hashed), and result.
- FR-11.72: Auth logs MUST NOT contain passwords, tokens, or other secrets.
- FR-11.73: The token deny-list in Redis MUST have TTLs matching token expiration to
  prevent unbounded memory growth.

---

## 13. Acceptance Criteria

### Identity

- **AC-11.01**: A visitor can start playing within 5 seconds by hitting the anonymous auth
  endpoint and creating a game.
- **AC-11.02**: An anonymous player who upgrades to a registered account retains their
  player_id and active game session.
- **AC-11.03**: A registered player can log in from two different browsers and see the same
  game list.

### Session Lifecycle

- **AC-11.04**: A game transitions from `created` to `active` on the first turn submission.
- **AC-11.05**: A paused game can be resumed after 29 days (within the 30-day window).
- **AC-11.06**: A game paused for 31 days is found in `expired` state.
- **AC-11.07**: An expired game can still be resumed with a "welcome back" experience.
- **AC-11.08**: A `created` game with no turns is found in `abandoned` state after 25 hours.

### Auth Security

- **AC-11.09**: After 5 failed login attempts, the 6th attempt returns `429 Too Many Requests`
  regardless of whether the password is correct.
- **AC-11.10**: A reused refresh token triggers invalidation of all tokens for that player.
- **AC-11.11**: A deleted player's credentials cannot be used to log in.
- **AC-11.12**: No API response ever contains a password or password hash.

### Data Deletion

- **AC-11.13**: After account deletion, the player's email, name, and turn history are not
  retrievable via any API endpoint or direct database query within 72 hours.
- **AC-11.14**: The deleted player's `player_id` cannot be reassigned to a new player.

### Gherkin Scenarios

Scenario: Anonymous player starts a game without registering

Given a new visitor with no existing session
When the visitor calls POST /api/v1/auth/anonymous
Then the response status is 201
And the response body contains a valid player_id and access_token
When the visitor calls POST /api/v1/games with the access_token
Then a new game is created in "created" state

Scenario: Anonymous player upgrades to a registered account

Given an anonymous player with player_id "anon-001" and an active game
When the player calls POST /api/v1/auth/upgrade with email and password
Then the response status is 200
And the player_id remains "anon-001"
And the active game is still accessible under the same game_id

Scenario: Game session lifecycle transitions

Given a registered player with a game in "created" state
When the player submits their first turn via POST /api/v1/games/{id}/turns
Then the game state transitions to "active"
When the player calls POST /api/v1/games/{id}/pause
Then the game state transitions to "paused"
When 31 days pass with no interaction
Then the game state transitions to "expired"
When the player calls POST /api/v1/games/{id}/resume
Then the game state transitions to "active" with a "welcome back" narrative

Scenario: Login lockout after repeated failures

Given a registered player with email "player@example.com"
When 5 consecutive login attempts are made with an incorrect password
Then each attempt returns 401 Unauthorized
When a 6th login attempt is made (even with the correct password)
Then the response status is 429 Too Many Requests
And the response includes a Retry-After header

---

## 14. Out of Scope

- **OAuth 2.0 / OpenID Connect provider** — TTA authenticates players directly; federation with external identity providers is post-v1 — deferred
- **SAML / SSO integration** — enterprise federation — not planned for v1
- **Multi-factor authentication (MFA)** — adds friction to a game context; revisit for admin/operator accounts — deferred
- **Social login** (Google, Discord, etc.) — reduces friction but adds external dependency — deferred to post-v1
- **Fine-grained permission system** — v1 has two roles (player, admin); RBAC/ABAC beyond that is deferred
- **Password-based registration for v1** — only anonymous + optional upgrade flow; full registration deferred to follow-up spec
- **Email verification / notification** — deferred; see OQ-11.03
- **Account linking** (merge two anonymous identities) — deferred to post-v1

---

## 15. Open Questions

- OQ-11.01: Should anonymous players be able to set a display name? Leaning yes — low
  cost, nice personalization.
- OQ-11.02: Should we support "guest links" where a registered player can share a
  read-only view of their game? Deferred to post-v1.
- OQ-11.03: Should we implement email verification for registration? Adds friction but
  improves data quality. Leaning toward optional for v1.
- OQ-11.04: Should expired games count toward the 5-game limit? Leaning no — only
  `active` and `paused` games count.
- OQ-11.05: Should we support password reset via email for v1? Yes, but spec deferred
  to a follow-up addendum.

---

## v1 Closeout (Non-normative)

> This section is retrospective and non-normative. It documents what shipped in the v1
> baseline, what was verified, what gaps were found, and what is deferred to v2.
> It does not change any requirements or acceptance criteria.

### What Shipped

- **Anonymous player registration** with consent enforcement, required categories, and 13+
  age confirmation (FR-11.01, FR-11.02)
- **JWT-based auth** — short-lived access token + refresh token issued on registration
  (FR-11.04)
- **Authenticated session** via `Authorization: Bearer` header; `get_current_player`
  dependency enforces token validity (FR-11.10)
- **Session index** — Redis sorted-set tracking player session list (FR-11.12;
  `GET /api/v1/auth/sessions`)
- **Soft-delete player** — marks player as `deleted` and enqueues GDPR erasure (FR-11.02)
- **Consent version tracking** — registration stores consent version + categories

### Evidence

- AC-11.01 (registration), AC-11.02 (consent), AC-11.04 (JWT), AC-11.10 (auth header),
  AC-11.12 (session index) — exercised in `tests/unit/api/test_s11_ac_compliance.py`
- BDD scenarios: `register anonymous player`, `register with missing consent` pass
- Redis sorted-set session index: PR #149 (wave-30)

### Gaps Found in v1

1. **No login endpoint** — AC-11.03 (multi-device) and AC-11.09 (lockout) both require
   a login endpoint that was deferred; anonymous-only registration is the v1 path
2. **No session expiry background job** — AC-11.05/11.06/11.08 (game pause/expire/abandon
   after N days) are not implemented; no cron or background task wired
3. **No async deletion job** — AC-11.13 (`data not retrievable within 72 h`) requires an
   async worker; v1 soft-deletes but does not physically purge
4. **DB constraint only** for AC-11.14 (deleted `player_id` not reassignable) — not
   unit-asserted

### Deferred to v2

| AC | Feature | Reason |
|----|---------|--------|
| AC-11.03 | Multi-device login | Login endpoint deferred (anonymous-only in v1) |
| AC-11.05–11.08 | Session/game expiry background jobs | Background task infrastructure |
| AC-11.09 | Login lockout | Login endpoint deferred |
| AC-11.11 | Deleted player cannot login | Login endpoint deferred |
| AC-11.13 | Data not retrievable within 72 h | Async deletion job |
| AC-11.14 | `player_id` not reassignable | DB constraint assertion |

### Lessons for v2

- Login endpoint is a hard prerequisite for retention features (AC-11.03, 11.09, 11.11)
- Background job infrastructure (for session expiry, GDPR purge) should be specced before
  those ACs are claimed as done
