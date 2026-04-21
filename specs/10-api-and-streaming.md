# S10 — API & Streaming

> **Status**: 📝 Draft
> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ⚠️ Partial
> **Level**: 3 — Platform
> **Dependencies**: S04 (World Model), S11 (Player Identity & Sessions), S12 (Persistence Strategy)
> **Last Updated**: 2026-04-07

---

## 1. Purpose

This spec defines the HTTP API surface and real-time streaming protocol for TTA. It is the
single contract between the game client and the server. Every player action, every narrative
response, and every piece of game state flows through this API.

TTA ships as a **single FastAPI application** with role-based access control — not a
constellation of microservices. This keeps the operational surface small and the developer
experience simple for an OSS-first project.

---

## 2. Design Philosophy

### 2.1 Two Protocols, Clear Boundaries

| Protocol | Used For | Direction |
|----------|----------|-----------|
| **REST (HTTP)** | Commands, queries, CRUD operations | Request → Response |
| **SSE (EventSource)** | Streaming narrative, live game events | Server → Client |

REST handles discrete actions: submit a turn, fetch a profile, list saved games.
SSE handles continuous output: the narrative stream that unfolds as the AI generates a
response, plus game events that arrive asynchronously.

### 2.2 Principles

- **Resource-oriented**: endpoints name nouns (`/games`, `/players`), not verbs
- **Predictable**: consistent naming, consistent error shapes, consistent pagination
- **Streaming-native**: narrative is always streamed, never returned as a single blob
- **Offline-tolerant**: clients can reconnect to SSE and resume without data loss
- **Documentation-as-code**: OpenAPI spec is auto-generated from the running application

---

## 3. User Stories

### Player-Facing

> **US-10.1** — As a player, I can submit a turn and immediately begin receiving streamed
> narrative so the game feels responsive even when the AI is still generating.

> **US-10.2** — As a player, I can reconnect after a network drop and resume receiving the
> current narrative stream from where I left off.

> **US-10.3** — As a player, I see clear, understandable error messages when something goes
> wrong — never raw stack traces or cryptic codes.

> **US-10.4** — As a player, I can fetch my game state at any time to re-render the UI
> without replaying the entire session.

> **US-10.5** — As a player on a slow connection, I receive SSE keep-alive signals so my
> browser does not close the connection prematurely.

### Developer-Facing

> **US-10.6** — As a front-end developer, I can discover all available endpoints, their
> request/response shapes, and error codes via auto-generated API documentation.

> **US-10.7** — As an integration developer, I can version my client against a stable API
> contract that does not break without a version bump.

> **US-10.8** — As an operator, I can call health-check and readiness endpoints to
> determine whether the service is alive and ready to accept traffic.

### Admin-Facing

> **US-10.9** — As an admin, I can access admin-only endpoints that are invisible and
> inaccessible to regular players.

> **US-10.10** — As an admin, I can view rate-limit metrics to identify abuse patterns.

---

## 4. API Versioning

### 4.1 Strategy: URL Path Prefix

All endpoints are prefixed with `/api/v1/`. This is the simplest, most visible versioning
strategy and aligns with OSS-first goals (easy to understand, easy to curl).

```
/api/v1/games
/api/v1/players/me
/api/v1/turns
```

### 4.2 Version Lifecycle

| Phase | Meaning |
|-------|---------|
| **Current** | The active, supported version. All new features land here. |
| **Deprecated** | Still functional, but clients should migrate. Sunset date published. |
| **Removed** | Returns `410 Gone` with a migration pointer. |

### 4.3 Rules

- FR-10.01: Breaking changes MUST increment the version number.
- FR-10.02: Additive changes (new fields, new endpoints) MAY ship without a version bump.
- FR-10.03: Deprecated versions MUST remain functional for at least 90 days after
  deprecation is announced.
- FR-10.04: Responses from deprecated endpoints MUST include a `Deprecation` header with
  the sunset date.

---

## 5. Core Endpoints

### 5.1 Turn Submission

The heart of gameplay. A player submits text; the server processes it through the agent
pipeline and streams narrative back.

#### `POST /api/v1/games/{game_id}/turns`

**Request shape:**
- `input` (string, required): the player's natural-language input, 1–2000 characters
- `metadata` (object, optional): client-side context (e.g. UI state, timing data)

**Response:** `202 Accepted` with:
- `turn_id` (string): unique identifier for this turn
- `stream_url` (string): SSE endpoint URL to connect for this turn's narrative
- `turn_number` (integer): the sequential turn count in this game

