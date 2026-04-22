# S50 — Concurrent Universe Loading

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v4+
> **Implementation Fit**: ❌ Not Started
> **Level**: 3 — Platform
> **Dependencies**: S29 (Universe Spec), S33 (Universe Persistence Schema)
> **Related**: S51 (Cross-Universe Travel), S54 (Event Substrate), S57 (Multi-Actor)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

S50 is the load-bearing prerequisite for all v4+ multiverse features. It defines
how two or more universes can be resident in server memory simultaneously, each
with its own isolated state, identity, and lifecycle, without violating resource
budgets or allowing state bleed between universes.

All other v4+ specs (S51–S59) depend on the guarantees made here.

---

## 2. Design Principles

### 2.1 Universe as First-Class Resource

A loaded universe is a bounded resource with a defined memory and CPU footprint.
Loading a universe requires explicit budget allocation. The engine refuses to load
a universe if doing so would exceed the global budget.

### 2.2 Isolation Is a Hard Guarantee

No Python object, database connection, or in-memory cache may be shared between
two loaded universes. A bug in Universe A must not be able to corrupt Universe B.
Isolation is enforced structurally, not by convention.

### 2.3 Eviction Is Non-Destructive

Evicting a universe from memory does not delete its data. The universe state is
persisted to PostgreSQL (S33) before eviction. Reloading a universe restores its
state from that snapshot.

---

## 3. Universe Lifecycle

```
  UNLOADED ──load()──► LOADING ──ready──► ACTIVE
                                            │
                                 deactivate()│
                                            ▼
                                      DEACTIVATING ──persisted──► EVICTED
                                            │
                               load() (reload from persist)
```

| State | Meaning |
|---|---|
| `UNLOADED` | Known in the registry but not in memory |
| `LOADING` | Hydrating from persistence; not yet accepting turns |
| `ACTIVE` | Fully resident; accepting turns and events |
| `DEACTIVATING` | Draining active sessions; persisting state |
| `EVICTED` | State persisted; resources released; ready to reload |

---

## 4. Functional Requirements

### FR-50.01 — Universe Registry

A `UniverseRegistry` in `src/tta/multiverse/registry.py` tracks all known
universes by `universe_id`. For each universe it records:
- Current lifecycle state
- Resident actor count (for eviction priority)
- Memory footprint estimate (updated at ACTIVE transition)
- Last active timestamp

### FR-50.02 — Resource Budget

The engine SHALL enforce a configurable resource budget:
- `MAX_CONCURRENT_UNIVERSES` (default: `4`) — maximum simultaneously ACTIVE universes
- `UNIVERSE_MEMORY_BUDGET_MB` (default: `256`) — maximum memory per universe (Neo4j subgraph + working caches)

Attempting to load a universe when budget is exhausted triggers eviction of the
least-recently-active universe with zero resident actors. If no evictable universe
exists, the load request is queued with a 30-second timeout; after timeout it fails
with `UniverseLoadError`.

### FR-50.03 — Isolation Enforcement

Each active universe holds:
- Its own scoped Neo4j session bound to the universe's node namespace (`universe_id` property)
- Its own in-memory narrative-cache keyed by `universe_id`
- No reference to any other universe's objects

Cross-universe reads are only permitted via the S54 Event Substrate, never
by direct object reference. Any code path that accesses a universe by calling
into another universe's scope MUST be rejected in code review.

### FR-50.04 — Persistence on Eviction

Before a universe transitions to EVICTED, the engine MUST call
`UniversePersistenceService.snapshot(universe_id)` (S33) and await its
completion. If the snapshot fails, the universe stays ACTIVE and a
CRITICAL log is emitted: `universe_eviction_snapshot_failed`.

### FR-50.05 — Load From Snapshot

When `load(universe_id)` is called for an UNLOADED or EVICTED universe,
the engine restores state from the most recent S33 snapshot. If no snapshot
exists, the universe is initialized fresh from its S29 manifest.

### FR-50.06 — Observability

Prometheus metrics SHALL include:
- `tta_universe_active_count` (gauge) — currently ACTIVE universes
- `tta_universe_load_duration_seconds{universe_id}` (histogram)
- `tta_universe_eviction_total{reason}` (counter: `lru`, `budget_exceeded`, `manual`)

---

## 5. Acceptance Criteria (Gherkin)

```gherkin
Feature: Concurrent Universe Loading

  Scenario: AC-50.01 — Two universes load and remain isolated
    Given Universe A is ACTIVE with world-state W_A
    When Universe B is loaded concurrently
    Then Universe B reaches ACTIVE state with its own world-state W_B
    And a write to W_A does not affect W_B

  Scenario: AC-50.02 — Budget exhaustion triggers LRU eviction
    Given MAX_CONCURRENT_UNIVERSES = 2
    And universes U1 and U2 are ACTIVE with zero resident actors
    And U1 was last active more recently than U2
    When a request to load U3 is received
    Then U2 is snapshotted and transitions to EVICTED
    And U3 transitions to ACTIVE

  Scenario: AC-50.03 — Universe with resident actors is not evicted
    Given MAX_CONCURRENT_UNIVERSES = 2
    And U1 (0 actors) and U2 (1 actor) are ACTIVE
    When a request to load U3 is received
    Then U1 is evicted (not U2)

  Scenario: AC-50.04 — Eviction failure leaves universe ACTIVE
    Given snapshot fails for universe U2
    When eviction is attempted
    Then U2 remains ACTIVE
    And a CRITICAL log universe_eviction_snapshot_failed is emitted

  Scenario: AC-50.05 — Reload restores persisted state
    Given U1 was evicted after snapshotting world-state W1
    When U1 is reloaded
    Then U1's world-state equals W1
```

---

## 6. Out of Scope

- Cross-universe actor travel (S51).
- The event bus between universes (S54).
- Universe creation (S29 defines the manifest; S33 defines persistence).

---

## 7. Open Questions

| ID | Question | Status |
|---|----------|--------|
| OQ-50.01 | Should memory footprint be measured or estimated? | 🔓 Open — estimate via Neo4j node count × average node byte size at v4 impl time. |
