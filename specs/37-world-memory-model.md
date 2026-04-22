# S37 — World Memory Model

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 2 — Simulation
> **Dependencies**: v1 S03 (Narrative), v1 S08 (Turn Pipeline), v1 S12 (Persistence), v1 S13 (World Graph)
> **Related**: S36 (Consequence Propagation), S38 (NPC Memory & Social), S62 (Story Export, v5+)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

In v1, narrative memory is a flat `list[dict]` field (`GameState.narrative_history`)
appended on every turn. There is no structure, no attribution, no importance scoring,
no decay, and no compression. When the context window fills, older turns simply fall
off the end. The player's story exists only as a growing string dump.

v2 replaces this with a structured, attributed, time-aware **World Memory Model**.

Memory is now a first-class entity with:
- Per-entry importance scores that determine what survives compression
- Tick-stamped timestamps from the diegetic clock (S34)
- Attribution to actors, locations, and event sources
- Three-tier working/active/compressed architecture tuned to context budgets
- LLM-assisted compression using the `LLMRole.SUMMARIZATION` path

This spec defines the `MemoryRecord` type, the `MemoryWriter` service contract,
the three-tier memory model, importance scoring rules, and the compression algorithm.
It is the foundation for story export (S62, v5+) and NPC memory (S38).

---

## 2. Design Philosophy

### 2.1 Principles

- **Memory as simulation state, not conversation log**: `MemoryRecord` entries are
  canon world events, not raw LLM output. They are attributed, scored, and managed
  independently of the text that mentions them.
- **Context budget drives compression, not wall time**: Compression is triggered
  by token count exceeding a configured threshold, not by age or calendar time.
  A player who plays slowly never loses memory unfairly.
- **Importance score determines what survives**: Low-importance records are compressed
  first. High-importance records are preserved in full or summarized with higher
  fidelity. Importance is scored at write time and decays over ticks.
- **Working memory is never compressed**: The last `working_memory_size` turns are
  always injected into the generation context in full, regardless of compression
  state. This prevents "amnesia" between consecutive turns.
- **LLM summarization is a compression tool, not a filter**: The summarization LLM
  call reduces token footprint but MUST preserve named entities, locations, and
  causal relationships present in the original records.

### 2.2 Relationship to v1 `narrative_history`

v1's `GameState.narrative_history: list[dict]` is deprecated in v2. During v2.0
migration, existing sessions' `narrative_history` entries are backfilled as
`MemoryRecord` entries with `source = "narrator"`, `importance_score = 0.3`
(low, triggering early compression), and `world_time_tick = 0`.

### 2.3 What This Spec Is NOT

- S37 does not define per-NPC recollection of the player — see S38.
- S37 does not define the story export format — see S62.
- S37 does not define how memory affects the generation prompt structure — that is
  the concern of the context assembly stage.
- S37 does not replace Postgres `game_snapshots` — snapshots remain the recovery
  mechanism; `MemoryRecord` is the semantic layer.

---

## 3. User Stories

> **US-37.1** — **As a** player, the game remembers what I did several sessions ago
> and NPCs can reference it, so the world feels persistent and meaningful.

> **US-37.2** — **As a** player, important story moments (discovering the villain's
> plan, making a major alliance) are never forgotten even after hundreds of turns,
> while minor flavor events fade gracefully.

> **US-37.3** — **As a** player, when memory is compressed, I don't notice jarring
> gaps — the summarized version preserves the key facts and named entities.

> **US-37.4** — **As a** developer, I can query all memory for a session ordered
> by importance or time, so I can debug what the game "knows" at any point.

> **US-37.5** — **As a** universe author, I can configure the working memory size
> and compression threshold per universe to tune the game's memory budget.

---

## 4. Functional Requirements

### FR-37.01 — MemoryRecord Type

A single unit of world memory:

