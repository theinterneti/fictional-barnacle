---
name: llm
description: "Skill for the Llm area of fictional-barnacle. 118 symbols across 17 files."
---

# Llm

118 symbols | 17 files | Cohesion: 88%

## When to Use

- Working with code in `tests/`
- Understanding how test_critical_admitted_when_high_tier_at_cap, test_critical_never_waits_even_under_full_load, test_high_tier_capped_at_configured_limit work
- Modifying llm-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/llm/test_s07_ac_compliance.py` | _role_configs, _mock_response, test_response_envelope_has_required_fields, test_caller_uses_role_not_model_name, test_model_resolved_from_config_not_hardcoded (+22) |
| `tests/unit/llm/test_litellm_client.py` | _role_configs, _mock_response, test_happy_path, test_default_params_from_role_config, test_fallback_on_transient_error (+15) |
| `tests/unit/llm/test_rate_limit_budget.py` | test_critical_admitted_when_high_tier_at_cap, test_critical_never_waits_even_under_full_load, test_high_tier_capped_at_configured_limit, test_low_tier_capped_independently, test_critical_unaffected_by_non_critical_caps (+7) |
| `src/tta/llm/rate_limiter.py` | admit, admit_or_queue, release, _sem_for, _timeout_for (+4) |
| `src/tta/llm/litellm_client.py` | generate, stream, _call_with_fallback, _call_with_retries, _call_llm (+2) |
| `src/tta/llm/errors.py` | LLMError, TransientLLMError, PermanentLLMError, AllTiersFailedError, BudgetExceededError (+2) |
| `tests/unit/llm/test_rate_limited_client.py` | test_critical_call_delegates_to_wrapped_client, test_multiple_critical_calls_not_blocked, task, test_high_tier_call_enforces_cap, slow_call (+1) |
| `tests/unit/performance/test_s28_performance.py` | test_metrics_update_on_execute, test_error_in_function_still_decrements, test_semaphore_queues_under_load, test_queue_overflow_returns_service_unavailable, test_semaphore_in_flight_completes |
| `tests/unit/llm/test_semaphore.py` | test_basic_execution, test_concurrency_limited, test_queue_overflow_returns_503, test_timeout_cancels_request, test_active_and_waiting_counts |
| `src/tta/llm/smart_router_client.py` | generate, stream, _ensure_ready, _is_healthy, _error_response |

## Entry Points

Start here when exploring this area:

- **`test_critical_admitted_when_high_tier_at_cap`** (Function) — `tests/unit/llm/test_rate_limit_budget.py:14`
- **`test_critical_never_waits_even_under_full_load`** (Function) — `tests/unit/llm/test_rate_limit_budget.py:45`
- **`test_high_tier_capped_at_configured_limit`** (Function) — `tests/unit/llm/test_rate_limit_budget.py:90`
- **`test_low_tier_capped_independently`** (Function) — `tests/unit/llm/test_rate_limit_budget.py:117`
- **`test_critical_unaffected_by_non_critical_caps`** (Function) — `tests/unit/llm/test_rate_limit_budget.py:138`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `LLMError` | Class | `src/tta/llm/errors.py` | 7 |
| `TransientLLMError` | Class | `src/tta/llm/errors.py` | 15 |
| `PermanentLLMError` | Class | `src/tta/llm/errors.py` | 19 |
| `AllTiersFailedError` | Class | `src/tta/llm/errors.py` | 23 |
| `BudgetExceededError` | Class | `src/tta/llm/errors.py` | 33 |
| `test_critical_admitted_when_high_tier_at_cap` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 14 |
| `test_critical_never_waits_even_under_full_load` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 45 |
| `test_high_tier_capped_at_configured_limit` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 90 |
| `test_low_tier_capped_independently` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 117 |
| `test_critical_unaffected_by_non_critical_caps` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 138 |
| `test_high_tier_call_queues_and_proceeds_when_slot_frees` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 161 |
| `test_fifo_ordering` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 190 |
| `task` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 197 |
| `test_best_effort_dropped_at_backpressure_limit` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 226 |
| `test_backpressure_drop_logs_warning` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 258 |
| `test_admission_logs_structlog_event` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 290 |
| `test_queue_logs_structlog_event` | Function | `tests/unit/llm/test_rate_limit_budget.py` | 300 |
| `admit` | Function | `src/tta/llm/rate_limiter.py` | 81 |
| `admit_or_queue` | Function | `src/tta/llm/rate_limiter.py` | 95 |
| `release` | Function | `src/tta/llm/rate_limiter.py` | 151 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → _is_healthy` | intra_community | 5 |
| `Main → _error_response` | intra_community | 4 |
| `Stream → _is_healthy` | intra_community | 4 |
| `Run_genesis_lite → Generate` | cross_community | 3 |
| `Stream → _error_response` | intra_community | 3 |
| `Admit_or_queue → _sem_for` | intra_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| World | 1 calls |

## How to Explore

1. `gitnexus_context({name: "test_critical_admitted_when_high_tier_at_cap"})` — see callers and callees
2. `gitnexus_query({query: "llm"})` — find related execution flows
3. Read key files listed above for implementation details
