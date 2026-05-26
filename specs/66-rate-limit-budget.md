# S50 — Rate-Limit Budget & Task Prioritization

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.1
> **Level**: 3 — Resilience
> **Dependencies**: S07 (LLM Integration), S23 (Error Handling & Resilience)
> **Companion**: `plans/v2_1-architecture-review.md` §12, `docs/vision/TTA-CRITICAL-REVIEW.md` §1
> **Last Updated**: 2026-05-14

---

## How to Read This Spec

This is a **component specification** — it defines *what* the rate-limit budget
system does and what behaviors it guarantees. The implementation approach
(asyncio semaphores + LiteLLM hooks) is documented in the architecture review
but this spec defines the behavioral contract independent of implementation.

---

## 1. Purpose

v2.1 introduces parallel playtester sessions, richer NPC autonomy, and
procedural content generation — all of which consume LLM capacity from the
same free-model pool that serves player-facing turns. Without a rate-limit
budget, background work will starve player turns, causing unpredictable
latency spikes and cascading failures.

This spec defines a **task-priority system with concurrent-request budgets**
that guarantees player-facing calls always have capacity, while playtester
and background work degrades gracefully under load.

The system operates as an **in-process component**, not an external service
or framework. It intercepts LLM calls at the LiteLLM integration point and
enforces per-task-type concurrency limits.

---

## 2. Design Principles

### 2.1 Player-First, Always

Player-facing calls (turn processing, Genesis v2 interactions) are **never
throttled**. Under any load condition, a player turn must proceed immediately.

### 2.2 Graceful Degradation

When the system is under load, lower-priority tasks slow down or queue
rather than failing. A playtester session that takes 15 minutes instead of
5 is acceptable. A player turn that takes 15 seconds instead of 5 is not.

### 2.3 Provider-Aware

Free-model capacity varies by provider. Google models have per-minute RPM
caps. Groq models have concurrency limits. NVIDIA models have a large pool
but variable per-model availability. The budget tracks per-provider
utilization and shifts background work to underutilized providers.

### 2.4 Observable

Every admission/rejection decision is logged via structlog. Dashboard-able
metrics: active requests per tier, wait times per tier, rejections per tier,
provider utilization per tier.

---

## 3. User Stories

### US-50.1 — Player Turn Under Load

**As a** player, **I want** my turn to process normally **so that** background
playtester activity doesn't make the game feel slow.

**Scenario**: Player submits a turn during 3 concurrent playtester sessions
- **Given** 3 playtester sessions are running (each consuming 1 LLM call slot)
- **And** the system has a maximum playtester concurrency of 3
- **When** the player submits a turn
- **Then** the turn is admitted immediately (player tier has no cap)
- **And** the turn completes within the v1 latency budget (5-8s for standard turns)

### US-50.2 — Playtester Concurrency Cap

**As a** system operator, **I want** playtester sessions to be capped at a
configurable concurrency **so that** they don't overwhelm free-model capacity.

**Scenario**: Starting a 4th playtester session when 3 are running
- **Given** the playtester concurrency cap is 3
- **And** 3 playtester sessions are already running
- **When** a 4th playtester session attempts to start
- **Then** it is queued (not rejected)
- **And** it begins when an existing playtester session completes

### US-50.3 — Background Task Throttling

**As a** system operator, **I want** NPC autonomy and world-time advancement
to slow down under load **so that** they never compete with player turns.

**Scenario**: NPC autonomy fires during heavy playtester load
- **Given** 3 playtester sessions are running (at the playtester cap)
- **And** 2 player turns are processing
- **When** NPC autonomy triggers for 50 NPCs
- **Then** at most 2 NPC autonomy LLM calls run concurrently
- **And** remaining NPC updates are deferred by 30s
- **And** player turns and playtester sessions are unaffected

### US-50.4 — Provider-Aware Routing

**As a** system operator, **I want** background work to prefer underutilized
providers **so that** no single provider is overwhelmed.

**Scenario**: Google models are near RPM cap, NVIDIA models are idle
- **Given** Google provider RPM utilization is above 80%
- **And** NVIDIA provider RPM utilization is below 20%
- **When** a background task (NPC autonomy) requests an LLM call
- **Then** the call is routed preferentially to NVIDIA models
- **And** Google models are reserved for player-facing and playtester calls

---

## 4. Task Priority Tiers

All LLM call sites in the codebase are assigned a priority tier:

