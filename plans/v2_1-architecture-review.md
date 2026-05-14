# v2.1 Architecture Review

> **Status**: ✅ Complete — all 13 decisions resolved
> **Created**: 2026-05-13
> **Completed**: 2026-05-14
> **Companion to**: `plans/v2_1-evaluation-and-playtesting.md`, `docs/vision/TTA-STRATEGY.md`, `docs/vision/TTA-CRITICAL-REVIEW.md`
> **Gate**: Between v2.0 merge and v2.1 design. Required by CRITICAL-REVIEW §6.

---

## Purpose

v1 fixed the architecture. v2.0 inherited it. Every version since has compounded
the cost of changing it. This document is the **deliberate pause** before v2.1
where each v1 choice is re-examined against:

1. What we have learned shipping v1 and v2.0
2. What v2.1 actually demands (quality eval, playtesters, structured turns,
   content richness, basic image gen, rate-limit budget)
3. What v3+ will demand soon enough that changing now is cheaper than later

**One decision per choice. Explicit verdict. No ambiguity.**

---

## Decision Matrix (Summary)

Verdicts: **KEEP** · **REPLACE** · **AUGMENT** · **DEFER**.

| # | Choice | Verdict | Action this version | Owner |
|---|--------|---------|---------------------|-------|
| 1 | Single FastAPI process | **AUGMENT** | Add arq worker; keep turn path in-process | Hermes |
| 2 | LiteLLM library mode (vs. direct FMR HTTP) | **KEEP** | Remove vestigial SmartRouterLLMClient | Hermes |
| 3 | Neo4j CE | **KEEP** | Benchmark at v2.1 stress test; defer upgrade to v3 | Hermes |
| 4 | SSE transport | **KEEP** | Revisit at v3 invite multiplayer | — |
| 5 | Manual JSON parsing for LLM output | **AUGMENT** | Spike complete: prompt + Pydantic validation wins; no new deps | Hermes |
| 6 | In-process async for background work | **AUGMENT** | Spike complete: arq ready; move NPC autonomy + playtesters to workers | Hermes |
| 7 | Jinja2 prompt templating | **AUGMENT** | Jinja2 for composition; Langfuse for versioning (already wired) | — |
| 8 | Static HTML/JS player UI | **AUGMENT** | Spike complete: htmx via script tags; zero deps, natural SSE | Hermes |
| 9 | Tenacity-only resilience | **AUGMENT** | Adopt ttadev RetryPrimitive + TimeoutPrimitive | Hermes |
| 10 | No dedicated cache layer | **AUGMENT** | Adopt ttadev CachePrimitive over Redis | Hermes |
| 11 | No image-gen client | **DEFER** | One-page ADR during v2.1 spec work | Hermes |
| 12 | No rate-limit budget | **BUILD** | Component spec + asyncio semaphore implementation | Hermes |
| 13 | No `ttadev` dependency | **ADOPT** | Verified: install from GitHub release v0.1.0-alpha; RetryPrimitive + CachePrimitive work | Hermes |

---

## 1. Single FastAPI Process

- **What it is**: `src/tta/app.py` — single ASGI app, single process, in-process
  pipelines. Background work runs via `asyncio.create_task()` (10 sites).
- **Why it was chosen**: `plans/system.md` — solo dev, no microservices, simplicity.
- **What we learned**: arq infrastructure already wired (`src/tta/jobs/queue.py`,
  `src/tta/jobs/worker.py`, `arq>=0.25` in pyproject.toml) but unused for
  background LLM work. Everything runs in the API process.
- **What v2.1 demands**: Parallel playtester sessions (long-running, LLM-heavy)
  will starve player-facing turns if sharing the API process.
- **Verdict**: **AUGMENT**. Add arq worker for background LLM tasks. Player turn
  path stays in-process for latency.
- **Action**: Define task routing in `plans/v2_1-evaluation-and-playtesting.md`.
  Spike: 3 concurrent playtester sessions, success = no player-turn latency
  regression > 20%.