| Field | Type | Description |
|-------|------|-------------|
| `memory_id` | ULID | Unique identifier. |
| `universe_id` | ULID | Owning universe. |
| `session_id` | UUID | Session that generated this record. |
| `turn_number` | int | Turn number at creation. |
| `world_time_tick` | int | `WorldTime.total_ticks` at creation (S34). |
| `source` | str | Origin: `"player"`, `"narrator"`, `"npc"`, `"world"`. |
| `attributed_to` | str or null | Entity ID (NPC, location) most associated with this event. |
| `content` | str | The full narrative text of this memory. |
| `summary` | str or null | LLM-generated summary if this is a compressed block. |
| `importance_score` | float [0.0, 1.0] | Importance at write time. |
| `current_importance` | float [0.0, 1.0] | Decayed importance at query time. |
| `tier` | str | `"working"`, `"active"`, or `"compressed"`. |
| `is_compressed` | bool | True if this record is a compression block. |
| `compressed_from` | list[ULID] | IDs of records this block replaced. |
| `tags` | list[str] | Content tags (e.g., `["combat", "quest", "faction:city_watch"]`). |
| `consequence_ids` | list[ULID] | `ConsequenceRecord` IDs that contributed to this memory. |
| `created_at` | datetime | Wall-clock time of record creation. |

### FR-37.02 — Three-Tier Memory Architecture

Memory is organized into three tiers at query time:

| Tier | Definition | Compressed? | Always Included? |
|------|-----------|-------------|------------------|
| Working | Last `working_memory_size` turns (default: 5) | Never | Yes |
| Active | Turns beyond working, up to `compression_threshold_tokens` | No | By importance |
| Compressed | Records summarized into compression blocks | Yes | Summary only |

- **FR-37.02a**: Working memory records are always injected into the generation
  context in full, regardless of their importance score.
- **FR-37.02b**: Active memory records are injected ordered by `current_importance`
  descending, trimmed to fit the available context budget after working memory.
- **FR-37.02c**: Compressed memory blocks are injected as their `summary` string
  only, not their original `content`.
- **FR-37.02d**: `working_memory_size` is configurable via
  `universes.config["memory"]["working_memory_size"]` (default: 5 turns).

### FR-37.03 — MemoryWriter Contract

```python
async def record(
    session_id: UUID,
    universe_id: str,
    turn_number: int,
    world_time: WorldTime,
    content: str,
    source: str,
    attributed_to: str | None,
    tags: list[str],
    consequence_ids: list[str],
) -> MemoryRecord: ...

async def get_context(
    session_id: UUID,
    universe_id: str,
    budget_tokens: int,
) -> MemoryContext: ...

async def compress_if_needed(
    session_id: UUID,
    universe_id: str,
) -> CompressionResult: ...
```

- **FR-37.03a**: `record()` MUST compute and store `importance_score` at write time
  using the scoring rules in FR-37.04.
- **FR-37.03b**: `record()` MUST check whether compression is needed
  (`compress_if_needed()`) after every write. Compression is async and non-blocking
  — it does not delay the current turn's pipeline.
- **FR-37.03c**: `get_context()` returns a `MemoryContext` object with three
  partitions: `working`, `active`, `compressed`, all fitted to `budget_tokens`.
- **FR-37.03d**: The `MemoryWriter` MUST be injectable. A `InMemoryMemoryWriter`
  with no persistence MUST exist for unit testing.

### FR-37.04 — Importance Scoring

Importance is scored at write time on the scale [0.0, 1.0] using these rules:

| Signal | Weight | Notes |
|--------|--------|-------|
| Source: `"player"` action | +0.3 | Player-driven events are inherently more salient |
| Source: `"world"` event | +0.2 | World-level events are significant |
| Source: `"narrator"` or `"npc"` | +0.0 | Baseline |
| NPC tier in `attributed_to` is `KEY` (S35) | +0.3 | KEY NPCs are high-salience |
| NPC tier `SUPPORTING` | +0.1 | |
| `ConsequenceRecord` severity `"critical"` | +0.3 | |
| `ConsequenceRecord` severity `"major"` | +0.2 | |
| `ConsequenceRecord` severity `"notable"` | +0.1 | |
| Tag `"quest"` present | +0.2 | Quest events are story-critical |
| Tag `"death"` or `"combat"` | +0.1 | |

