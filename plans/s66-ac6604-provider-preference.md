# S66 AC-66.04 Provider-Preference Implementation Plan

> **Status**: 📝 Draft
> **Scope**: S66 AC-66.04 real implementation
> **Owner**: Hermes
> **For Hermes:** Use subagent-driven-development and free-agent-swarm review after each bounded slice; do not claim AC completion until `make trace` shows honest coverage and tests exercise real provider selection behavior.

## Goal

Implement the real AC-66.04 behavior from `specs/66-rate-limit-budget.md`:

- Given Google is `NEAR_LIMIT`
- And NVIDIA is `HEALTHY`
- When a `LOW` tier call is admitted
- Then the call is dispatched to a model on the NVIDIA provider
- And no Google model is used for this call

This is not a logging change. It must affect actual model/provider dispatch order.

## Truth boundary

The spike already introduced a typed provider-utilization signal seam.
That did not complete AC-66.04.

The real blocker discovered during prerequisite analysis is structural:

- `RateLimitBudget` knows provider utilization, but only for admission/logging.
- `LiteLLMClient._call_with_fallback()` owns actual model selection order.
- `ModelRoleConfig` currently exposes only `primary` and `fallback` model strings.
- Default `openai` backend config uses `openai/tta` for both generation primary and fallback, so there is no app-visible provider choice unless config supplies distinct provider-qualified models.

Therefore this slice must do two things:

1. Add an explicit provider-aware candidate ordering seam in the actual client path.
2. Make that seam no-op when there are not multiple distinct provider candidates.

Anything less is fake compliance.

## Design constraints

- Keep existing default behavior unchanged when no provider signal exists.
- Never assume `HEALTHY`; `UNKNOWN` must not outrank explicit healthy providers.
- Do not block `CRITICAL` requests on observability/provider lookup failures.
- Fail open on snapshot lookup errors.
- Do not introduce network dependency for tests.
- Use stdlib + existing repo dependencies only.
- Preserve current fallback/retry semantics inside a selected candidate.

## Proposed implementation

### 1. Extend role config to express provider candidates

Add an optional ordered tuple/list of candidate model strings to `ModelRoleConfig`, with compatibility rules:

- If `candidates` is unset:
  - synthesize candidates from `(primary, fallback?)`
- If `candidates` is set:
  - `primary` becomes the first candidate
  - `fallback` becomes the second candidate when present
  - existing consumers remain compatible

This keeps old config shape working while allowing explicit multi-provider generation choices such as:

- `google/...`
- `nvidia/...`
- `groq/...`

### 2. Add provider-ordering policy helper

Create a helper in `tta.llm.provider_utilization` or `tta.llm.litellm_client` that:

- extracts provider from each candidate model string
- looks up provider state from an injected snapshot mapping
- ranks candidates for low-priority work:
  - `HEALTHY`
  - `ELEVATED`
  - `UNKNOWN`
  - `NEAR_LIMIT`
  - `EXHAUSTED`
- preserves original declaration order as stable tiebreaker

For `CRITICAL`/`HIGH`, keep declared order.
For `LOW`/`BEST_EFFORT`, reorder by utilization preference.

### 3. Thread task tier into the real dispatch path

Today `RateLimitedLLMClient` admits by tier but does not pass tier/provider preference to `LiteLLMClient`.

Add an internal optional dispatch-context parameter through the wrapped client path so the concrete client can know:

- request tier
- provider snapshot (or derived ranking inputs)

Do this without breaking the public `LLMClient` protocol used by call sites. Likely shape:

- keep `LLMClient` public methods unchanged
- add optional concrete-only kwargs on `RateLimitedLLMClient -> LiteLLMClient`
- or add a dedicated internal method used only when the wrapped client supports it

### 4. Reorder candidate traversal in LiteLLMClient

Replace the hard-coded `(primary, fallback)` traversal with:

- build candidate list from config
- reorder list when tier is `LOW`/`BEST_EFFORT` and provider signal exists
- then keep the existing retry-per-tier / fall-through behavior

This is the real AC-66.04 control point.

### 5. Honest deferred-coverage cleanup

Remove the deferred `AC-66.04` skip from `tests/unit/v2_deferred_coverage.py` only after:

- unit tests prove provider-preference ordering
- trace shows AC-66.04 covered by real tests

## Test plan

### Red tests to add first

1. Candidate ordering helper:
   - healthy beats near_limit for LOW
   - exhausted always sorted last for LOW
   - unknown does not beat healthy
   - original order preserved within same state

2. LiteLLMClient dispatch order:
   - when generation config has `google/...` then `nvidia/...`
   - and snapshot marks google `NEAR_LIMIT`, nvidia `HEALTHY`
   - LOW tier attempts NVIDIA first
   - HIGH/CRITICAL still attempt declared primary first

3. No-op compatibility:
   - with no snapshot, declared order remains unchanged
   - with single candidate / same provider on both entries, behavior unchanged

4. RateLimitedLLMClient integration:
   - LOW request passes tier/context into inner client
   - snapshot failure does not crash request path

5. AC marker migration:
   - real AC-66.04 tests get `@pytest.mark.spec("AC-66.04")`
   - deferred skip removed only after the above pass

## Files likely to change

- `src/tta/llm/roles.py`
- `src/tta/llm/litellm_client.py`
- `src/tta/llm/rate_limiter.py`
- `src/tta/llm/provider_utilization.py`
- `tests/unit/llm/test_litellm_client.py`
- `tests/unit/llm/test_rate_limited_client.py`
- `tests/unit/llm/test_provider_utilization.py` or a new focused test module
- `tests/unit/v2_deferred_coverage.py`

## Verification

Minimum gate before claiming completion:

- focused pytest on touched llm modules
- `ruff check src tests`
- `ruff format --check src tests`
- `make trace`

Then perform an independent free-model review swarm against the diff.

## Risks

1. Config/API creep:
   avoid exposing a broad new public API if an internal seam is enough.

2. Fake provider preference on router aliases:
   if both candidates are `openai/tta`, there is no app-visible provider distinction.
   Tests must use provider-qualified model strings.

3. Behavior drift for existing users:
   default order must remain identical unless low-priority provider-aware routing is actually applicable.

## Exit criteria

AC-66.04 is complete only when all are true:

- real tests with `@pytest.mark.spec("AC-66.04")` pass
- deferred skip is removed
- LOW/BEST_EFFORT dispatch demonstrably prefers healthier providers when distinct provider candidates exist
- HIGH/CRITICAL behavior remains unchanged
- `make trace` stays green