| Tier | Priority | Tasks | Concurrency | Latency Budget | Admission |
|------|----------|-------|-------------|----------------|-----------|
| **CRITICAL** | Highest | Player turns, Genesis v2 interactions | Unlimited | 5-8s (standard), 12-15s (complex) | Always admitted |
| **HIGH** | High | Playtester sessions, quality evaluation | Configurable (default: 3) | 30-60s per call | Queued when at cap |
| **LOW** | Low | NPC autonomy, world-time advancement, consequence propagation | Configurable (default: 2) | 60-120s per call | Queued with backpressure |
| **BEST_EFFORT** | Lowest | Cost summaries, TTL monitors, session purging | 1 | No budget | Best-effort, dropped if system overloaded |

### 4.1 Tier Assignment Rules

- **CRITICAL**: Any LLM call that blocks a player-facing response.
  Identified by call site in `games.py` turn pipeline, `genesis_v2.py`
  player interactions.
- **HIGH**: Any LLM call in the playtester harness or evaluation pipeline
  (`quality/evaluator.py`, `simulation/` playtester agents).
- **LOW**: Any LLM call for world simulation that runs asynchronously
  (`npc_autonomy.py`, `world_time.py`, `consequence_service.py`).
- **BEST_EFFORT**: Any LLM call for operational tasks that can be retried
  or dropped (`pool_metrics.py`, cost summaries).

### 4.2 Configurable Defaults

All concurrency caps are configurable via environment variables:

```
TTA_RATE_LIMIT_PLAYTESTER_CONCURRENCY=3
TTA_RATE_LIMIT_BACKGROUND_CONCURRENCY=2
TTA_RATE_LIMIT_PROVIDER_RPM_THRESHOLD=0.8
```

---

## 5. Provider Utilization Tracking

The system tracks per-provider RPM utilization based on observed rate-limit
headers from FMR and provider responses:

### 5.1 Utilization Signals

| Signal | Source | Meaning |
|--------|--------|---------|
| `X-RateLimit-Remaining` | Provider response header | Remaining requests in current window |
| `X-RateLimit-Limit` | Provider response header | Total requests allowed per window |
| `429 Too Many Requests` | HTTP response | Provider rate limit hit |
| `retry-after` | HTTP response header | Seconds until retry allowed |

### 5.2 Utilization States

| State | RPM Utilization | Behavior |
|-------|-----------------|----------|
| **HEALTHY** | < 50% | All tiers can use this provider |
| **ELEVATED** | 50-80% | LOW and BEST_EFFORT prefer other providers |
| **NEAR_LIMIT** | > 80% | Only CRITICAL and HIGH use this provider |
| **EXHAUSTED** | 100% (429 received) | All tiers avoid this provider until cooldown |

### 5.3 Provider Preference for Background Work

When a LOW or BEST_EFFORT task needs an LLM call, the system:
1. Queries current provider utilization states
2. Prefers providers in HEALTHY state
3. Falls back to ELEVATED if no HEALTHY providers available
4. Queues if all providers are NEAR_LIMIT or EXHAUSTED

---

## 6. Functional Requirements

### FR-50.01 — Admission Control

The system MUST check tier concurrency before allowing any LLM call to proceed.
CRITICAL tier calls MUST always be admitted. HIGH, LOW, and BEST_EFFORT calls
MUST be checked against their respective concurrency caps.

### FR-50.02 — Queuing

When a HIGH or LOW tier call is at its concurrency cap, the system MUST queue
the call rather than rejecting it. Queued calls MUST be processed in FIFO order
when capacity becomes available.

### FR-50.03 — Timeout

Queued calls MUST have a configurable timeout. HIGH tier calls time out after
5 minutes. LOW tier calls time out after 10 minutes. Timed-out calls return
an error to the caller.

### FR-50.04 — Provider Awareness

The system MUST track per-provider RPM utilization. When a LOW or BEST_EFFORT
call is queued or admitted, the system MUST prefer providers in HEALTHY or
ELEVATED state.

### FR-50.05 — Observability

The system MUST log every admission, queue, rejection, and completion event
via structlog with: tier, task_type, provider (if known), queue_wait_ms,
and admission_decision (admitted/queued/rejected).

### FR-50.06 — Backpressure

When the BEST_EFFORT queue exceeds 10 pending calls, new BEST_EFFORT calls
MUST be dropped (not queued) with a log warning.

### FR-50.07 — Graceful Shutdown

On server shutdown, queued calls MUST be cancelled with a clear error message.
In-flight calls MUST be allowed to complete within a 30s grace period.