## 2. LiteLLM Library Mode

- **What it is**: `src/tta/llm/litellm_client.py` calls `litellm.acompletion()`.
  FMR is routed provider (`openai/tta`). `SmartRouterLLMClient` (256 lines,
  `smart_router_client.py`) talks to FMR via direct HTTP but is **not wired**
  into the app. The app uses `LiteLLMClient` exclusively.
- **Why it was chosen**: `specs/07-llm-integration.md` — abstract provider.
  Multi-backend PR #193 hardened with role-configurable backends.
- **What we learned**: Two parallel clients for the same purpose. SmartRouter
  duplicates token counting, error handling, call history. LiteLLM handles
  fallback, retry, provider abstraction. Multi-backend config lets operators
  switch between FMR, OpenRouter, Anthropic without code changes.
- **What v2.1 demands**: Structured output. 30 LLM call sites.
- **Verdict**: **KEEP** LiteLLM. Remove SmartRouterLLMClient as dead code.
- **Action**: Delete `src/tta/llm/smart_router_client.py`. Verify FMR
  `response_format` passthrough (see Decision #5).

## 3. Neo4j Community Edition

- **What it is**: Neo4j CE 5.x via `neo4j>=6.0`. World graph, NPCs, consequences.
- **Why it was chosen**: `plans/system.md` — OSS, graph-native queries.
- **What we learned**: 26/28 integration tests pass. Two-hop latency acceptable
  in isolation; flaky under concurrent load. No observed CE ceiling at single-user.
- **What v2.1 demands**: Richer graphs + playtester parallelism.
- **Verdict**: **KEEP** for v2.1. Benchmark at stress test; empirical data gates v3.
- **Action**: Add concurrent Neo4j read benchmark to v2.1 stress test.

## 4. SSE Transport

- **What it is**: FastAPI `EventSourceResponse` streaming turn output.
- **Why it was chosen**: `plans/api-and-sessions.md` — one-way, simple.
- **What we learned**: Reliable for narrative streaming. Transport abstraction
  added in Wave C but not exercised.
- **What v2.1 demands**: Still solo player. SSE sufficient.
- **Verdict**: **KEEP**. Revisit at v3 multiplayer.
- **Action**: None this version.

## 5. Manual JSON Parsing for LLM Output

- **What it is**: Hand-rolled `json.loads()` at 14 call sites across
  genesis_v2.py, quality/evaluator.py, generate.py, snapshot.py, neo4j_service.py.
- **Why it was chosen**: v1 had few structured-output sites.
- **What we learned**: Free models produce parseable JSON ~80-90% of the time.
  Typical failures: trailing commas, unescaped quotes, markdown-wrapped JSON.
  Instructor PR #196 merged then reverted (#198) — premature.
- **What v2.1 demands**: Many new structured-output sites (quality scoring,
  tone tags, lore checks, choice classification, composition extraction).
- **Verdict**: **AUGMENT** (spike complete). Winner: **prompt-based JSON + Pydantic
  validation**. See `spikes/005-structured-output/README.md` for full results.
  - `response_format` ignored by free models through FMR — ineffective.
  - `instructor` blocked by `mistralai` dependency conflict.
  - `pydantic-ai` overkill for structured output alone (deferred to v3+).
  - Free models produce valid JSON 85-100% with strong prompt + example.
  - Recommendation: strong prompt template + Pydantic `model_validate()` + 1 retry.
- **Action**: Done. Implement in production: add strong prompt template from spike,
  add Pydantic post-validation to existing `json.loads()` call sites, add 1 retry
  on validation failure. No new dependencies.

## 6. In-Process Async for Background Work

- **What it is**: NPC autonomy, consequence propagation, session purging all run
  as `asyncio.create_task()` in the API process (10 sites in app.py, games.py).
- **Why it was chosen**: v1 had no background work; v2.0 kept it simple.
- **What we learned**: arq infrastructure wired but unused. NPC autonomy fires
  after every turn and competes with the next player turn for LLM capacity.
- **What v2.1 demands**: Playtester sessions are long-running (5-10 min),
  expensive (14+ LLM calls), and parallel. They will starve player turns.
- **Verdict**: **AUGMENT** (spike complete). arq infrastructure ready — 4 existing
  jobs, dead-letter handling, metrics. Playtester sessions and NPC autonomy
  ready to move. See `spikes/006-arq-worker-migration.md`.
  **Critical finding**: NPC autonomy runs INLINE during turn pipeline
  (`context.py:87`) — every player turn waits for NPC LLM calls.
  Should fire-and-forget after turn completes.
- **Action**: Implement in two phases: (1) move NPC autonomy + consequence
  propagation to arq workers (immediate latency win), (2) move playtester
  sessions to arq workers (v2.1 concurrency). Zero new infrastructure needed.

## 7. Jinja2 Prompt Templating

- **What it is**: `src/tta/prompts/` — Jinja2 templates. Langfuse prompt bridge
  (`langfuse_bridge.py`) already wired across 6 files.
- **Why it was chosen**: `plans/prompts.md` — familiar, debuggable. Langfuse
  bridge added in gap-closure (#187).
- **What we learned**: Dual approach working: Jinja2 composes prompts from
  world state; Langfuse versions and enables A/B comparison.
- **What v2.1 demands**: Versioned prompts with quality metrics per version.
- **Verdict**: **AUGMENT** (already done). Keep both.
- **Action**: None. Document the dual approach.

## 8. Static HTML/JS Player UI

- **What it is**: Minimal HTML test harness with EventSource consumer.
- **Why it was chosen**: v1 needed a test harness, not a client.
- **What we learned**: Inadequate for playtesters. No choice buttons, no styling.
- **What v2.1 demands**: Styled output, choice buttons, dark theme, basic image
  rendering.
- **Verdict**: **AUGMENT** with htmx. Smaller than Alpine (~14KB), natural SSE
  support (`hx-sse`), no build step. Defer React/Svelte to v3.
- **Action**: Spike complete. See `spikes/008-htmx-ui.md`. Add htmx as script-tag
  dependency in `static/index.html`. Two tags: `htmx.org@2.0.4` + `htmx-ext-sse@2.2.2`.
  Zero build steps, zero new Python dependencies.

## 9. Tenacity-Only Resilience

- **What it is**: `tenacity>=9.0` decorators on LLM calls + Neo4j queries.
  3 retries per tier, exponential backoff. No circuit breakers, no timeouts.
- **Why it was chosen**: `plans/resilience-and-safety.md` — proven retry library.
- **What we learned**: Free model calls take 30-90s. No per-task timeout
  enforcement. Concurrent calls have no circuit breaking.
- **What v2.1 demands**: Per-task timeouts, circuit breakers for parallel
  playtesters, cooperative throttling for rate-limit budget.
- **Verdict**: **AUGMENT**. Adopt ttadev RetryPrimitive + TimeoutPrimitive.
  Tenacity stays for Neo4j/Redis.
- **Action**: Depends on #13 (ttadev). If ttadev adopted, use its primitives.
  If not, add `asyncio.wait_for()` timeout wrappers.

## 10. No Dedicated Cache Layer

- **What it is**: Redis used for sessions only. No LLM output memoization,
  no scenario-seed cache, no Genesis phase-output cache.
- **Why it was chosen**: v1 didn't repeat enough LLM work.
- **What we learned**: Genesis smoke test showed repeated LLM calls. Playtester
  agents replay similar scenarios. Image-gen prompts are deterministic.
  Turn retries SHOULDN'T be cached (want different result).
- **What v2.1 demands**: Cache scenario seeds, Genesis phase outputs,
  image-gen prompt→URL mappings. Never cache per-turn narrative generation.
- **Verdict**: **AUGMENT**. ttadev CachePrimitive over Redis.
- **Action**: Depends on #13 (ttadev). Cache targets clearly defined.

## 11. No Image-Gen Client (NEW for v2.1)

- **What it is**: Not present. v2.1 adds basic portraits.
- **What v2.1 demands**: Image generation from world-state-derived prompts.
- **Verdict**: **DEFER**. Leaf feature — doesn't block other decisions.
  Write ADR during v2.1 spec work.
- **Action**: One-page ADR. Default: route through FMR; fallback to direct SDK.

## 12. No Rate-Limit Budget (NEW for v2.1)

- **What it is**: No rate limiting exists. 30 LLM call sites compete equally
  for free-model capacity. CRITICAL-REVIEW §1: required BEFORE v2.1.
- **What v2.1 demands**: Player-facing must not starve. Three priority tiers:
  1. Player-facing (never throttled)
  2. Playtester (concurrent limit)
  3. Background/NPC (best-effort, throttled first)
  Provider-aware: track utilization, shift background work to underutilized
  providers.
- **Verdict**: **BUILD**. In-process component: asyncio semaphores keyed by
  task type, provider-aware via LiteLLM hooks.
- **Action**: ✅ Spec written: `specs/50-rate-limit-budget.md`. Implement as
  `src/tta/llm/rate_limiter.py`. Success: under 3× concurrent playtester load,
  player turn latency stays within budget.

## 13. No `ttadev` Dependency (NEW for v2.1)

- **What it is**: Not present. STRATEGY recommends adopting at v2.1.
- **What v2.1 demands**: Cache, Memory, Timeout, Parallel primitives across
  playtester harness.
- **Verdict**: **ADOPT** (spike complete). Install from GitHub release:
  `ttadev @ git+https://github.com/theinterneti/TTA.dev.git@v0.1.0-alpha`.
  Verified: RetryPrimitive and CachePrimitive import and work correctly.
  Add to `pyproject.toml` after architecture review merge.
- **Action**: Done. Spike verified (< 2 min to install + test).
  Adopt incrementally: RetryPrimitive + CachePrimitive → TimeoutPrimitive →
  MemoryPrimitive + ParallelPrimitive. Document integration pattern
  (wrap async functions as WorkflowPrimitive subclasses).

---

## Frameworks Explicitly Deferred

| Framework | Defer to | Why not now |
|---|---|---|
| **LangGraph** | v4 | Linear playtester sessions; no cyclic workflows yet |
| **React / Svelte** | v3 | htmx sufficient for styled output + choice buttons |
| **WebRTC / WebSockets** | v3 | Still solo through v2.1 |
| **Celery** | n/a | arq already chosen and partially wired |
| **PydanticAI (full agent)** | v3+ | Structured output only at v2.1; lighter options first |

---

## Exit Criteria

- [x] Every row in the Decision Matrix has a verdict and an owner.
- [x] Every REPLACE / AUGMENT verdict has a spike branch + success metric, or ADR.
  - [x] #13 (ttadev): **spike complete** — verified on v0.1.0-alpha release
  - [x] #5 (structured output): **spike complete** — prompt + Pydantic wins
  - [x] #6 (arq worker): **spike complete** — infrastructure ready, call sites mapped
  - [x] #8 (htmx UI): **spike complete** — htmx via script tags, zero deps
  - [x] #12 (rate-limit): **spec written** — `specs/50-rate-limit-budget.md`
- [ ] Decisions reflected in `plans/v2_1-evaluation-and-playtesting.md`.
- [x] Anti-decisions documented and signed off.
- [x] No v2.1 spec work begins on a call site whose architectural choice is TBD.

---

## Open Questions

1. **Does FMR `response_format` work with free Gemini models?** Gates Decision #5.
2. ~~**Is `ttadev` install + test ergonomics acceptable?**~~ ✅ **RESOLVED.** Installs
   from GitHub release `v0.1.0-alpha`. RetryPrimitive and CachePrimitive verified.
   Integration pattern: wrap async functions as `WorkflowPrimitive` subclasses.
3. **What is the Neo4j CE concurrent read ceiling?** Gates Decision #3 at v3.