**Behavior:**
- FR-10.05: The endpoint MUST return `202 Accepted` before the AI begins generating,
  within 500ms of receiving the request.
- FR-10.06: The `stream_url` MUST be valid for at least 5 minutes after the turn is
  accepted.
- FR-10.07: If a turn is already in progress for this game, the server MUST return
  `409 Conflict` with a message indicating the active turn.
- FR-10.08: Empty or whitespace-only input MUST be rejected with `400 Bad Request`
  and error category `input_invalid` (per S23 FR-23.01).
- FR-10.09: Input exceeding 2000 characters MUST be rejected with `422`.

### 5.2 Session / Game Management

#### `POST /api/v1/games`

Create a new game session.

**Request shape:**
- `world_id` (string, optional): which world to play in; defaults to the system default
- `preferences` (object, optional): player preferences for this session

**Response:** `201 Created` with:
- `game_id`, `world_id`, `status` ("active"), `created_at`, `turn_count` (0)

**Behavior:**
- FR-10.10: A player MUST NOT have more than 5 active games simultaneously.
- FR-10.11: Creating a game MUST initialize a session in the session store (see S12).

#### `GET /api/v1/games`

List the authenticated player's games.

**Response shape:** paginated list of game summaries:
- `game_id`, `world_id`, `status`, `turn_count`, `created_at`, `last_active_at`

**Behavior:**
- FR-10.12: Results MUST be ordered by `last_active_at` descending by default.
- FR-10.13: Results MUST support cursor-based pagination.
- FR-10.14: Only games belonging to the authenticated player are returned.

#### `GET /api/v1/games/{game_id}`

Get full game state for a specific game.

**Response shape:**
- Game metadata (id, world, status, turn count, timestamps)
- Current location summary (name, description, exits)
- Recent conversation history (last N turns — configurable, default 10)
- Active game state snapshot (inventory, character status)

**Behavior:**
- FR-10.15: The response MUST contain enough state for a client to fully render the game
  UI without any additional requests.
- FR-10.16: Returns `404 Not Found` if the game does not exist or does not belong to the
  authenticated player.

#### `PATCH /api/v1/games/{game_id}`

Update game status (pause, resume).

**Request shape:**
- `status` (string): one of "paused", "active"

**Behavior:**
- FR-10.17: Only transitions defined in the session lifecycle (see S11) are valid.
- FR-10.18: Invalid transitions MUST return `422 Unprocessable Entity`.

#### `DELETE /api/v1/games/{game_id}`

End and archive a game.

**Behavior:**
- FR-10.19: This is a soft delete. Game data is retained for the player's history but the
  game transitions to "abandoned" status (per S27 FR-27.16).
- FR-10.20: An abandoned game MUST NOT accept new turns.

### 5.3 Player Profile

#### `GET /api/v1/players/me`

Get the authenticated player's profile.

**Response shape:**
- `player_id`, `display_name`, `email` (masked), `preferences`, `created_at`

#### `PATCH /api/v1/players/me`

Update profile or preferences.

**Request shape:**
- `display_name` (string, optional)
- `preferences` (object, optional): theme, text speed, content sensitivity settings

**Behavior:**
- FR-10.21: Display names MUST be 1–50 characters, alphanumeric plus spaces and hyphens.
- FR-10.22: Preferences MUST be validated against a known schema; unknown keys are ignored.

### 5.4 Health & Operations

#### `GET /api/v1/health`

Health probe. Canonical response semantics are defined in S23 FR-23.23/24.

**Behavior:**
- FR-10.23: This endpoint contract (status model, checks, and dependency semantics) is
  defined by S23 FR-23.23/FR-23.24.
- FR-10.24: This endpoint MUST NOT require authentication.

#### `GET /api/v1/health/ready`

Readiness probe. Canonical response semantics are defined in S23 FR-23.25.

**Behavior:**
- FR-10.25: This endpoint contract (readiness gating and required services) is defined
  by S23 FR-23.25.
- FR-10.26: If any backend is unreachable, return `503 Service Unavailable` with the
  failing check identified.
- FR-10.27: This endpoint MUST NOT require authentication.

---

## 6. SSE Streaming Contract

### 6.1 Connection

#### `GET /api/v1/games/{game_id}/stream`

Opens an SSE connection scoped to a specific game. The client receives all events for
that game: narrative chunks, game state updates, errors.

