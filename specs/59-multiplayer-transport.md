# S59 — Multiplayer Transport

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v4+
> **Implementation Fit**: ❌ Not Started
> **Level**: 3 — Platform
> **Dependencies**: S57 (Multi-Actor Universe Model), S58 (Turn Conflict Resolution), S10 (API and Streaming), S49 (Horizontal Scaling)
> **Related**: S11 (Session Management), S23 (Error Handling)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

S59 defines the real-time transport layer for multiplayer sessions: the
WebSocket protocol, message schema, connection lifecycle, and horizontal
scaling considerations for actors who share a universe (S57).

In v1, players receive narrative via SSE (S10). SSE is unidirectional
(server → client) and per-session. Multiplayer requires:
1. **Bidirectional communication** (actors submit turns in real-time)
2. **Session-independent channels** (a player can remain connected even
   between turns)
3. **Actor-scoped fan-out** (world events broadcast to all actors in a universe)

---

## 2. Library Choice

> **OQ-59.01 resolved**: `websockets` (pure-asyncio, no dependencies)

Rationale: TTA already runs a single FastAPI process. FastAPI supports WebSocket
endpoints natively via Starlette's `WebSocket` class, which wraps the `websockets`
library. No additional process or service is required. The choice is:
- `websockets` via FastAPI/Starlette native — **selected**
- `socket.io` — rejected (Node.js heritage; Python library is less maintained)
- `channels` — rejected (Django-specific)

---

## 3. WebSocket Endpoint

```
WS /api/v1/play/ws?session_token={token}
```

Authentication: JWT session token in query param (WebSocket headers are
browser-constrained; query param is standard practice).

The endpoint is behind the same rate-limit middleware as REST endpoints (S25).

---

## 4. Message Schema

All messages are JSON. Messages have a `type` field that determines the schema
of the `payload` field.

### 4.1 Client → Server

| Type | Payload | Description |
|---|---|---|
| `turn_submit` | `{action: str, context?: dict}` | Actor submits a turn |
| `ping` | `{}` | Keepalive |
| `depart` | `{destination?: str}` | Actor voluntarily leaves universe |

### 4.2 Server → Client

| Type | Payload | Description |
|---|---|---|
| `turn_result` | `{narration: str, world_delta: dict, choices: list}` | Turn outcome |
| `world_event` | `{event_type: str, description: str}` | World-state change visible to actor |
| `actor_joined` | `{actor_id, display_name}` | Another actor joined the universe |
| `actor_departed` | `{actor_id, display_name}` | Another actor left |
| `bleedthrough` | `{fragment: str}` | Ambient bleedthrough event (S55) |
| `error` | `{code: str, message: str}` | Error (see S23) |
| `pong` | `{}` | Keepalive response |

---

## 5. Connection Lifecycle

```
Client → WS CONNECT → authenticate → join actor roster (S57) → receive world_event:welcome
Client → turn_submit → [S58 conflict window] → turn_result delivered
Client → depart → actor departed from roster → WS CLOSE (graceful)
```

On **abnormal disconnect** (network drop, browser close):
- Actor slot transitions to `idle` (S57 FR-57.05)
- Unprocessed turn_submit is cancelled
- Actor removal timeout begins (30 min)

---

## 6. Horizontal Scaling

WebSocket connections are stateful (one connection per actor, affinity required).
Following S49's SSE affinity pattern, the first WS response sets a
`fly-force-instance-id` cookie (Fly.io) that pins the actor to their instance.

For cross-instance world events (e.g., Actor A on instance 1 takes an action
that Actor B on instance 2 must see), the event is published via the S54
substrate. Each instance subscribes to universe-scoped channels and forwards
world events to locally-connected actors.

---

## 7. Functional Requirements

### FR-59.01 — WebSocket Endpoint

A `WS /api/v1/play/ws` endpoint is added to the FastAPI application.
Connection authentication uses the same JWT validation as REST endpoints.

### FR-59.02 — Turn Submit via WebSocket

A `turn_submit` message triggers the same turn pipeline as a REST `POST /play/turn`
call. The WebSocket handler awaits the turn result and sends it back as a
`turn_result` message. SSE delivery (v1 path) remains available for backward
compatibility.

### FR-59.03 — World Event Fan-Out

When any actor in a universe produces a world-state delta, the delta is published
to S54 and each connected actor on the instance receives a `world_event` message.
Fan-out MUST complete within 200 ms of the originating turn completing.

### FR-59.04 — Keepalive

The server sends a `pong` in response to every `ping`. Connections with no
activity (no ping, no turn) for > 60 seconds receive a server-initiated ping.
If no pong within 10 seconds, the connection is closed with code 1001.

### FR-59.05 — Connection Limits

Maximum WebSocket connections per instance: 200 (configurable via
`MAX_WS_CONNECTIONS`). New connections beyond this limit receive HTTP 503
before the WebSocket upgrade.

---

## 8. Acceptance Criteria (Gherkin)

```gherkin
Feature: Multiplayer Transport

  Scenario: AC-59.01 — Actor connects and receives welcome event
    Given a valid session token for Actor A
    When Actor A opens a WebSocket to WS /api/v1/play/ws
    Then the connection is accepted
    And a world_event with type=welcome is sent

  Scenario: AC-59.02 — Turn submitted via WebSocket produces turn_result
    Given Actor A is connected via WebSocket
    When Actor A sends {type: turn_submit, payload: {action: "look around"}}
    Then Actor A receives a turn_result message with narration

  Scenario: AC-59.03 — World event is delivered to all actors in universe
    Given Actor A and Actor B are connected in Universe X
    When Actor A's turn changes the world-state
    Then Actor B receives a world_event message within 200ms

  Scenario: AC-59.04 — Stale connection is cleaned up
    Given a WebSocket connection with no activity for 70 seconds
    When the server sends a ping and receives no pong within 10 seconds
    Then the connection is closed with code 1001
    And the actor slot transitions to idle
```

---

## 9. Out of Scope

- Player-to-player text chat (narration only; OOC chat is not in scope for v4).
- WebRTC voice (v5+).
- Reconnection with turn replay (at-most-once delivery; no message queue for
  reconnecting clients in v4).

---

## 10. Open Questions

| ID | Question | Status |
|---|----------|--------|
| OQ-59.01 | Which WebSocket library? | ✅ Resolved — FastAPI/Starlette native (websockets). |
| OQ-59.02 | Should we support HTTP long-polling as a WebSocket fallback? | 🔓 Open — SSE remains available; long-polling not planned for v4. |