Final score is clamped to [0.0, 1.0]. Scores are additive up to the cap.

### FR-37.05 — Importance Decay

Importance decays over diegetic time. The decay function is:

```
current_importance = importance_score * (0.5 ^ (ticks_elapsed / memory_half_life_ticks))
```

- `ticks_elapsed = current_world_time_tick - record.world_time_tick`
- `memory_half_life_ticks` is configurable via
  `universes.config["memory"]["memory_half_life_ticks"]` (default: 50 ticks).
- Decay is computed at query time, not stored. `current_importance` is a derived
  field calculated when `get_context()` is called.
- Records in the working tier are NOT subject to decay for context injection purposes
  (they are always included regardless of `current_importance`).
- An `importance_score` of 1.0 (maximum) takes 10 half-lives (~500 ticks default)
  to decay below 0.001. Such records are effectively permanent.

### FR-37.06 — Compression Trigger

Compression is triggered when the total token count of ALL active `MemoryRecord`
content for a session exceeds `compression_threshold_tokens`.

- `compression_threshold_tokens` is configurable via
  `universes.config["memory"]["compression_threshold_tokens"]` (default: 4000).
- Token count estimation uses the v1 `count_tokens()` function from
  `tta.llm.context_budget` (character-count heuristic, safe over-estimate).
- **FR-37.06a**: Compression selects the oldest active records with
  `current_importance < 0.5` (configurable via `compression_importance_threshold`,
  default: 0.5) for summarization.
- **FR-37.06b**: Selected records are batched into a single LLM summarization call
  using `LLMRole.SUMMARIZATION`. The prompt instructs the model to preserve named
  entities, locations, and causal relationships.
- **FR-37.06c**: The resulting summary text is stored as a new `MemoryRecord` with
  `is_compressed = True`, `tier = "compressed"`, and `compressed_from = [list of
  original memory_ids]`. The original records are NOT deleted — they are marked
  `tier = "archived"` and excluded from context injection.
- **FR-37.06d**: If LLM summarization fails, compression is skipped for this turn.
  A `WARNING` is logged. The uncompressed records remain in the active tier.
  Compression will be retried on the next turn.
- **FR-37.06e**: Working-tier records (last `working_memory_size` turns) are NEVER
  eligible for compression.

### FR-37.07 — MemoryContext Type

The output of `get_context()`, consumed by the context assembly stage:

| Field | Type | Description |
|-------|------|-------------|
| `working` | list[MemoryRecord] | Last N turns, always in full. |
| `active` | list[MemoryRecord] | Older records, sorted by `current_importance` desc. |
| `compressed` | list[MemoryRecord] | Compression blocks; only `summary` is used. |
| `total_tokens` | int | Estimated token count of this context. |
| `dropped_count` | int | Active records dropped to fit budget. |

### FR-37.08 — Integration with S36 (Consequence Propagation)

When `ConsequencePropagator.propagate()` produces `ConsequenceRecord` entries, the
corresponding `MemoryRecord` for that turn receives:
- `consequence_ids` populated with the `consequence_id` values from the result.
- An importance boost per FR-37.04 based on the highest severity propagated
  consequence.

This linkage enables S38 (NPC Memory) to query MemoryRecords by consequence.

### FR-37.09 — Persistence

`MemoryRecord` objects are stored in Neo4j as `Memory` nodes with `universe_id`
and `session_id` properties, connected to their `Universe` node via a
`HAS_MEMORY` relationship.