**Headers required:**
- `Authorization: Bearer <token>` — player's auth token
- `Accept: text/event-stream`
- `Last-Event-ID` (optional) — for reconnection, the last event ID received

**Behavior:**
- FR-10.28: The server MUST validate the auth token before establishing the SSE connection.
- FR-10.29: The server MUST verify the game belongs to the authenticated player.
- FR-10.30: The connection MUST remain open as long as the game is active, subject to
  keep-alive and timeout rules.

### 6.2 Event Types

| Event Type | Purpose | Data Shape |
|------------|---------|------------|
| `narrative` | A chunk of AI-generated narrative text | `{text, turn_id, sequence}` |
| `narrative_end` | Signals the end of a narrative stream | `{turn_id, total_chunks}` |
| `state_update` | Game state has changed | `{changes: [...]}` |
| `location_change` | Player has moved to a new location | `{location_id, name, description, exits}` |
| `error` | An error occurred during processing | `{code, message, turn_id}` |
| `heartbeat` | Keep-alive signal | `{timestamp}` |

### 6.3 Event Format

All events follow the SSE specification (RFC 8895):

```
id: <monotonic_event_id>
event: <event_type>
data: <JSON_payload>

```

- FR-10.31: Every event MUST include a unique, monotonically increasing `id` field.
- FR-10.32: The `data` field MUST be valid JSON.
- FR-10.33: Multi-line data MUST be split across multiple `data:` lines per the SSE spec.

### 6.4 Narrative Streaming

When a turn is submitted, the narrative is streamed as a sequence of `narrative` events
followed by a single `narrative_end` event.

- FR-10.34: Each `narrative` event MUST contain a `sequence` number starting from 0 for
  each turn.
- FR-10.35: The `narrative_end` event MUST contain `total_chunks` matching the number of
  `narrative` events sent.
- FR-10.36: If the AI generation fails mid-stream, an `error` event MUST be sent with
  the `turn_id` and the stream MUST continue accepting future turns.
- FR-10.37: Narrative chunks SHOULD be sentence-aligned where possible, not arbitrary
  byte boundaries.

### 6.5 Keep-Alive

- FR-10.38: The server MUST send a `heartbeat` event at least every 15 seconds during
  idle periods.
- FR-10.39: The heartbeat interval MUST be configurable via server settings.
- FR-10.40: If the server detects the client has disconnected (write fails), it MUST
  clean up the connection resources within 5 seconds.

### 6.6 Reconnection

- FR-10.41: When a client reconnects with `Last-Event-ID`, the server MUST replay any
  events after that ID that are still in the buffer.
- FR-10.42: The server MUST maintain an event buffer of at least the last 100 events or
  5 minutes of events, whichever is larger.
- FR-10.43: The server MUST send a `retry:` field in the initial connection response,
  suggesting a reconnection delay (default: 3000ms).
- FR-10.44: If the requested `Last-Event-ID` is no longer in the buffer, the server MUST
  send a `state_update` event with a full state snapshot before resuming normal events.

---

## 7. Request & Response Schemas

### 7.1 General Shape Conventions

**Successful responses:**
```
{
  "data": { ... },          // the resource or result
  "meta": {                 // optional metadata
    "cursor": "...",        // pagination cursor
    "count": 42             // total count (where applicable)
  }
}
```

**Collection responses:**
```
{
  "data": [ ... ],
  "meta": {
    "next_cursor": "...",
    "has_more": true
  }
}
```

- FR-10.45: All successful responses MUST wrap the payload in a `data` key.
- FR-10.46: Collection responses MUST include `meta.has_more` for pagination.

### 7.2 Timestamps

- FR-10.47: All timestamps MUST be ISO 8601 format in UTC (e.g., `2025-07-24T12:00:00Z`).
- FR-10.48: All timestamp fields MUST use the suffix `_at` (e.g., `created_at`).

### 7.3 Identifiers

- FR-10.49: All resource IDs MUST be opaque strings (UUIDs or ULIDs).
- FR-10.50: Clients MUST NOT parse or construct IDs; they are opaque handles.

---

## 8. Error Responses

### 8.1 Standard Error Shape

```
{
  "error": {
    "code": "TURN_IN_PROGRESS",
    "message": "A turn is already being processed for this game.",
    "details": { ... },     // optional, context-specific
    "correlation_id": "..." // trace identifier
  }
}
```

