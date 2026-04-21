# S32 — Transport Abstraction

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 3 — Platform
> **Dependencies**: v1 S10
> **Last Updated**: 2026-04-21

---

## 1. Purpose

v1's narrative delivery code is tightly coupled to Server-Sent Events (SSE). The
`stream_turn` route handler directly constructs `NarrativeEvent`, `HeartbeatEvent`, and
`NarrativeEndEvent` model instances, calls `SseEventBuffer.append()`, and formats raw
SSE wire strings. This hard-coupling means that adding WebSocket support (planned for
S59 in v4+) would require modifying the route handler and any other code that orchestrates
delivery — a violation of the v1 S21 constraint 4 (SSE→WS migration path) that was
documented as unmet at v1 closeout.

S32 introduces `NarrativeTransport`: a Python `Protocol` that represents the abstract
contract for delivering narrative events to a connected client. SSE becomes one
implementation of this protocol (`SSETransport`). Any future transport — WebSocket
(S59), long-polling, local in-process (testing) — implements the same protocol without
touching pipeline or route logic above the transport boundary.

The boundary is explicit: **no code above the transport module shall import from
`tta.api.sse` or directly construct `SSEEvent` subclasses for the purpose of narrative
delivery**. Code above the transport boundary communicates only via `NarrativeTransport`
method calls.

---

## 2. Design Philosophy

**Protocol over inheritance**: `NarrativeTransport` is a `typing.Protocol`, not an ABC.
Implementations need not inherit from a base class — duck typing is sufficient. This
allows `SSETransport` to remain a clean implementation class with no forced hierarchy.

**Method-per-event-type**: the protocol exposes one method per logical event type
(`send_narrative`, `send_end`, `send_error`, `send_heartbeat`, `send_state_update`,
`send_moderation`). This makes the transport boundary explicit: callers name what they
want to send, not what wire format to use.

**Transport owns chunking**: the responsibility for splitting a narrative string into
sentence-aligned chunks (currently `_split_narrative()` in `games.py`) moves inside
`SSETransport.send_narrative()`. Callers pass the full narrative string; the transport
decides how to chunk it and how many chunks were emitted.

**Return total_chunks from send_narrative**: `send_narrative()` returns the number of
chunks emitted, so the caller can immediately call `send_end(total_chunks=n)` without
re-counting.

**No async generator leakage**: the `SSETransport` internally manages the async
generator or callback that feeds `StreamingResponse`. The route handler's `event_stream`
generator delegates entirely to the transport, yielding only what the transport returns.

---

## 3. User Stories

### Developer-Facing

- **US-32.1** — **As a** backend developer adding WebSocket support in v4+, **I want**
  to implement one Python class that conforms to `NarrativeTransport`, **so that** I
  do not need to touch the turn pipeline, route logic, or any other delivery code.

- **US-32.2** — **As a** backend developer writing integration tests, **I want** to
  inject a mock `NarrativeTransport` that records all sent events, **so that** I can
  assert delivery behavior without spinning up an SSE connection.

- **US-32.3** — **As a** backend developer on-call, **I want** the transport boundary
  to be clearly defined and documented, **so that** I can quickly understand which layer
  is responsible for a streaming bug.

### Player-Facing (unchanged from v1)

- **US-32.4** — **As a** player, I receive streamed narrative chunks in the same SSE
  format as v1, with no visible change to the player-facing API.

---

## 4. Functional Requirements

### FR-32.01 — `NarrativeTransport` Protocol

- **FR-32.01a**: The system MUST define a `NarrativeTransport` class in
  `src/tta/transport/protocol.py` using `typing.Protocol` with
  `@runtime_checkable`.

- **FR-32.01b**: `NarrativeTransport` MUST declare the following async methods:

  | Method | Signature | Returns | Notes |
  |---|---|---|---|
  | `send_narrative` | `(text: str, turn_id: str) -> int` | `int` — number of chunks emitted | Transport owns chunking |
  | `send_end` | `(turn_id: str, total_chunks: int) -> None` | `None` | Signals turn narrative is complete |
  | `send_error` | `(code: str, message: str, turn_id: str \| None, correlation_id: str \| None, retry_after_seconds: int \| None) -> None` | `None` | Delivers an error event |
  | `send_heartbeat` | `() -> None` | `None` | Keepalive pulse |
  | `send_state_update` | `(changes: list[WorldChange]) -> None` | `None` | World-state diff post-turn |
  | `send_moderation` | `(reason: str) -> None` | `None` | Moderation redirect notice |

  All methods MUST be `async def` (awaitable). Synchronous implementations MUST
  use `asyncio.coroutine` wrappers or `async def` with synchronous bodies.