---

## 7. Non-Functional Requirements

### NFR-50.01 — Admission Overhead

Admission control MUST add < 1ms overhead to the LLM call path for CRITICAL
tier calls (the fast path).

### NFR-50.02 — Memory

The component MUST use < 10MB of additional memory under maximum load
(3 HIGH + 2 LOW + 1 BEST_EFFORT concurrent calls).

### NFR-50.03 — No External Dependency

The component MUST NOT require an external service (Redis, database).
All state is in-process.

---

## 8. Acceptance Criteria

### AC-50.01 — Player Turn Not Blocked

**Given** the system is at maximum playtester concurrency (3 HIGH tier calls)
**And** 2 LOW tier calls are running
**When** a player submits a turn (CRITICAL tier)
**Then** the turn LLM call is admitted immediately
**And** the turn completes without queuing

### AC-50.02 — Playtester Queued at Cap

**Given** the playtester concurrency cap is 3
**And** 3 playtester sessions are running
**When** a 4th playtester session starts
**Then** its first LLM call is queued (not rejected)
**And** it proceeds when an existing playtester session completes

### AC-50.03 — Background Throttled

**Given** the background concurrency cap is 2
**And** 2 LOW tier calls are running
**When** a 3rd LOW tier call is requested
**Then** it is queued
**And** CRITICAL tier calls are unaffected

### AC-50.04 — Provider Preference

**Given** Google provider is at NEAR_LIMIT (>80% RPM)
**And** NVIDIA provider is HEALTHY (<50% RPM)
**When** a LOW tier call is admitted
**Then** the call is dispatched to a model on the NVIDIA provider
**And** no Google model is used for this call

### AC-50.05 — Structlog Events

**Given** any LLM call passes through admission control
**When** the admission decision is made
**Then** a structlog event is emitted with: tier, task_type, decision,
queue_depth (if queued), and provider_utilization (if provider-aware)

### AC-50.06 — Backpressure

**Given** the BEST_EFFORT queue has 10 pending calls
**When** an 11th BEST_EFFORT call is requested
**Then** it is dropped (not queued)
**And** a structlog warning is emitted with queue_depth=10 and decision=dropped

---

## 9. Integration Points

### 9.1 LiteLLM Client

The admission control wraps `LiteLLMClient.generate()` and `LiteLLMClient.stream()`.
All existing call sites use the wrapped client — no call-site changes needed.

### 9.2 arq Workers (v2.1)

When arq workers are adopted for background tasks (Decision #6), the admission
control applies per-worker-process. Each worker has its own in-process state.
The CRITICAL tier only applies to the API process (player turns).

### 9.3 FMR

FMR receives the `task` parameter in chat completions. The rate-limit budget
can optionally set this to communicate priority to FMR's own routing. Not
required for v2.1; FMR's `model:auto` already handles provider-level routing.

### 9.4 Langfuse

Admission/rejection events are traced to Langfuse as span events on the LLM
generation span. This enables dashboard queries: "show me rejection rate by
tier over the last 24h."

---

## 10. Implementation Notes

- **Location**: `src/tta/llm/rate_limiter.py`
- **Key class**: `RateLimitBudget` — holds semaphores per tier, provider state
- **Wrap pattern**: `RateLimitedLLMClient` wraps `LiteLLMClient`, delegates
  CRITICAL calls directly, enforces caps on other tiers
- **Provider tracking**: Parse `X-RateLimit-*` headers from LiteLLM responses.
  LiteLLM doesn't expose these natively — may need to read from
  `litellm.response_cost` or raw response headers (TBD in spike).
- **Testability**: All state is in-process — unit-testable without FMR.
  `MockRateLimitBudget` can inject utilization states.

---

## 11. Open Questions

1. **Does LiteLLM expose provider rate-limit headers?** The provider-awareness
   feature (FR-50.04) depends on reading `X-RateLimit-Remaining` from provider
   responses. If LiteLLM doesn't expose these, we need an alternative signal
   (e.g., tracking 429 responses ourselves, or using FMR's `/v1/router/capacity`
   endpoint).

2. **What is the actual concurrency ceiling?** The default caps (3 playtester,
   2 background) are estimates. The v2.1 stress test (Decision #1) should
   empirically determine safe caps before production use.

3. **Should FMR handle this instead?** FMR already has provider-level routing
   and cooldown logic. The architecture review decided to build this in-process
   because FMR doesn't have task-priority awareness. If FMR adds tier-based
   admission, this component could delegate to it.
