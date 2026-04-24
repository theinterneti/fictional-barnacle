# S34 — Diegetic Time

> **Status**: ✅ Approved
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 2 — Simulation
> **Dependencies**: S29 (Universe Identity)
> **Consumed by**: S35 (NPC Autonomy), S36 (Consequence Propagation), S37 (World Memory), S40 (Genesis v2)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

In v1, time does not exist in the game world. The only time concept is the wall-clock
timestamp on the session and the monotonic `turn_count` on `GameState`. This was a
correct v1 simplification.

v2 introduces **Diegetic Time**: an in-world clock that advances as the player acts,
independent of wall-clock time. The world has a day, a night, and routines that other
systems can consume. Time is turn-driven — not real-time — so a player who pauses for
a week returns to exactly the world-time they left.

This spec defines the `WorldTime` type, how time advances per turn, how it is
configured per universe, the time-of-day label vocabulary, and the skip-ahead mechanic
(sleep, wait, fast-travel). It is the **foundation primitive** for NPC routines (S35),
consequence timing (S36), and memory timestamps (S37).

---

## 2. Design Philosophy

### 2.1 Principles

- **Turn-driven, not wall-clock-driven**: One turn = one in-world tick. The player
  controls the pace of time. There is no background timer. This keeps the game world
  predictable and respectful of player agency.
- **Configurable per universe**: A grimdark fantasy may have 16-hour days; a cozy
  slice-of-life may have 24 equal hours. The mapping is stored in `universes.config`.
  Sane system defaults allow universes that do not specify time config to work
  out of the box.
- **No real-time mapping**: Diegetic time never maps to wall-clock time. Players who
  sleep on a problem return to the exact in-world moment they left.
- **Label-first consumption**: The rest of the system consumes `time_of_day_label`
  (e.g., `"dawn"`, `"midnight"`), not raw `hour`/`minute`. This decouples downstream
  logic from specific numeric thresholds.
- **Skip-ahead as a first-class action**: Sleeping, waiting, and fast-travel are
  legitimate player choices that advance `WorldTime` by multiple ticks atomically.
  The autonomy processor (S35) MUST run for every skipped tick.

### 2.2 What This Spec Is NOT

- This spec does not define seasons or calendar systems (reserved for v3+).
- This spec does not define how time is *narrated* (prose of "the sun rises") —
  that belongs to the generation stage (S36, S40).
- This spec does not define any real-time or async background job that advances time
  while the player is offline.

---

## 3. User Stories

> **US-34.1** — **As a** player, when I take an action, I notice the in-world time
> advances (e.g., "It is now mid-afternoon"), so the world feels alive and temporal.

> **US-34.2** — **As a** player, I can choose to "sleep until morning" and wake up to
> a world that has changed — NPCs have moved, the market has opened — without taking
> one turn at a time.

> **US-34.3** — **As a** player, the time of day feels meaningful: shops close at
> night, guards are less alert at dawn, and the forest is more dangerous after dusk.

> **US-34.4** — **As a** developer, I can query the current `WorldTime` for a session
> and get a structured object with `day_count`, `hour`, `minute`, and
> `time_of_day_label`. I do not need to compute these from a raw tick counter.

> **US-34.5** — **As a** universe author, I can configure how quickly in-world time
> passes via the universe's config, without touching game engine code.

> **US-34.6** — **As an** operator, I can inspect the current `WorldTime` for any
> active session and verify that time is advancing correctly.

---

## 4. Functional Requirements

### FR-34.01 — WorldTime Type

The `WorldTime` type is a structured, immutable value object with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `total_ticks` | Non-negative integer | Monotonic tick counter. Starts at 0. Advances by 1 per normal turn, by N per skip-ahead of N ticks. Never decreases. |
| `day_count` | Non-negative integer | Number of complete in-world days elapsed. 0-indexed. |
| `hour` | Integer [0, hours_per_day) | Current in-world hour within the current day. |
| `minute` | Integer [0, 60) | Current in-world minute within the current hour. |
| `time_of_day_label` | String | Human-readable label. See FR-34.04. |

`WorldTime` is immutable. Mutation produces a new `WorldTime` instance.

`WorldTime` with `total_ticks = 0` represents the moment a universe is created —
before any player turn has been processed. This is a valid state and MUST NOT be
represented as `None`.

### FR-34.02 — Time Advancement Per Turn

- **FR-34.02a**: At the end of each successfully processed player turn, `WorldTime`
  MUST advance by exactly `ticks_per_turn` ticks (see FR-34.03).