- **FR-32.01c**: `NarrativeTransport` MUST declare a read-only `is_connected`
  property returning `bool`. A transport where `is_connected == False` MUST silently
  discard all `send_*` calls without raising.

- **FR-32.01d**: The `typing.runtime_checkable` decorator MUST be applied to
  `NarrativeTransport` so that `isinstance(transport, NarrativeTransport)` works in
  tests and guards.

### FR-32.02 — `SSETransport` Implementation

- **FR-32.02a**: The system MUST provide a class `SSETransport` in
  `src/tta/transport/sse.py` that satisfies the `NarrativeTransport` protocol.

- **FR-32.02b**: `SSETransport` MUST accept the following at construction time:
  - `redis: Redis` — the async Redis client for the `SseEventBuffer`
  - `game_id: str` — used as the buffer namespace key
  - An `emit` callable: `Callable[[SSEEvent], Awaitable[str]]` — the callback that
    formats and appends an event to the buffer and returns the raw SSE string.

  The `emit` callable is provided by the route handler (it is the existing `_emit`
  closure), keeping `SSETransport` free of direct dependency on FastAPI request state.

- **FR-32.02c**: `SSETransport.send_narrative()` MUST:
  1. Split `text` into sentence-aligned chunks using the same algorithm as v1
     `_split_narrative()` (sentence boundaries, max-chunk-size guard from
     `settings.sse_chunk_max_chars`).
  2. Call `emit(NarrativeEvent(text=chunk, turn_id=turn_id, sequence=i))` for each
     chunk.
  3. Return the number of chunks emitted.

- **FR-32.02d**: `SSETransport.send_end()` MUST call
  `emit(NarrativeEndEvent(turn_id=turn_id, total_chunks=total_chunks))`.

- **FR-32.02e**: `SSETransport.send_error()` MUST call
  `emit(ErrorEvent(code=code, message=message, ...))`.

- **FR-32.02f**: `SSETransport.send_heartbeat()` MUST call
  `emit(HeartbeatEvent())`.

- **FR-32.02g**: `SSETransport.send_state_update()` MUST call
  `emit(StateUpdateEvent(changes=changes))`.

- **FR-32.02h**: `SSETransport.send_moderation()` MUST call
  `emit(ModerationEvent(reason=reason))`.

- **FR-32.02i**: `SSETransport.is_connected` MUST return `True` after construction
  and `False` after `close()` is called or a client-disconnect is detected.

### FR-32.03 — `MemoryTransport` (Testing Utility)

- **FR-32.03a**: The system MUST provide a `MemoryTransport` class in
  `src/tta/transport/memory.py` that satisfies `NarrativeTransport` and records all
  sent events in an ordered list (`events: list[dict]`).

- **FR-32.03b**: `MemoryTransport` MUST NOT depend on Redis, FastAPI, or any I/O.
  All `send_*` methods append a structured record to `self.events` and return
  immediately (no I/O).

- **FR-32.03c**: `MemoryTransport` MUST expose a `clear()` method to reset the
  events list between test scenarios.

- **FR-32.03d**: `MemoryTransport.send_narrative()` MUST still apply the chunking
  algorithm (or accept a `split: bool = True` parameter to skip it in unit tests that
  want raw text).

### FR-32.04 — Module Layout

- **FR-32.04a**: The transport package MUST be located at `src/tta/transport/` with
  the following structure:

  ```
  src/tta/transport/
    __init__.py          # re-exports NarrativeTransport, SSETransport, MemoryTransport
    protocol.py          # NarrativeTransport Protocol definition
    sse.py               # SSETransport implementation
    memory.py            # MemoryTransport for testing
  ```

- **FR-32.04b**: `src/tta/transport/__init__.py` MUST re-export `NarrativeTransport`,
  `SSETransport`, and `MemoryTransport` so callers import from `tta.transport`.

