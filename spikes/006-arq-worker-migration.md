# Decision #6 Spike: arq Worker Migration

**Status**: ✅ Complete — design validated
**Date**: 2026-05-14
**Architecture Review**: `plans/v2_1-architecture-review.md` §6

## Current State

### arq infrastructure (already wired)

- `src/tta/jobs/queue.py` (77 lines): `ArqQueue` — enqueue by function name, status checking
- `src/tta/jobs/worker.py` (34 lines): `WorkerSettings` — function registry, Redis config, cron jobs
- `src/tta/jobs/jobs.py` (262 lines): 4 existing jobs with dead-letter handling, metrics, retry
- `pyproject.toml`: `arq>=0.25` already declared
- Worker start: `uv run arq tta.jobs.worker.WorkerSettings`

Existing jobs: `gdpr_delete_player`, `retention_sweep`, `session_cleanup`, `game_backfill`

### What runs where today

| Task | Location | How | Problem |
|------|----------|-----|---------|
| NPC autonomy | `context.py:87` | **INLINE** during turn pipeline | Adds LLM latency to every player turn |
| Consequence propagation | `context.py:105` | **INLINE** during turn pipeline | Same — serial LLM calls in critical path |
| Playtester sessions | `eval/pipeline.py:74` | In-process async | Will starve player turns under parallel load |
| Title generation | `games.py:331` | `asyncio.create_task()` | Lightweight, non-LLM — OK in-process |
| Summary regen | `games.py:399` | `asyncio.create_task()` | Lightweight — OK in-process |
| Snapshot writing | `games.py:406` | `asyncio.create_task()` | Lightweight — OK in-process |
| Session purge/TTL | `app.py:419` | `asyncio.create_task()` | Lightweight — OK in-process |

### The critical finding

NPC autonomy and consequence propagation run **synchronously during the turn pipeline** (`context.py:73-116`). Every player turn waits for NPC updates and consequence propagation before assembling context. This is the single biggest latency contributor that can be moved off the critical path.

## Target State

| Task | Runs in | Trigger |
|------|---------|---------|
| Player turn pipeline | API process | Player submits turn |
| NPC autonomy | arq worker | Fire-and-forget after turn completion |
| Consequence propagation | arq worker | Fire-and-forget after NPC autonomy |
| Playtester sessions | arq worker | Enqueued by eval pipeline |
| Title gen, summary, snapshots | API process (existing) | No change needed |

### Key design decision: fire-and-forget NPC autonomy

NPC autonomy should NOT run during the turn pipeline. Instead:
1. Player turn completes → response sent to player
2. NPC autonomy fires asynchronously in arq worker
3. Next player turn loads NPC state from Neo4j (which was updated by the worker)
4. Consequence propagation fires after NPC autonomy (also in arq worker)

This means NPC autonomy effects are visible on the NEXT turn, not the current turn. This is acceptable — NPCs don't react instantly to player actions in any believable simulation.

## Migration Plan

### Phase 1: Playtester sessions (low risk, high impact)

1. Add `run_playtester_session(seed_id: str, persona_profile: dict)` to `jobs.py`
2. Wire `EvaluationPipeline.run_llm_playtesters()` to call `ArqQueue.enqueue()` instead of running inline
3. Worker needs: LLM client, Postgres session, Neo4j driver, Redis — all available via `get_settings()`

### Phase 2: NPC autonomy (medium risk, high impact)

1. Add `run_npc_autonomy(game_id: str)` to `jobs.py`
2. Change `context.py:87` from inline call to `ArqQueue.enqueue()`
3. Worker loads world state from Neo4j, processes NPCs, writes back
4. Add `run_consequence_propagation(game_id: str)` chained after NPC autonomy

### Phase 3: Rate-limit integration

1. arq workers respect the rate-limit budget (Decision #12)
2. NPC autonomy jobs use LOW tier, playtester jobs use HIGH tier
3. Worker concurrency: 2 NPC autonomy + 3 playtester = compatible with rate-limit caps

## Validation Checklist

- [x] arq infrastructure exists and is production-quality (4 jobs, dead-letter, metrics)
- [x] Worker pattern established: `WorkerSettings` → `jobs.py` functions
- [x] Playtester entry point identified: `EvaluationPipeline.run_llm_playtesters()`
- [x] NPC autonomy call site identified: `context.py:87` (current bottleneck)
- [x] Worker DB access: all jobs use `get_settings()` + `create_async_engine()` — same pattern usable for playtester/NPC jobs
- [x] Redis available to workers via `ctx['redis']` (ARQ convention)
- [x] LLM client available: `LiteLLMClient()` can be instantiated in worker (reads env vars)
- [ ] Actual integration test: run 1 playtester session via arq worker (deferred to implementation)

## Verdict

**arq migration is ready to implement.** Infrastructure is complete, patterns are proven, call sites are identified. The only change needed is:

1. **immediate**: Move NPC autonomy off the critical path — run after turn completes, not during
2. **v2.1**: Move playtester sessions to arq workers
3. **v2.1**: Wire rate-limit budget into worker task types

Zero new infrastructure needed. The existing arq setup handles queueing, retries, dead letters, and metrics.