- FR-10.51: All error responses MUST use the `error` wrapper.
- FR-10.52: The `code` field MUST be a stable, machine-readable string (UPPER_SNAKE_CASE).
- FR-10.53: The `message` field MUST be a human-readable explanation safe to display.
- FR-10.54: Every error response MUST include a `correlation_id` for tracing (matching
  the request correlation ID semantics in S23 FR-23.03).

### 8.2 HTTP Status Code Usage

| Status | Meaning in TTA |
|--------|---------------|
| `200` | Successful retrieval or update |
| `201` | Resource created |
| `202` | Turn accepted, processing asynchronously |
| `400` | Malformed request or `input_invalid` category errors |
| `401` | Missing or invalid authentication |
| `403` | Authenticated but not authorized for this resource |
| `404` | Resource not found (or not owned by this player) |
| `409` | Conflict (e.g., turn already in progress) |
| `422` | Semantically invalid request (valid JSON but bad values) |
| `429` | Rate limit exceeded |
| `500` | Unexpected server error |
| `503` | Service unavailable (backend dependency down) |

- FR-10.55: `404` MUST be returned for resources that don't exist AND for resources the
  player doesn't own (to avoid leaking existence).
- FR-10.56: `500` responses MUST NOT include stack traces, internal paths, or
  implementation details.

---

## 9. Authentication Integration

Authentication is defined in S11. This section specifies how auth tokens flow through
the API.

- FR-10.57: All endpoints except `/api/v1/health`, `/api/v1/health/ready`, and
  `/api/v1/auth/*` MUST require
  a valid `Authorization: Bearer <token>` header.
- FR-10.58: SSE connections MUST validate the token at connection time. If the token
  expires during an active SSE connection, the connection MAY remain open until the next
  event or heartbeat, then MUST close with an appropriate error event.
- FR-10.59: The API MUST extract the `player_id` from the token, never from query
  parameters or request bodies (for ownership-scoped endpoints).
- FR-10.60: Token validation failures MUST return `401 Unauthorized` with error code
  `AUTH_TOKEN_INVALID` or `AUTH_TOKEN_EXPIRED`.

---

## 10. Rate Limiting

### 10.1 Limits

| Scope | Limit | Window |
|-------|-------|--------|
| Turn submission | 10 requests | per minute per player |
| Game creation | 5 requests | per hour per player |
| Profile reads | 60 requests | per minute per player |
| Profile updates | 10 requests | per hour per player |
| SSE connections | 3 concurrent | per player |
| General API | 120 requests | per minute per player |

### 10.2 Behavior

- FR-10.61: Rate limit state MUST be tracked per authenticated player, not per IP.
- FR-10.62: Rate-limited responses MUST return `429 Too Many Requests`.
- FR-10.63: Rate-limited responses MUST include `Retry-After` header (seconds until
  the window resets).
- FR-10.64: All responses MUST include rate-limit headers:
  - `X-RateLimit-Limit`: the limit for this endpoint
  - `X-RateLimit-Remaining`: remaining requests in the current window
  - `X-RateLimit-Reset`: Unix timestamp when the window resets

### 10.3 Edge Cases

- FR-10.65: If a player has multiple active SSE connections at the limit (3), new SSE
  connection attempts MUST return `429` with a message indicating the concurrent limit.
- FR-10.66: Rate limits MUST NOT apply to health and readiness endpoints.

---

## 11. CORS Configuration

- FR-10.67: The API MUST support CORS for browser-based clients.
- FR-10.68: Allowed origins MUST be configurable via environment variables.
- FR-10.69: In development mode, `*` (all origins) MAY be permitted.
- FR-10.70: In production, only explicitly listed origins MUST be accepted.
- FR-10.71: CORS preflight responses MUST allow the following headers:
  `Authorization`, `Content-Type`, `Accept`, `Last-Event-ID`.
- FR-10.72: CORS MUST allow `GET`, `POST`, `PATCH`, `DELETE`, `OPTIONS` methods.

---

## 12. API Documentation

- FR-10.73: The API MUST expose an OpenAPI 3.1 specification at `/api/v1/openapi.json`.
- FR-10.74: Interactive documentation MUST be available at `/api/v1/docs` (Swagger UI).
- FR-10.75: Every endpoint MUST include a summary, description, and example
  request/response in the OpenAPI spec.
- FR-10.76: Error responses MUST be documented in the OpenAPI spec for each endpoint.
- FR-10.77: The OpenAPI spec MUST include security scheme definitions matching the
  authentication strategy in S11.

---