### FR-32.05 — Delivery Layer Constraint (Import Rule)

- **FR-32.05a**: The `stream_turn` route handler in `games.py` MUST NOT directly
  import or instantiate `NarrativeEvent`, `NarrativeEndEvent`, `HeartbeatEvent`,
  `ErrorEvent`, `StateUpdateEvent`, or `ModerationEvent` for the purpose of emitting
  narrative. These imports are permitted only within `SSETransport.send_*` methods.

- **FR-32.05b**: The `stream_turn` route handler MUST construct an `SSETransport`
  and call its methods. The pattern MUST be:

  ```python
  transport = SSETransport(redis=redis, game_id=game_id_str, emit=_emit)
  total_chunks = await transport.send_narrative(result.narrative_output, turn_id)
  await transport.send_end(turn_id, total_chunks)
  ```

- **FR-32.05c**: All existing direct event emissions in `games.py` (moderation,
  state_update, heartbeat, error) MUST be refactored to call the corresponding
  `transport.send_*()` method.

- **FR-32.05d**: The `_split_narrative()` free function in `games.py` MUST be moved
  to `src/tta/transport/sse.py` or `src/tta/transport/_chunking.py` and MUST NOT
  remain in the route handler module. It MAY be re-exported from `tta.transport` for
  use in tests.

### FR-32.06 — `PipelineDeps` Transport Slot

- **FR-32.06a**: `PipelineDeps` in `src/tta/pipeline/types.py` MUST gain an optional
  field `transport: NarrativeTransport | None = None`. Default is `None`; injection
  is done at route-handler construction time.

- **FR-32.06b**: In v2.0, NO pipeline stage (understand, context, generate, deliver)
  calls `transport.send_*()` directly. The transport slot is reserved for a future
  streaming-native generate stage that calls `send_narrative` token-by-token during
  LLM generation (deferred to v3+). In v2.0, the route handler calls the transport
  after the pipeline returns.

- **FR-32.06c**: The `deliver_stage` MUST NOT be modified for S32. It continues to
  mark the turn as complete; narrative delivery is the route handler's responsibility.

---

## 5. Non-Functional Requirements

- **NFR-32.A** — `SSETransport` MUST add no more than 1 ms of overhead per `send_*`
  call compared to the equivalent direct `_emit()` call (p95). The abstraction must be
  zero-cost for SSE delivery.
- **NFR-32.B** — `MemoryTransport.send_*()` methods MUST complete within 0.1 ms (p99)
  with no I/O.
- **NFR-32.C** — The `stream_turn` handler's end-to-end SSE delivery latency (first
  chunk to client) MUST remain within the v1 baseline ± 5 ms after refactoring.
- **NFR-32.D** — No existing v1 SSE wire format is changed. Clients receive identical
  event names, data structures, and ordering as v1.
- **NFR-32.E** — The `NarrativeTransport` protocol MUST be Pyright `standard`-clean
  with no type: ignore comments. `SSETransport` and `MemoryTransport` MUST pass Pyright
  checks as satisfying the Protocol.

---

## 6. User Journeys

### Journey 1: v2.0 SSE Delivery (No Change for Clients)

1. Client opens SSE connection: `GET /api/v1/games/{id}/stream`.
2. Client submits turn: `POST /api/v1/games/{id}/turns`.
3. Route handler runs pipeline → gets `TurnState` with `narrative_output`.
4. Route handler constructs `SSETransport(redis=..., game_id=..., emit=_emit)`.
5. Route handler calls `await transport.send_narrative(result.narrative_output, turn_id)`.
6. `SSETransport` splits narrative, emits `NarrativeEvent` chunks via `_emit`.
7. Route handler calls `await transport.send_end(turn_id, total_chunks)`.
8. Route handler calls `await transport.send_state_update(result.world_state_updates)` if present.
9. Client receives identical SSE wire format as v1.

### Journey 2: Integration Test Using MemoryTransport

1. Test instantiates `MemoryTransport()`.
2. Test injects transport into route handler (via dependency override).
3. Test submits a turn.
4. Test asserts `transport.events` contains: narrative chunks in order, narrative_end with correct `total_chunks`, no error events.
5. No Redis, no SSE connection required.

