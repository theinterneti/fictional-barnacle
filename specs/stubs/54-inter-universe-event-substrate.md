# S54 — Inter-Universe Event Substrate

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v4+
> **Implementation Fit**: ❌ Not Started
> **Level**: 3 — Platform
> **Dependencies**: S49 (Horizontal Scaling / Redis PubSub), S50 (Concurrent Universe Loading)
> **Related**: S55 (Bleedthrough Propagation), S56 (Resonance Correlation), S48 (Async Jobs)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

S54 defines the low-level pub/sub substrate that allows events to propagate
between loaded universe instances. It is the backbone for:
- Cross-universe travel notifications (S51)
- Bleedthrough propagation (S55)
- Resonance correlation (S56)
- Admin broadcasts across universes

The substrate is not a narrative system. It is a plumbing layer: a typed event
bus built on the Redis PubSub mechanism already present in S49, with a dedicated
channel namespace and an explicit event schema.

**Implementation constraint**: No new infrastructure. The substrate runs on the
same Redis instance as sessions (S11) and job queues (S48). It uses a channel
naming convention to segregate multiverse events from other PubSub traffic.

---

## 2. Channel Naming Convention

```
tta:multiverse:events          # global broadcast (all universes subscribed)
tta:multiverse:universe:{id}   # universe-scoped; only that universe subscribed
tta:multiverse:actor:{id}      # actor-scoped; relevant universe subscribed
```

Publishers write to the most specific appropriate channel. The global channel
is used for system-wide events (shutdown, scheduled maintenance). Subscribers
listen to the global channel plus any universe-scoped channels they own.

---

## 3. Event Schema

All events published to the substrate use the following envelope:

```python
class MultiverseEvent(BaseModel):
    event_id: uuid.UUID
    event_type: str              # e.g. "travel_completed", "bleedthrough", "resonance_pulse"
    source_universe_id: str
    target_universe_id: str | None  # None = global
    actor_id: uuid.UUID | None
    timestamp: datetime
    payload_type: str            # fully-qualified Python type name or schema slug
    payload: dict                # event-specific data; validated against payload_type schema
    schema_version: int = 1
```

Events are serialized as JSON. Payload schemas are versioned separately.
Unknown `payload_type` values are logged and discarded (forward-compat).

---

## 4. Functional Requirements

### FR-54.01 — Publish

Any universe instance may call `MultiverseEventBus.publish(event)`. The method
serializes the event to JSON and calls `redis.publish(channel, payload)` where
channel is selected per §2. Publish is fire-and-forget (at-most-once delivery).

### FR-54.02 — Subscribe

Universe instances subscribe to their universe-scoped channel + the global
channel on load (S50 LOADING state). Subscriptions are released on eviction
(S50 EVICTED state). Subscription management is handled by `MultiverseEventBus`.

### FR-54.03 — Delivery Guarantee

The substrate provides **at-most-once delivery**. Events may be lost if a
subscriber disconnects and reconnects. Consumers MUST be designed to handle
missing events gracefully (idempotent processing, no critical state derived
solely from substrate events).

### FR-54.04 — Rate Limiting

Publication is rate-limited to **100 events per second per universe** via a
Redis token bucket (keys: `tta:multiverse:ratelimit:{universe_id}`, TTL:
`RATELIMIT_TTL_SECONDS` default 60 s per S12 FR-12.13). Events
exceeding this limit are dropped with a warning log. This prevents a single
universe from flooding the substrate.

### FR-54.05 — Metrics

The substrate exposes Prometheus counters:
- `tta_multiverse_events_published_total{universe_id, event_type}`
- `tta_multiverse_events_dropped_total{universe_id, reason}`
- `tta_multiverse_events_received_total{universe_id, event_type}`

### FR-54.06 — Shutdown Ordering

During graceful shutdown (SIGTERM), universe instances flush pending outbound
events before releasing subscriptions. Flush timeout: 2 seconds.

---

## 5. Acceptance Criteria (Gherkin)

```gherkin
Feature: Inter-Universe Event Substrate

  Scenario: AC-54.01 — Event published by Universe A is received by Universe B
    Given Universe A and Universe B are both ACTIVE
    And Universe B is subscribed to the global channel
    When Universe A publishes a travel_completed event
    Then Universe B receives the event within 500ms

  Scenario: AC-54.02 — Universe-scoped event is not received by other universes
    Given Universe A and Universe B are both ACTIVE
    When Universe A publishes an event to tta:multiverse:universe:A
    Then Universe B does NOT receive the event

  Scenario: AC-54.03 — Rate limit drops excess events
    Given Universe A has exhausted its 100/s token bucket
    When Universe A attempts to publish event 101
    Then the event is dropped
    And tta_multiverse_events_dropped_total increments with reason=rate_limited

  Scenario: AC-54.04 — Unknown payload_type is logged and discarded
    Given Universe B receives an event with payload_type = "unknown_future_type"
    Then Universe B logs a warning
    And does not raise an exception
```

---

## 6. Out of Scope

- Event persistence or replay (at-most-once; no durable log).
- Cross-datacenter event propagation (all instances share one Redis).
- Semantic interpretation of events (S55, S56).

---

## 7. Open Questions

| ID | Question | Status |
|---|----------|--------|
| OQ-54.01 | Should we add a dead-letter queue for undeliverable events? | 🔓 Open — at-most-once is sufficient for v4; DLQ deferred if needed. |