A `MemoryRecord` is NEVER mutated after creation. Compression creates new records;
original records are re-labeled to `tier = "archived"`.

---

## 5. Non-Functional Requirements

### NFR-37.01 — Write Latency
`record()` MUST complete in under 20 ms (p95), excluding the async compression call.

### NFR-37.02 — Context Assembly Latency
`get_context()` MUST complete in under 50 ms (p95) for a session with up to 500
active `MemoryRecord` nodes.

### NFR-37.03 — Compression Non-Blocking
`compress_if_needed()` is async and runs outside the turn pipeline critical path.
It MUST NOT delay generation by more than 5 ms (it should be fire-and-forget).

### NFR-37.04 — Observability
Every `record()` call MUST emit a structlog event with `memory_id`, `importance_score`,
and `session_id`. Every compression run MUST emit `records_compressed`,
`tokens_before`, `tokens_after`, and `session_id`.

### NFR-37.05 — Test Coverage
An `InMemoryMemoryWriter` and unit tests MUST cover: importance scoring for all
signal combinations, decay calculation at multiple tick offsets, compression
trigger boundary (just under and just over threshold), LLM failure fallback
(no compression), and three-tier context assembly with budget trimming.

---

## 6. User Journeys

### Journey 1: Player Discovers the Villain's Plan (High Importance)

**Turn N**: Player in `villain_lair`. Player action triggers a `"world"` event.
A `ConsequenceRecord` with severity `critical` is generated (S36).

1. `MemoryWriter.record()` is called with `source = "world"`, `tags = ["quest"]`,
   `consequence_ids = [villain_plan_consequence_id]`.
2. Importance scoring: `+0.2` (world source) + `+0.2` (quest tag) + `+0.3`
   (critical consequence) = `0.7` importance_score.