### Journey 3: v4+ WebSocket Transport (Future, Not Implemented in v2)

1. Developer creates `WebSocketTransport` in `src/tta/transport/websocket.py`.
2. `WebSocketTransport` satisfies `NarrativeTransport` protocol.
3. Route handler for WebSocket connections constructs `WebSocketTransport` and passes it
   to the same delivery logic used by the SSE handler.
4. No changes to pipeline stages, `PipelineDeps`, or any module above the transport.

---

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| EC-32.01 | Client disconnects mid-stream | `SSETransport.is_connected` returns `False`; subsequent `send_*` calls are silently discarded; route handler exits generator cleanly. |
| EC-32.02 | `send_narrative` called with empty string | Transport emits zero chunks; returns 0; caller passes `total_chunks=0` to `send_end`. |
| EC-32.03 | `send_narrative` called with very long text (> buffer max) | Chunking algorithm applies max-chunk guard; emits `N` chunks each within the configured size limit. |
| EC-32.04 | `emit` callback raises during `send_narrative` | Exception propagates to the route handler; the generator's error handler calls `send_error()` via the same transport — which also raises. The generator falls back to raw error SSE string. |
| EC-32.05 | `MemoryTransport` used in production (configuration error) | `MemoryTransport.is_connected` always returns `True`; events are silently dropped in memory. Operator-level monitoring should alert on missing SSE client connections. |
| EC-32.06 | Pipeline stage accidentally calls `deps.transport.send_narrative()` in v2.0 | Pyright detects `NarrativeTransport | None` and requires a None-check. Test transport captures the call; code review policy flags direct stage→transport calls as a violation. |

---

## 8. Acceptance Criteria

```gherkin
Feature: Transport Abstraction

  Scenario: AC-32.01 — SSETransport satisfies NarrativeTransport protocol
    Given SSETransport is instantiated with a mock emit callback
    When isinstance(transport, NarrativeTransport) is evaluated
    Then the result is True (runtime_checkable Protocol check passes)

  Scenario: AC-32.02 — send_narrative returns chunk count
    Given an SSETransport with a recording emit callback
    When send_narrative("First sentence. Second sentence.", turn_id="t1") is called
    Then send_narrative returns 2 (two chunks emitted)
    And emit was called twice with NarrativeEvent instances
    And the first NarrativeEvent has sequence=0 and text="First sentence."
    And the second NarrativeEvent has sequence=1 and text="Second sentence."

  Scenario: AC-32.03 — send_end emits NarrativeEndEvent
    Given an SSETransport with a recording emit callback
    When send_end(turn_id="t1", total_chunks=2) is called
    Then emit was called once with a NarrativeEndEvent with total_chunks=2

  Scenario: AC-32.04 — send_heartbeat emits HeartbeatEvent
    Given an SSETransport with a recording emit callback
    When send_heartbeat() is called
    Then emit was called once with a HeartbeatEvent instance

  Scenario: AC-32.05 — games.py does not directly import SSE event classes for delivery
    Given the games.py source file
    When the import statements are inspected
    Then NarrativeEvent, NarrativeEndEvent, HeartbeatEvent, ErrorEvent, StateUpdateEvent,
         and ModerationEvent are NOT imported at the top level of games.py for delivery purposes

  Scenario: AC-32.06 — MemoryTransport records events without I/O
    Given a MemoryTransport instance
    When send_narrative("Hello world.", "t1") is called
    And send_end("t1", 1) is called
    Then MemoryTransport.events contains exactly 2 entries
    And no Redis or network calls were made

  Scenario: AC-32.07 — MemoryTransport satisfies NarrativeTransport protocol
    Given MemoryTransport is instantiated
    When isinstance(transport, NarrativeTransport) is evaluated
    Then the result is True

  Scenario: AC-32.08 — Disconnected transport discards sends silently
    Given an SSETransport where is_connected returns False
    When send_narrative("text", "t1") is called
    Then no exception is raised
    And emit was NOT called
    And send_narrative returns 0

  Scenario: AC-32.09 — SSE wire format is unchanged from v1
    Given an SSETransport with the real SseEventBuffer
    When a full turn is delivered via the transport
    Then the emitted SSE event names (narrative, narrative_end, heartbeat, error, etc.)
         are identical to those specified in v1 S10 §6.2
    And existing SSE client code receives correct events without modification

  Scenario: AC-32.10 — Pyright passes on transport module
    Given the src/tta/transport/ package
    When pyright is run with mode=standard
    Then zero type errors are reported
    And SSETransport and MemoryTransport are recognised as satisfying NarrativeTransport
```