- **FR-34.02b**: Advancement MUST be atomic with the session state write. A turn that
  fails to persist MUST NOT advance `WorldTime`.
- **FR-34.02c**: Advancement MUST recompute all `WorldTime` fields from the new
  `total_ticks` using `compute_world_time` (see FR-34.07).
- **FR-34.02d**: A paused or abandoned session MUST NOT advance `WorldTime`. Time
  only advances during active turn processing.

### FR-34.03 — Universe Time Configuration

The following fields MUST be supported in `universes.config` under the key `"time"`.
All fields are optional; defaults are defined below.

| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `ticks_per_turn` | Positive integer | `1` | In-world ticks advanced per player turn. |
| `minutes_per_tick` | Positive integer | `60` | In-world minutes advanced per tick. |
| `hours_per_day` | Positive integer | `24` | Length of an in-world day in hours. |
| `day_start_hour` | Integer [0, hours_per_day) | `6` | Hour at which "day" begins (used for skip-to-dawn). |
| `starting_hour` | Integer [0, hours_per_day) | `8` | In-world hour at universe creation (total_ticks = 0). |
| `starting_day` | Non-negative integer | `0` | In-world day count at universe creation. |
| `max_skip_ticks` | Positive integer | `48` | Maximum ticks advanced in a single skip-ahead action. |
| `tod_boundaries` | Object or null | null (use defaults) | Map of label → start fraction of hours_per_day. |

With system defaults: one player turn advances the world by 60 in-world minutes
(1 hour) on a 24-hour day starting at 08:00 on day 0.

A `ticks_per_turn` value of `0` MUST be rejected at universe creation time with a
validation error. For legacy/migrated universes that somehow carry this value, it
MUST be treated as `1`.

### FR-34.04 — Time-of-Day Label Vocabulary

The system MUST map the current `hour` to one of the following canonical labels using
the boundaries in `tod_boundaries` (fractional proportion of `hours_per_day`).
If `tod_boundaries` is null, the default boundaries below apply.

| Label | Default Start (fraction) | Default Start (24h) |
|-------|--------------------------|---------------------|
| `midnight` | 0.000 | 00:00 |
| `predawn` | 0.042 | 01:00 |
| `dawn` | 0.208 | 05:00 |
| `morning` | 0.292 | 07:00 |
| `midday` | 0.500 | 12:00 |
| `afternoon` | 0.583 | 14:00 |
| `dusk` | 0.708 | 17:00 |
| `evening` | 0.833 | 20:00 |
| `night` | 0.917 | 22:00 |

When `hours_per_day` ≠ 24, the fraction-based boundaries scale automatically.

The `time_of_day_label` field is a plain string (not a closed enum) to allow universe
authors to provide custom labels via `tod_boundaries` (e.g., `"lighttime"` /
`"darktime"` for a binary day/night world).

### FR-34.05 — Skip-Ahead Mechanics

A **skip-ahead** is a player action that advances `WorldTime` by more than one tick.
Valid triggers include: sleep/rest, explicit waiting, and location travel with a
non-zero `Connection.travel_time`.

- **FR-34.05a**: A skip-ahead of `N` ticks MUST advance `total_ticks` by exactly `N`.
- **FR-34.05b**: For every tick advanced during a skip-ahead, the NPC autonomy
  processor (S35 FR-35.05) MUST be invoked once, in ascending tick order. The
  processor MAY batch multiple ticks for a single NPC for efficiency, provided the
  observable NPC state at the end of the batch is equivalent to per-tick processing.
- **FR-34.05c**: The maximum skip-ahead in one player action is `max_skip_ticks`
  (see FR-34.03). Requests exceeding this limit MUST be silently capped.
- **FR-34.05d**: A skip-ahead request MUST specify a target: either an absolute
  `WorldTime` target (e.g., "next dawn") or a delta in ticks. The system converts
  the target to a tick count before advancing.
- **FR-34.05e**: A skip-ahead MUST pause when a `WorldEvent` (S35 FR-35.07) with
  `triggers_at_tick ≤ target_tick` is encountered within the skip window. The event
  MUST be applied at that tick before advancing further.

### FR-34.06 — GameState Integration

- **FR-34.06a**: `GameState` MUST include a `world_time: WorldTime` field.
- **FR-34.06b**: On session creation, `world_time` MUST be initialized to the
  universe's current canonical `WorldTime`. If the universe has no prior sessions,
  `WorldTime` is initialized from `starting_hour` and `starting_day` config.