3. Record stored in Neo4j. Tier: `active` (not yet in working window's overflow).
4. After 200 ticks (4 half-lives at default 50): `current_importance = 0.7 × (0.5^4)
   = 0.7 × 0.0625 = 0.044`. Still above `0.001` — not effectively zero.
5. After 500 ticks (10 half-lives): `current_importance ≈ 0.001`. Near-zero,
   eligible for compression in a future compression run.

### Journey 2: Compression Run (50 Turns of Low-Importance Events)

After 50 turns of `"narrator"` source records (importance `0.0`–`0.3`), total
active memory crosses `compression_threshold_tokens = 4000`.

1. `compress_if_needed()` fires asynchronously after turn 50's `record()` call.
2. Records with `current_importance < 0.5` selected (40 of 50 records).
3. Batched into single `LLMRole.SUMMARIZATION` call.
4. Summary returned: "Over the past 40 turns, the player explored the merchant
   district, resolved a minor dispute between innkeeper Carla and the baker,
   and purchased supplies for the journey north."
5. New `MemoryRecord` created: `is_compressed = True`, `tier = "compressed"`,
   `compressed_from = [40 ids]`, `importance_score = 0.5`.
6. 40 original records marked `tier = "archived"` (excluded from context injection).
7. `compress_if_needed()` logs: `records_compressed = 40`, `tokens_before = 4400`,
   `tokens_after = 850`.

### Journey 3: Working Memory Guarantee

Player is on turn 200 in a long session. Active memory is heavily compressed.

1. `get_context(budget_tokens = 2000)` is called.
2. Working tier (last 5 turns) consumes ~500 tokens — always included first.
3. Remaining 1500 tokens split between active records (sorted by
   `current_importance` desc) and compressed block summaries.
4. Player never experiences amnesia about what happened in the last 5 turns.

---

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | `record()` called with empty `content` | Raise `ValueError`; do not persist |
| E2 | LLM summarization fails during compression | Skip compression; log WARNING; retry next turn |
| E3 | `compress_if_needed()` called but threshold not reached | No-op; no LLM call made |
| E4 | `get_context()` with budget smaller than working memory alone | Include working memory only; `dropped_count` reflects dropped active + compressed |
| E5 | All records are in working tier (session < `working_memory_size` turns) | No active or compressed records; context is purely working tier |
| E6 | `world_time_tick` is 0 (migrated v1 session) | No decay applied (0 ticks elapsed); importance_score used as-is |
| E7 | Compression block's `compressed_from` references a deleted record | Log WARNING; continue; block is still valid |
| E8 | Two concurrent turns attempt compression simultaneously | Second call short-circuits if first is in progress (Redis lock or idempotency key) |

---

## 8. Acceptance Criteria (Gherkin)

```gherkin
Feature: World Memory Model

  Background:
    Given a session with universe memory config:
      | working_memory_size          | 5    |
      | compression_threshold_tokens | 4000 |
      | compression_importance_threshold | 0.5 |
      | memory_half_life_ticks       | 50   |

  Scenario: AC-37.01 — MemoryRecord is created with correct importance score
    Given a turn with source "world", tag "quest", and a critical ConsequenceRecord
    When MemoryWriter.record() is called
    Then a MemoryRecord is persisted with importance_score = 0.7
    And the record has tier = "active"

  Scenario: AC-37.02 — Working memory records are always injected
    Given a session with 20 turns of compressed memory
    And a budget_tokens of 100 (smaller than active memory)
    When get_context() is called
    Then working tier records (last 5 turns) are included
    And dropped_count reflects records excluded from active/compressed

  Scenario: AC-37.03 — Compression is triggered when threshold exceeded
    Given a session where active memory token count exceeds 4000
    When MemoryWriter.record() completes
    Then compress_if_needed() fires asynchronously
    And records with current_importance < 0.5 are summarized
    And a new MemoryRecord with is_compressed = True is created
    And original records are marked tier = "archived"

  Scenario: AC-37.04 — LLM summarization failure leaves memory unchanged
    Given a session where compression is triggered
    And the LLM summarization call fails
    When compress_if_needed() completes
    Then no MemoryRecord is archived
    And a WARNING is logged
    And the next turn's record() call retries compression

  Scenario: AC-37.05 — Importance decay reduces active record priority over time
    Given a MemoryRecord with importance_score = 0.4 created at tick 0
    And current_world_time_tick = 50 (one half-life elapsed)
    When get_context() is called
    Then the record's current_importance = 0.2

  Scenario: AC-37.06 — Working-tier records are never compressed
    Given 5 records in the working tier
    And active memory token count exceeds compression_threshold_tokens
    When compress_if_needed() runs
    Then working-tier records are not included in compression candidates

  Scenario: AC-37.07 — ConsequenceRecord linkage boosts importance
    Given a source event with a critical ConsequenceRecord
    When MemoryWriter.record() is called with consequence_ids populated
    Then the resulting MemoryRecord.importance_score includes the +0.3 critical boost

  Scenario: AC-37.08 — Migrated v1 records have low default importance
    Given a MemoryRecord migrated from v1 narrative_history
    Then importance_score = 0.3
    And world_time_tick = 0
    And no decay is applied (ticks_elapsed = 0)
```

---

## 9. Out of Scope

- Per-NPC recollection of the player — see S38.
- Story export format — see S62.
- How `MemoryContext` is serialized into the generation prompt — context assembly
  stage concern.
- Long-term semantic search over memories — deferred to v3+ (likely S62 dependency).
- Multi-session shared world memory across different players' sessions in the same
  universe — deferred to a future Universe Shared State spec.

---

## 10. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-37.01 | Memory compression threshold — token count or semantic boundary? | ✅ Resolved | **Token count** (primary trigger, configurable). Semantic boundaries (chapter/arc breaks) deferred to v2.1 as optional secondary hints. |
| OQ-37.02 | Should `MemoryRecord` be persisted in Postgres (for `game_snapshots` recovery) or Neo4j only? | ⏳ Open | Proposed: Neo4j only. Postgres `game_snapshots` remain the recovery path; `MemoryRecord` is the semantic layer. `compress_if_needed()` fires post-snapshot. S33 author to confirm schema. |
| OQ-37.03 | Is `tier` a stored field or always derived at query time? | ✅ Resolved | **Stored field** (`"working"`, `"active"`, `"compressed"`, `"archived"`). Tier is assigned at write time and updated during compression. This avoids recomputing for every `get_context()` call. |
| OQ-35.02 | Should `WorldDelta` be persisted as part of the turn record? | ⏳ Open (inherited from S35) | Proposed: `WorldDelta.changes` are consumed by S36 and S37; the delta itself is ephemeral and need not be stored separately. S37 implementation author to confirm. |

---

## Appendix A — MemoryRecord Dataclass Shape

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class MemoryRecord:
    memory_id: str          # ULID
    universe_id: str        # ULID
    session_id: str         # UUID
    turn_number: int
    world_time_tick: int    # WorldTime.total_ticks (S34)
    source: str             # "player" | "narrator" | "npc" | "world"
    attributed_to: str | None
    content: str
    summary: str | None
    importance_score: float
    tier: str               # "working" | "active" | "compressed" | "archived"
    is_compressed: bool
    compressed_from: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    consequence_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now())

    def current_importance(self, current_tick: int, half_life_ticks: int) -> float:
        ticks_elapsed = max(0, current_tick - self.world_time_tick)
        if ticks_elapsed == 0 or half_life_ticks <= 0:
            return self.importance_score
        return self.importance_score * (0.5 ** (ticks_elapsed / half_life_ticks))