## 13. Edge Cases & Failure Modes

### 13.1 Network Failures During Streaming

- EC-10.01: If the AI pipeline fails after streaming has begun, the server MUST send an
  `error` event indicating the failure and a `narrative_end` event with whatever was
  produced. The game state MUST NOT advance on a failed turn.
- EC-10.02: If the server crashes during streaming, the client's EventSource will
  automatically attempt reconnection. On reconnect, the server MUST replay buffered
  events or provide a state snapshot.

### 13.2 Concurrent Requests

- EC-10.03: If a player submits two turns simultaneously, the second MUST receive
  `409 Conflict`. The API is turn-sequential per game.
- EC-10.04: Different games for the same player MAY process turns concurrently.

### 13.3 Stale State

- EC-10.05: If a client fetches game state while a turn is being processed, the response
  MUST reflect the last completed state, not the in-progress state.
- EC-10.06: The response SHOULD include a `processing_turn` field if a turn is currently
  in progress.

### 13.4 Large Payloads

- EC-10.07: Request bodies exceeding 64KB MUST be rejected with `413 Payload Too Large`.
- EC-10.08: Narrative responses have no server-imposed length limit, but SSE chunking
  ensures memory usage stays bounded.

### 13.5 SSE Backpressure

- EC-10.09: If the client reads SSE events slower than the server produces them, the
  server MUST buffer events in memory up to `SSE_BUFFER_MAX_EVENTS` (default: 500).
  If the buffer is full, the server MUST drop the connection and log a warning rather
  than consuming unbounded memory.
- EC-10.10: The server SHOULD track per-connection send-queue depth and expose it as a
  metric for monitoring.

### 13.6 Client Disconnect During Generation

- EC-10.11: If the client disconnects while the AI pipeline is still generating, the
  server MUST cancel or abandon the in-flight generation within
  `SSE_ORPHAN_TIMEOUT_SECONDS` (default: 30). The partial narrative MUST NOT be
  committed to game state.
- EC-10.12: On disconnect, the SSE handler MUST release its Redis Pub/Sub subscription
  immediately — no leaked subscriptions.

### 13.7 Reconnection With Expired Buffer

- EC-10.13: If a client reconnects with a `Last-Event-ID` that is no longer in the
  server's replay buffer, the server MUST respond with an `error` event containing
  `replay_unavailable` and then send a full state snapshot so the client can
  resynchronize without data loss.

---

## 14. Acceptance Criteria

### API Surface

- **AC-10.01**: A new player can create an account, start a game, submit a turn, and receive
  streamed narrative — using only documented API endpoints.
- **AC-10.02**: The OpenAPI spec is valid (passes `openapi-spec-validator`).
- **AC-10.03**: Every endpoint returns the documented error shape for all error conditions.

### Streaming

- **AC-10.04**: SSE narrative stream begins delivering chunks within 2 seconds of turn
  submission (measured from the `202 Accepted` response to first `narrative` event).
- **AC-10.05**: A client that disconnects and reconnects within 30 seconds receives all
  missed events without data loss.
- **AC-10.06**: Keep-alive heartbeats arrive at least every 15 seconds during idle.

### Rate Limiting

- **AC-10.07**: A player who exceeds the turn submission rate limit receives `429` with a
  valid `Retry-After` header.
- **AC-10.08**: Rate limit headers are present on every authenticated response.

### Error Handling

- **AC-10.09**: No API response ever contains stack traces, file paths, or internal
  implementation details.
- **AC-10.10**: Every error response includes a `correlation_id` that can be found in
  server logs.
- **AC-10.13**: Submitting a turn with empty or whitespace-only input returns `400` with
  error category `input_invalid`.

### Security

- **AC-10.11**: Unauthenticated requests to protected endpoints return `401`, not `403` or
  `404`.
- **AC-10.12**: A player cannot access another player's game via direct URL manipulation —
  the API returns `404`.

---

## 15. Out of Scope

- **WebSocket protocol** — SSE is sufficient for server-to-client streaming; bidirectional WebSocket adds complexity without v1 benefit — deferred to post-v1
- **GraphQL API** — REST + SSE covers all v1 access patterns; GraphQL would duplicate the surface — not planned
- **API gateway / reverse proxy configuration** — deployment-level concern — handled in S14
- **Admin dashboard UI** — this spec defines the admin API endpoints, not a front-end — deferred
- **Client SDK / generated clients** — OpenAPI spec enables codegen, but shipping an official SDK is post-v1 — deferred
- **Long-polling fallback** — alternative to SSE for restricted environments — deferred to post-v1 (see OQ-10.02)
- **Webhook / callback integrations** — external event delivery — not planned for v1
- **File upload endpoints** — no v1 use case requires binary uploads — not planned