- **FR-34.06c**: The canonical `WorldTime` for a universe is the `world_time` from
  the last successfully completed session turn. A new session in an existing universe
  inherits this canonical time.
- **FR-34.06d**: `WorldTime` is included in the `GameState` snapshot persisted via
  S33 `universe_snapshots`.

### FR-34.07 — compute_world_time

A pure function `compute_world_time(total_ticks: int, config: TimeConfig) -> WorldTime`
MUST exist. It MUST be:

- **Deterministic**: Identical inputs always produce identical output.
- **Pure**: No I/O, no side effects, no database reads.
- **Fast**: MUST complete in under 1 ms for any valid input.
- **Portable**: Usable outside the running application (offline tooling, test fixtures,
  S41 scenario seed validation).

---

## 5. Non-Functional Requirements

### NFR-34.01 — Computation Latency
`compute_world_time` MUST complete in under 1 ms. It is pure arithmetic; no I/O.

### NFR-34.02 — Snapshot Size
`WorldTime` serialized in `GameState` MUST NOT exceed 200 bytes.

### NFR-34.03 — Backward Compatibility (v1 Migration)
Sessions migrated from v1 have no `WorldTime`. On first access, MUST return a
`WorldTime` initialized from universe config defaults (`total_ticks = 0`). MUST NOT
derive `total_ticks` from `turn_count` — the semantics are different.

---

## 6. User Journeys

### Journey 1: Normal Turn with Time Advancement

**Trigger**: Player submits "I walk to the market."

1. Pipeline processes the player's action.
2. At turn-end, `total_ticks` advances by `ticks_per_turn`.
3. `compute_world_time` recomputes all fields.
4. Updated `WorldTime` written atomically with session state.
5. Next turn's narrative generation receives the new `WorldTime`.
6. Narrator may acknowledge: "The market bells ring as midday arrives."

### Journey 2: Sleep Until Morning

**Trigger**: Player inputs "I find a safe corner and sleep until morning."

1. System determines target: next occurrence of `dawn` label.
2. Computes `ticks_to_dawn`. Caps at `max_skip_ticks` if needed.
3. For each tick in `[current_tick, current_tick + ticks_to_dawn)`:
   - NPC autonomy processor (S35) runs.
   - If a `WorldEvent` triggers mid-skip, pause and notify player.
4. `WorldTime` advances to the `dawn` boundary.
5. Accumulated `WorldDelta` events passed to narrative generation.
6. Narrator describes rest, night's passage, and what has changed.

### Journey 3: Universe with Custom Time Config

**Trigger**: Universe author sets `hours_per_day = 16`, `ticks_per_turn = 2`.

1. Each player action advances 2 in-world hours.
2. A full day passes in 8 player turns.
3. `time_of_day_label` boundaries scale proportionally to the 16-hour day.

---

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | Universe has no prior `WorldTime` | Initialize from `starting_hour`/`starting_day` defaults |
| E2 | Skip-ahead target is already in the past | Treat as 0-tick skip; no-op |
| E3 | `hours_per_day = 1` (degenerate config) | Valid; labels cycle within 1 hour; proportional boundaries apply |
| E4 | `ticks_per_turn = 0` | Rejected at creation. Legacy sessions treat as `1`. |
| E5 | `minutes_per_tick = 90` | Carry over: 1 hour 30 minutes per tick; `hour` and `minute` computed correctly |
| E6 | Two sessions advance time concurrently | Last-write-wins per S30 universe atomicity rules |
| E7 | WorldEvent fires mid-skip | Pause at event tick; player notified; skip does NOT auto-resume |
| E8 | v1 migrated session accessed before backfill | Return `total_ticks = 0` WorldTime; log warning; MUST NOT return null |

---

## 8. Acceptance Criteria (Gherkin)

