# v2.1 Architecture Review

> **Status**: 📝 Template — fill in as the review is conducted
> **Created**: 2026-05-13
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

Fill in as decisions are made. Verdicts: **KEEP** · **REPLACE** · **AUGMENT** · **DEFER**.

| # | Choice | Verdict | Action this version | Owner |
|---|--------|---------|---------------------|-------|
| 1 | Single FastAPI process | _TBD_ | | |
| 2 | LiteLLM library mode (vs. direct FMR HTTP) | _TBD_ | | |
| 3 | Neo4j CE | _TBD_ | | |
| 4 | SSE transport | _TBD_ | | |
| 5 | Manual JSON parsing for LLM output | _TBD_ | | |
| 6 | In-process async for background work | _TBD_ | | |
| 7 | Jinja2 prompt templating | _TBD_ | | |
| 8 | Static HTML/JS player UI | _TBD_ | | |
| 9 | Tenacity-only resilience | _TBD_ | | |
| 10 | No dedicated cache layer | _TBD_ | | |
| 11 | No image-gen client | _TBD_ (new for v2.1) | | |
| 12 | No rate-limit budget | _TBD_ (new for v2.1) | | |
| 13 | No `ttadev` dependency | _TBD_ (new for v2.1) | | |

---

## Method

For each choice below, answer four questions:

1. **What it is** — current state in code (file path, key abstraction).
2. **Why it was chosen** — v1 reasoning (link to spec/plan).
3. **What we learned** — what shipping v1 + v2.0 actually taught us.
4. **What v2.1 demands** — does this choice still serve the version's scope?

Then issue a verdict and an action. If the verdict is REPLACE or AUGMENT,
require a spike branch with a defined success metric before the change merges.

---

## 1. Single FastAPI Process

- **What it is**: `src/tta/app.py` — single ASGI app, single process, in-process pipelines.
- **Why it was chosen**: `plans/system.md` — solo dev, no microservices, simplicity over scale.
- **What we learned**: _v2.0 NPC autonomy / playtester concurrency observations go here._
- **What v2.1 demands**: Parallel playtester sessions, stress test (CRITICAL-REVIEW §4).
- **Verdict**: _TBD_
- **Action**: _TBD_ (likely: keep + add `arq` worker process for background work)

## 2. LiteLLM Library Mode