---

## 16. Open Questions

- OQ-10.01: Should the SSE stream be per-game or per-player? Per-game is simpler but
  means multiple connections for multi-game views. Current design: per-game.
- OQ-10.02: Should we support long-polling as a fallback for environments where SSE is
  blocked? Deferred to post-v1.
- OQ-10.03: What is the maximum narrative length before we should truncate or paginate
  within the stream? Needs playtesting data.
- OQ-10.04: Should admin endpoints live under `/api/v1/admin/` or use the same paths
  with role-based visibility? Leaning toward separate prefix for clarity.

---

## 17. Migration Notes (Issue #128)

- **Input validation status alignment**: `FR-10.08` now requires `400 input_invalid`
  (instead of `422`) to align with S23's canonical error taxonomy.
- **Lifecycle alignment**: `DELETE /api/v1/games/{game_id}` now normatively maps to
  `abandoned` (soft-delete) per S27, rather than `ended`.
- **Health/readiness path + ownership alignment**: S10 now defines canonical public paths
  (`/api/v1/health`, `/api/v1/health/ready`) and delegates behavior semantics to S23.
- **Error envelope identifier alignment**: `correlation_id` is canonical in the error
  envelope. Implementations MAY continue to source it from `request.state.request_id`
  internally, but response field naming is `correlation_id`.

---

## v1 Closeout (Non-normative)

> This section is retrospective and non-normative. It documents what shipped in the v1
> baseline, what was verified, what gaps were found, and what is deferred to v2.
> It does not change any requirements or acceptance criteria.

### What Shipped

- **Single FastAPI process** with SSE streaming via `/api/v1/games/{id}/turns` (FR-10.01, FR-10.03)
- **Turn endpoint** accepting player input and streaming LLM narrative back chunk-by-chunk
- **Health & readiness endpoints** at `/api/v1/health` and `/api/v1/health/ready` (FR-10.09, FR-10.10)
- **Error envelope** with `correlation_id` field aligned to S23 (FR-10.11, FR-10.12)
- **RBAC stubs** — anonymous player token required for game actions (FR-10.07)
- **`/api/v1/games`** create/list/get/delete routes (soft-delete to `abandoned` per S27)

### Evidence

- 100 unit tests pass across S10/S11/S12/S13/S27 compliance suites (4.16 s)
- AC-10.01 (POST /games), AC-10.03 (POST /turns), AC-10.07 (auth), AC-10.09/10.10 (health),
  AC-10.11/10.12 (error envelope) — all exercised in `tests/unit/api/test_s10_ac_compliance.py`
- BDD scenario `play a complete game turn via SSE` passes in `tests/bdd/`
- PR #161 sim: 11/11 turns completed, SSE chunks received end-to-end

### Gaps Found in v1

1. **No SSE reconnect** — AC-10.05 (missed events within 30 s) not implemented; Redis pub/sub
   replay absent; client disconnect loses buffered events permanently
2. **No timing SLA validation** — AC-10.04 (chunk < 2 s) and AC-10.06 (heartbeat every 15 s)
   measured in unit tests by config value, not real-time observation
3. **No OpenAPI validation** — AC-10.02 requires `openapi-spec-validator` tooling; schema drift
   between code and spec not caught automatically
4. **No rate-limit headers** — AC-10.08 (`X-RateLimit-*` on every authenticated response)
   deferred; middleware not wired

### Deferred to v2

| AC | Feature | Reason |
|----|---------|--------|
| AC-10.02 | OpenAPI spec-validator in CI | Tooling/CI setup |
| AC-10.04 | Real-time chunk-delivery SLA (< 2 s) | Requires integration harness |
| AC-10.05 | SSE reconnect + missed-event replay | Redis pub/sub architecture |
| AC-10.06 | SSE heartbeat every 15 s in prod | Integration timing |
| AC-10.08 | `X-RateLimit-*` headers on every auth response | Rate-limit middleware (S25) |

### Lessons for v2

- SSE reconnect is the single most impactful reliability gap for players; prioritise in v2
- `openapi-spec-validator` CI step is cheap to add and prevents schema drift
- Heartbeat interval is configurable (15 s default) but untested under load
