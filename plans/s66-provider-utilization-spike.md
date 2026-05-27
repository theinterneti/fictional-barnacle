# S66 Provider-Utilization Signal Spike Implementation Plan

> **Status**: 📝 Draft
> **Scope**: S66 AC-66.04 provider awareness spike only
> **Input Spec**: S66
> **Last Updated**: 2026-05-27

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task after plan review approves it.

**Goal:** Choose and prove the provider-utilization signal that will unlock AC-66.04 without prematurely building provider-aware routing.

**Architecture:** This is a spike slice, not the full provider-aware routing implementation. It adds a small, typed provider-utilization signal seam that can be fed by observed LiteLLM/FMR outcomes, then verifies that `RateLimitBudget` can receive and log provider state without changing model selection yet. The output must be an implementation recommendation with no-spend evidence.

**Tech Stack:** Python 3.12, pytest, structlog `capture_logs`, existing `tta.llm.rate_limiter`, existing `tta.llm.litellm_client`, optional HTTP probing via `httpx` only if the repo already depends on it.

---

## 1. Why this plan exists

S66 is approved, but AC-66.04 is intentionally deferred. The current implementation logs `provider_utilization=None` and does not route LOW or BEST_EFFORT calls by provider. The spec requires provider-aware behavior, but the repo has not selected a trustworthy source of provider utilization yet.

This plan turns AC-66.04 into a bounded spike with a clear truth boundary:

- allowed: choose and prove a provider-utilization signal seam;
- allowed: add pure parsing/state tests for utilization states;
- allowed: log provider utilization when supplied;
- forbidden: claim AC-66.04 complete until background calls actually prefer HEALTHY/ELEVATED providers over NEAR_LIMIT/EXHAUSTED providers.

## 2. Current-state evidence

Relevant files:

- `specs/66-rate-limit-budget.md` — AC-66.04 and the approval reality-check deferral.
- `src/tta/llm/rate_limiter.py` — `RateLimitBudget._log_decision()` emits `provider_utilization=None` today.
- `src/tta/llm/litellm_client.py` — has model/provider naming, router task hints, LiteLLM calls, retry/fallback handling, and `llm_call_complete` logs.
- `tests/unit/v2_deferred_coverage.py` — marks `AC-66.04` as skipped/deferred.
- `tests/unit/llm/test_rate_limit_budget.py` — existing S66 admission/logging coverage.

Known signal candidates from S66 approval:

1. LiteLLM response metadata / response headers.
2. Observed 429s and retry-after metadata from thrown exceptions.
3. FMR capacity/readiness endpoint.

## 3. Design decision to make

The spike must choose the first implementation target using these criteria:

| Candidate | Deterministic in unit tests | No-spend friendly | Runtime authority | Coupling risk | Notes |
|-----------|-----------------------------|-------------------|-------------------|---------------|-------|
| LiteLLM response metadata/headers | Medium | High | Medium | Medium | Best if headers are exposed consistently by LiteLLM/FMR responses. |
| Observed 429/retry-after events | High | High | High for exhaustion, weak for healthy/elevated | Low | Good fallback signal; insufficient alone for underutilized-provider preference. |
| FMR capacity endpoint | High with fake HTTP client | High | Highest if endpoint exists and is stable | Medium | Best for proactive routing, but only if endpoint contract is discoverable and local-first. |

Recommendation bias before implementation: prefer a composable provider-state interface that can ingest both FMR snapshots and observed errors. Do not make `RateLimitBudget` depend directly on HTTP or LiteLLM object internals.

## 4. Technology and architecture

This slice uses standard-library dataclasses/enums/protocols plus pytest and structlog test capture. It intentionally avoids new runtime dependencies unless the spike proves an existing repo dependency is already the right seam.

### 4.1 Data models

Create a small provider-state module if the spike confirms no equivalent exists:

```python
# src/tta/llm/provider_utilization.py
from dataclasses import dataclass
from enum import StrEnum

class ProviderUtilizationState(StrEnum):
    HEALTHY = "healthy"
    ELEVATED = "elevated"
    NEAR_LIMIT = "near_limit"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class ProviderUtilization:
    provider: str
    state: ProviderUtilizationState
    rpm_utilization: float | None = None
    retry_after_seconds: float | None = None
    source: str = "unknown"
```

The spike may rename fields if code review finds a better fit, but it must keep the model small and serializable.

### 4.2 Interfaces

Keep the interface pure and injectable:

```python
class ProviderUtilizationSource(Protocol):
    def snapshot(self) -> Mapping[str, ProviderUtilization]: ...
```

`RateLimitBudget` should accept an optional snapshot/source and include the relevant state in logs when task/provider context is known. Full provider choice can wait for the implementation slice after the spike.

### 4.3 Truth boundary

The spike is complete when it answers:

- Which signal source should feed AC-66.04 first?
- What shape does provider utilization take inside TTA?
- How will LOW/BEST_EFFORT routing consume it in the next slice?
- What tests prove the selected signal without live spend?

The spike is not complete if it merely adds more `None` placeholders or generic TODOs.

## 5. Task plan

### Task 1: Inventory actual provider signal surfaces

**Objective:** Verify what the current repo and local FMR-compatible path can expose without guessing.

**Files:**
- Read: `src/tta/llm/litellm_client.py`
- Read: `src/tta/llm/errors.py`
- Read: `src/tta/llm/rate_limiter.py`
- Optional read: local FMR docs/config if reachable outside this repo