---

## 9. Dependencies & Integration Boundaries

| Dependency | Spec | Integration Notes |
|---|---|---|
| API & SSE contract | v1 S10 | The SSE wire format (event names, data schemas, `Last-Event-ID` replay) is defined by S10. S32 wraps that contract; it does not change it. All S10 FRs and ACs remain normative. |
| Turn pipeline | v1 S08 | `PipelineDeps` gains a `transport` slot (FR-32.06a). No pipeline stage is modified in v2.0. |
| SSE event models | v1 internal | `src/tta/models/events.py` (NarrativeEvent, etc.) is used ONLY inside `SSETransport`. Route handlers do not import from it for delivery. |
| SSE buffer | v1 internal | `SseEventBuffer` and `format_sse` are used ONLY inside `SSETransport`. They remain in `src/tta/api/sse.py` and are not moved. |
| WebSocket transport | v4+ S59 | S59 provides `WebSocketTransport` implementing `NarrativeTransport`. S32 defines the protocol contract S59 must satisfy. |
| Content moderation | v1 S24 | `send_moderation()` delivers the player-safe moderation notice. The route handler detects `TurnStatus.moderated` and calls `transport.send_moderation(reason)`. |

---

## 10. Open Questions

| # | Question | Impact | Owner |
|---|----------|--------|-------|
| OQ-32.01 | Should `_split_narrative()` be configurable per-transport (e.g., WebSocket transport might prefer unsplit full text)? Or should chunking always be enforced at the transport level? | `send_narrative` contract (FR-32.01b) | S59 author |
| OQ-32.02 | Should the `emit` callback be part of the `NarrativeTransport` Protocol or an implementation detail of `SSETransport`? The current design embeds the `emit` callable in `SSETransport.__init__`, but a future transport might not need it. | FR-32.02b constructor signature | v2 tech lead |
| OQ-32.03 | v3+ may add a streaming-native generate stage that calls `transport.send_narrative()` token-by-token during LLM generation, requiring the transport to exist in `PipelineDeps` and be called from within the pipeline. Should S32 already define the `PipelineDeps.transport` field as an active call site, or strictly as a reserved slot? | FR-32.06b scope | v3+ LLM pipeline author |

---

## 11. Out of Scope

- **WebSocket implementation** — `WebSocketTransport` is the subject of S59. S32 only
  defines the protocol that S59 must implement.
- **Long-polling fallback** — documented as deferred in v1 S10 OQ-10.02. S32 does not
  address it; long-polling is a future transport implementation if/when needed.
- **Token-by-token LLM streaming into transport** — the generate stage in v2.0 still
  returns the full narrative string to the route handler. Real-time token streaming into
  the transport is a v3+ concern. S32 reserves the `PipelineDeps.transport` slot but
  does not wire it.
- **Transport multiplexing** — sending one turn's events to multiple simultaneous
  transport connections (e.g., browser tab + mobile) is a v4+ concern (S57/S59).
- **Changes to `SseEventBuffer`** — the Redis-backed replay buffer remains unchanged.
  `SSETransport` wraps it; S32 does not modify or specify changes to `SseEventBuffer`.
- **Changes to `src/tta/models/events.py`** — the SSE event model classes remain
  unchanged. S32 moves their use inside `SSETransport`; it does not alter the models.
- **Server-side rate-limit headers on SSE responses** — the v1 open item (AC-10.08 gap)
  is an S10 concern, not S32.

---

## Changelog

- 2026-04-21: Initial draft. Authored by GitHub Copilot continuing from Claude Code
  rate-limited session. Based on roadmap §3.1 S32 summary, v1 S10 implementation,
  `src/tta/api/sse.py`, `src/tta/models/events.py`, and `src/tta/api/routes/games.py`
  delivery section analysis.