```

## Appendix B — Importance Scoring Reference

| Signal | Score Delta | Cap |
|--------|-------------|-----|
| source = `"player"` | +0.3 | 1.0 |
| source = `"world"` | +0.2 | 1.0 |
| source = `"narrator"` or `"npc"` | +0.0 | — |
| attributed_to NPC tier = `KEY` | +0.3 | 1.0 |
| attributed_to NPC tier = `SUPPORTING` | +0.1 | 1.0 |
| ConsequenceRecord severity `"critical"` | +0.3 | 1.0 |
| ConsequenceRecord severity `"major"` | +0.2 | 1.0 |
| ConsequenceRecord severity `"notable"` | +0.1 | 1.0 |
| tag `"quest"` | +0.2 | 1.0 |
| tag `"death"` or `"combat"` | +0.1 | 1.0 |
| *(any combination)* | sum, clamped to [0.0, 1.0] | 1.0 |

## Appendix C — Three-Tier Memory Architecture Diagram

```
Session memory at get_context() time:

  ┌──────────────────────────────────────────────────────┐
  │  WORKING TIER  (last 5 turns — always injected)      │
  │  turn 196, 197, 198, 199, 200                        │
  └──────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────┐
  │  ACTIVE TIER  (sorted by current_importance desc)    │
  │  Full content — trimmed to context budget            │
  │  turn 100, 150, 175 (high-importance survivors)      │
  └──────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────┐
  │  COMPRESSED TIER  (summary text only)                │
  │  block A: turns 1–99 summary                         │
  │  block B: turns 101–149 summary                      │
  └──────────────────────────────────────────────────────┘

  [ARCHIVED records: excluded from context, kept for audit / S62 export]
```

## Appendix D — Pipeline Position

```
Turn Pipeline (v2 Enrich stage):
  1. Understand stage (parse intent)
  2. AutonomyProcessor.process()       →  WorldDelta              [S35]
  3. ConsequencePropagator.propagate() →  PropagationResult       [S36]
  4. MemoryWriter.record()             →  MemoryRecord[]          [S37] ← THIS SPEC
     └─ compress_if_needed() (async, non-blocking)
  5. Context assembly: get_context()   →  MemoryContext
  6. Generate stage
  7. Stream stage
```