**Step 1: Search for existing signal primitives**

Run:

```bash
search_files equivalent: provider_utilization|retry-after|RateLimit|429|headers|fmr|capacity
```

Expected: exact inventory of existing code paths and gaps.

**Step 2: Inspect LiteLLM exception shape in tests, not live calls**

Use synthetic exception objects or existing error classification tests. Do not spend tokens.

**Step 3: Record decision evidence**

Update this plan or a short spike note with the chosen source and rejected alternatives.

**Step 4: Commit**

```bash
git add plans/s66-provider-utilization-spike.md
git commit -m "docs: plan S66 provider utilization spike"
```

### Task 2: Add provider-utilization parsing tests

**Objective:** Define the pure state mapping before any runtime integration.

**Files:**
- Create: `tests/unit/llm/test_provider_utilization.py`
- Create or modify: `src/tta/llm/provider_utilization.py`

**Step 1: Write failing tests**

Tests should cover:

```python
@pytest.mark.spec("AC-66.04")
def test_utilization_from_remaining_and_limit_headers_marks_near_limit(): ...

@pytest.mark.spec("AC-66.04")
def test_observed_429_marks_provider_exhausted_with_retry_after(): ...

@pytest.mark.spec("AC-66.04")
def test_missing_signal_is_unknown_not_healthy(): ...
```

Expected first run: FAIL because module/functions do not exist.

**Step 2: Implement minimal pure parser/state model**

Keep implementation independent of LiteLLM and HTTP clients.

**Step 3: Verify**

Run:

```bash
uv run pytest tests/unit/llm/test_provider_utilization.py -q
uv run ruff check src/tta/llm/provider_utilization.py tests/unit/llm/test_provider_utilization.py
uv run ruff format --check src/tta/llm/provider_utilization.py tests/unit/llm/test_provider_utilization.py
```

### Task 3: Thread provider utilization into admission logs without routing

**Objective:** Replace `provider_utilization=None` with supplied state when available, while preserving existing behavior when absent.

**Files:**
- Modify: `src/tta/llm/rate_limiter.py`
- Modify: `tests/unit/llm/test_rate_limit_budget.py`

**Step 1: Write failing log-shape test**

Add a test that injects a provider state snapshot and asserts the structlog event includes:

- provider name when known;
- provider utilization state;
- utilization source;
- no provider-aware routing claim yet.

**Step 2: Implement minimal injection seam**

Do not call HTTP from `RateLimitBudget`. Pass in a source/snapshot object or explicit context.

**Step 3: Verify**

Run:

```bash
uv run pytest tests/unit/llm/test_rate_limit_budget.py tests/unit/llm/test_provider_utilization.py -q
```

### Task 4: Produce implementation recommendation for the real AC-66.04 slice

**Objective:** Convert spike output into the next implementable work item.

**Files:**
- Modify: `plans/s66-provider-utilization-spike.md`
- Modify or create: `.barnacle/work/items/FB-06604.json`
- Optionally modify: `tests/unit/v2_deferred_coverage.py` only when AC-66.04 is actually implemented; do not remove the skip during the spike.

**Step 1: Add a Spike Result section**

Document:

- selected source;
- implementation seam;
- rejected alternatives;
- exact next tests for routing behavior.

**Step 2: Keep AC-66.04 deferred unless routing exists**

The skipped deferred test remains until LOW/BEST_EFFORT calls actually prefer healthier providers.

**Step 3: Verify planning state**

Run:

```bash
uv run python plans/index_plans.py --validate
uv run python scripts/workflow_state.py status
make trace
```

## 6. Testing strategy

Use no-spend tests only:

- Pure parser tests for headers/errors/snapshots.
- Structlog capture tests for admission decisions enriched with provider state.
- Fake provider source/snapshot objects; no live LiteLLM/FMR calls.
- Existing `make trace` to ensure `AC-66.04` remains represented honestly.

Do not run live LLM calls for this spike. If a local FMR endpoint must be probed, use only read-only metadata/capacity endpoints and enforce these safeguards before the command runs:

- URL path must not be `/v1/chat/completions`, `/v1/completions`, `/v1/responses`, or any endpoint that dispatches model work.
- Command must be `GET` only; no request body containing `messages`, `prompt`, `model`, or `task`.
- Prefer `curl --head` or `curl --get` against documented capacity/readiness/status paths.
- Capture and paste the exact response shape into the Spike Result section before implementation consumes it.


## 7. Acceptance criteria for this plan

- The plan is indexed by `plans/index_plans.py` without new warnings specific to this file.
- A machine-readable work item references `specs/66-rate-limit-budget.md`, this plan, and `AC-66.04`.
- The first implementation task is a spike with no-spend evidence, not a routing rewrite.
- AC-66.04 remains truthfully deferred until routing behavior exists.

## 8. Validation commands

```bash
uv run python plans/index_plans.py --validate
uv run python scripts/workflow_state.py status
make trace
```

Full implementation closeout, after the spike tasks are complete:

```bash
uv run pytest tests/unit/llm/test_provider_utilization.py tests/unit/llm/test_rate_limit_budget.py -q
uv run ruff format --check src/tta/llm/provider_utilization.py tests/unit/llm/test_provider_utilization.py tests/unit/llm/test_rate_limit_budget.py
uv run ruff check src/tta/llm/provider_utilization.py tests/unit/llm/test_provider_utilization.py tests/unit/llm/test_rate_limit_budget.py
make complete-check
make gate
```