```gherkin
Feature: Diegetic Time

  Background:
    Given a universe with default time config (1 tick/turn, 60 min/tick, 24h day)
    And an active game session in that universe

  Scenario: AC-34.01 — Time advances by one tick per normal turn
    When the player submits a turn action
    And the turn is processed successfully
    Then world_time.total_ticks is incremented by 1
    And world_time.hour is recomputed from total_ticks
    And world_time.time_of_day_label reflects the new hour

  Scenario: AC-34.02 — WorldTime is initialized from universe config on first session
    Given a universe with starting_hour = 8 and starting_day = 0
    And no prior session has been processed in this universe
    When a new session is created
    Then world_time.total_ticks = 0
    And world_time.day_count = 0
    And world_time.hour = 8
    And world_time.time_of_day_label = "morning"

  Scenario: AC-34.03 — New session inherits canonical universe time
    Given a universe where the last completed session ended at world_time.total_ticks = 5
    When a new session is started in the same universe
    Then the new session's world_time.total_ticks = 5

  Scenario: AC-34.04 — compute_world_time is deterministic
    Given total_ticks = 36 and default time config
    When compute_world_time is called twice with identical inputs
    Then both calls return identical WorldTime objects

  Scenario: AC-34.05 — Skip-ahead advances by the correct number of ticks
    Given world_time.total_ticks = 10 and time_of_day_label = "evening"
    When the player requests "sleep until morning" (target = next dawn)
    Then world_time advances by the exact number of ticks to the next dawn boundary
    And world_time.time_of_day_label = "dawn"

  Scenario: AC-34.06 — Skip-ahead is capped at max_skip_ticks
    Given a universe with max_skip_ticks = 48
    When the player requests a skip-ahead of 100 ticks
    Then only 48 ticks are advanced
    And the session records that the skip was capped

  Scenario: AC-34.07 — Skip-ahead invokes NPC autonomy per tick
    Given an NPC with a routine step triggering at ticks 3 and 7
    When the player skips ahead 10 ticks
    Then the NPC routine step is processed at ticks 3 and 7 during skip processing

  Scenario: AC-34.08 — Skip-ahead pauses at a WorldEvent within the skip window
    Given a WorldEvent scheduled at tick 5 and current total_ticks = 2
    When the player requests a skip-ahead of 10 ticks
    Then the skip pauses at tick 5
    And the WorldEvent is applied before the skip continues

  Scenario: AC-34.09 — Custom hours_per_day scales time-of-day boundaries
    Given a universe with hours_per_day = 16
    When total_ticks results in an hour at the proportional midpoint of the day
    Then time_of_day_label = "midday"

  Scenario: AC-34.10 — Failed turn does not advance WorldTime
    Given world_time.total_ticks = 10
    When the turn pipeline raises an unrecoverable error
    And the session state is not persisted
    Then world_time.total_ticks remains 10
```

---

## 9. Out of Scope

- **Calendar systems, months, seasons**: Reserved for v3+.
- **Real-time advancement**: No background timer advances time while offline.
- **Narrating time passage**: Prose is the responsibility of the generation stage.
- **`tod_boundaries` schema validation**: Governed by S39 (Universe Composition).
- **UI/UX clock display**: A client concern.

---

## 10. Open Questions

| OQ | Question | Status |
|----|----------|--------|
| OQ-34.01 | Diegetic-time-to-real-time mapping: configurable per universe or global? | **Resolved**: configurable per universe; system defaults in this spec. |
| OQ-34.02 | Should `WorldTime` include sub-minute precision (seconds)? | Deferred. Reserve `second` field for v3+. |
| OQ-34.03 | Should a WorldEvent mid-skip auto-resume after the event resolves? | Proposed: no auto-resume; require explicit player input. Final decision deferred to S40 author. |

---

## Appendix A — WorldTime Fields (Reference Implementation Shape)

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class WorldTime:
    """Immutable in-world time value object.

    All fields are derived from total_ticks via compute_world_time().
    Do not construct directly — use compute_world_time().
    """
    total_ticks: int        # Monotonic. Never decreases.
    day_count: int          # 0-indexed complete days elapsed.
    hour: int               # [0, hours_per_day)
    minute: int             # [0, 60)
    time_of_day_label: str  # e.g., "dawn", "morning", "midnight"
```

---

## Appendix B — Default TimeConfig Values

```python
from dataclasses import dataclass, field

@dataclass
class TimeConfig:
    ticks_per_turn: int = 1
    minutes_per_tick: int = 60
    hours_per_day: int = 24
    day_start_hour: int = 6
    starting_hour: int = 8
    starting_day: int = 0
    max_skip_ticks: int = 48
    tod_boundaries: dict[str, float] | None = None  # None = use built-in defaults
```

Default `tod_boundaries` expressed as fractional proportion of `hours_per_day`:

| Label | Start fraction | 24h equivalent |
|-------|---------------|----------------|
| `midnight` | 0.000 | 00:00 |
| `predawn` | 0.042 | 01:00 |
| `dawn` | 0.208 | 05:00 |
| `morning` | 0.292 | 07:00 |
| `midday` | 0.500 | 12:00 |
| `afternoon` | 0.583 | 14:00 |
| `dusk` | 0.708 | 17:00 |
| `evening` | 0.833 | 20:00 |
| `night` | 0.917 | 22:00 |