- **What it is**: `src/tta/llm/litellm_client.py` calls `litellm.acompletion(...)` directly. FMR is a routed provider.
- **Why it was chosen**: `specs/07-llm-integration.md` — abstract provider, keep proxy out of process tree.
- **What we learned**: _Recent multi-backend work (#193) hardened this — note actual experience._
- **What v2.1 demands**: Structured output (quality scoring, choice classification). LiteLLM supports `response_format=` natively against most providers; FMR support is the unknown.
- **Verdict**: _TBD_
- **Action**: Verify FMR `response_format` support; if missing, decide between PydanticAI/instructor wrapper or contributing upstream to FMR.

## 3. Neo4j Community Edition

- **What it is**: Neo4j CE 5.x via `neo4j>=6.0` driver. Graph holds world, NPCs, consequences, locations.
- **Why it was chosen**: `plans/system.md` — OSS, no parallel-query limit at our scale.
- **What we learned**: _v2.0 graph query volume observations go here._
- **What v2.1 demands**: Quality eval reads, richer location/NPC/faction graphs, playtester parallelism. CRITICAL-REVIEW §6 flags CE ceiling.
- **Verdict**: _TBD_
- **Action**: Benchmark concurrent read throughput under simulated playtester load. Decide whether CE survives v3.

## 4. SSE Transport

- **What it is**: FastAPI native `EventSourceResponse` streaming turn output to player.
- **Why it was chosen**: `plans/api-and-sessions.md` — one-way, simple, well-supported.
- **What we learned**: _v2.0 transport-abstraction work informs this._
- **What v2.1 demands**: Still solo player. SSE remains sufficient.
- **Verdict**: _TBD_ (default: KEEP, revisit at v3 invite multiplayer)

## 5. Manual JSON Parsing for LLM Output

- **What it is**: Hand-rolled parsing/validation in pipeline stages (Understand, choice classification, etc.).
- **Why it was chosen**: v1 only had a small number of structured calls.
- **What we learned**: _Failure-rate data from production traces goes here._
- **What v2.1 demands**: Many new structured-output sites — coherence/tone/pacing scores, tone tags, lore checks, choice classification. STRATEGY's "frequent and fragile" trigger fires here.
- **Verdict**: _TBD_ (candidates: LiteLLM native `response_format` · `instructor` · `pydantic-ai`)
- **Action**: Spike branch — implement one v2.1 structured call three ways, measure failure rate × 100 runs against free models. Pick winner before writing v2.1 quality specs.

## 6. In-Process Async for Background Work

- **What it is**: NPC autonomy, consequence propagation run as `asyncio.create_task(...)` in the API process.
- **Why it was chosen**: v1 had no background work; v2.0 kept it simple.
- **What we learned**: `arq>=0.25` is already in `pyproject.toml` — verify whether it is wired in or vestigial.
- **What v2.1 demands**: Playtester sessions are long-running, expensive, and parallel. They will starve player-facing turns if they share the API process.
- **Verdict**: _TBD_ (default: AUGMENT — adopt arq for playtester runs and NPC autonomy; keep player turn path in-process)
- **Action**: Define which task types run where. Document in `plans/v2_1-evaluation-and-playtesting.md`.

## 7. Jinja2 Prompt Templating

- **What it is**: `src/tta/prompts/` — Jinja2 templates rendered with world-state context.
- **Why it was chosen**: `plans/prompts.md` — familiar, debuggable, no abstraction overhead.
- **What we learned**: _Prompt-iteration friction observations go here._
- **What v2.1 demands**: Versioned prompts in Langfuse, A/B comparison. Langfuse v4 has its own prompt management.
- **Verdict**: _TBD_ (default: KEEP for composition, ADOPT Langfuse prompt store for versioning)

## 8. Static HTML/JS Player UI

- **What it is**: Minimal `index.html` with `EventSource` consumer.
- **Why it was chosen**: v1 needed a test harness, not a client.
- **What we learned**: _Playtester feedback (when available) goes here._
- **What v2.1 demands**: Styled output, choice buttons, scene metadata display, basic image rendering (basic portraits land in v2.1).
- **Verdict**: _TBD_ (default: AUGMENT with htmx or Alpine over existing HTML; defer React/Svelte to v3)
- **Action**: Decide between htmx and Alpine. Both are dependency-light; pick one before writing v2.1 UI specs.

## 9. Tenacity-Only Resilience

- **What it is**: `tenacity>=9.0` decorators on LLM calls and Neo4j queries.
- **Why it was chosen**: `plans/resilience-and-safety.md` — single proven retry library, no custom code.
- **What we learned**: _Production retry-failure patterns go here._
- **What v2.1 demands**: Playtester runs need timeouts; concurrent calls need circuit breakers; rate-limit budget needs cooperative throttling. STRATEGY recommends `ttadev` primitives.
- **Verdict**: _TBD_ (default: AUGMENT — adopt `ttadev` RetryPrimitive + CachePrimitive + TimeoutPrimitive)

## 10. No Dedicated Cache Layer

- **What it is**: Redis is present but used for sessions only. No memoization of LLM outputs, no scenario-seed cache, no playtester memory.
- **Why it was chosen**: v1 didn't repeat enough work to need it.
- **What v2.1 demands**: Playtester runs replay similar scenarios; Genesis can cache phase outputs; image gen benefits from prompt → URL caching.
- **Verdict**: _TBD_ (default: AUGMENT — adopt `ttadev` CachePrimitive over Redis)

## 11. No Image-Gen Client (NEW for v2.1)

- **What it is**: Not present today. v2.1 introduces basic portraits.
- **What v2.1 demands**: Image generation from world-state-derived prompts. Storage for generated assets.
- **Candidates**: Route through FMR (consistent layering) · `fal-client` · `replicate` · direct provider SDKs.
- **Verdict**: _TBD_
- **Action**: One-page ADR comparing FMR routing vs. direct client. Decide before writing image-gen specs.

## 12. No Rate-Limit Budget (NEW for v2.1)

- **What it is**: Not present today. CRITICAL-REVIEW §1 flagged this as required *before* v2.1.
- **What v2.1 demands**: Player-facing calls must not starve under playtester / NPC-autonomy load. Per-task-type RPM budgets across provider tiers.
- **Verdict**: _TBD_ (default: BUILD — in-process component, not a framework. asyncio semaphores keyed by task type, provider-aware via LiteLLM hooks.)
- **Action**: Write component spec before any v2.1 work that adds new LLM call sites.

## 13. No `ttadev` Dependency (NEW for v2.1)

- **What it is**: Not present today. STRATEGY recommends adopting at v2.1.
- **What v2.1 demands**: Cache, Memory, Timeout, Parallel primitives across playtester harness.
- **Verdict**: _TBD_
- **Action**: Throwaway branch test integration first (Open Decision #5 in STRATEGY). Adopt incrementally — RetryPrimitive + CachePrimitive first, others as needed.

---

## Frameworks Explicitly Deferred

Recording the *non-adoptions* so they don't get re-debated mid-v2.1.

| Framework | Defer to | Why not now |
|---|---|---|
| **LangGraph** | v4 | Playtester sessions are linear; NPC autonomy is fire-and-forget. No cyclic/resumable workflow yet. STRATEGY anti-pattern: "adopting a framework for future needs." |
| **React / Svelte** | v3 | v2.1 UI is styled output + choice buttons. htmx/Alpine over existing HTML is sufficient. Greenfield SPA client lands when character sheet + map arrive. |
| **WebRTC / WebSockets** | v3 | Still solo through v2.1. |
| **Celery** | n/a | `arq` already chosen. Stick with it. |
| **PydanticAI (as full agent framework)** | v3+ | If structured output is the only need, lighter options (LiteLLM native, `instructor`) are evaluated in §5 first. |

---

## Exit Criteria

This review is **done** when:

- [ ] Every row in the Decision Matrix has a verdict and an owner.
- [ ] Every REPLACE / AUGMENT verdict has a spike branch + success metric, or an ADR.
- [ ] Decisions are reflected in `plans/v2_1-evaluation-and-playtesting.md`.
- [ ] Anti-decisions (Frameworks Explicitly Deferred) are documented and signed off.
- [ ] No v2.1 spec work begins on a call site whose underlying architectural choice is still _TBD_.

---

## Open Questions

_Move items here when the review surfaces decisions that need broader input._

1. _e.g., "Does FMR `response_format` work end-to-end with free Gemini models?"_
2. _e.g., "Is `ttadev` install + test ergonomics acceptable on a fresh clone?"_
