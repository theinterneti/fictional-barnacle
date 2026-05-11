---
name: llm
description: "Skill for the Llm area of fictional-barnacle. 90 symbols across 12 files."
---

# Llm

90 symbols | 12 files | Cohesion: 86%

## When to Use

- Working with code in `tests/`
- Understanding how test_response_envelope_has_required_fields, test_caller_uses_role_not_model_name, test_model_resolved_from_config_not_hardcoded work
- Modifying llm-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/llm/test_s07_ac_compliance.py` | _role_configs, _mock_response, test_response_envelope_has_required_fields, test_caller_uses_role_not_model_name, test_model_resolved_from_config_not_hardcoded (+22) |
| `tests/unit/llm/test_litellm_client.py` | _role_configs, _mock_response, test_happy_path, test_default_params_from_role_config, test_fallback_on_transient_error (+15) |
| `src/tta/llm/litellm_client.py` | generate, stream, _call_with_fallback, _call_with_retries, _call_llm (+2) |
| `src/tta/llm/smart_router_client.py` | generate, stream, _ensure_ready, _is_healthy, _error_response (+2) |
| `src/tta/llm/errors.py` | LLMError, TransientLLMError, PermanentLLMError, AllTiersFailedError, BudgetExceededError (+2) |
| `tests/unit/performance/test_s28_performance.py` | test_metrics_update_on_execute, test_error_in_function_still_decrements, test_semaphore_queues_under_load, test_queue_overflow_returns_service_unavailable, test_semaphore_in_flight_completes |
| `tests/unit/llm/test_semaphore.py` | test_basic_execution, test_concurrency_limited, test_queue_overflow_returns_503, test_timeout_cancels_request, test_active_and_waiting_counts |
| `scripts/llm_player.py` | get_llm_reflection, main, get_player_input |
| `tests/unit/llm/test_llm_client.py` | test_generate_returns_valid_response, test_stream_returns_llm_response, test_satisfies_llm_client_protocol |
| `src/tta/llm/testing.py` | _build_response, generate, stream |

## Entry Points

Start here when exploring this area:

- **`test_response_envelope_has_required_fields`** (Function) — `tests/unit/llm/test_s07_ac_compliance.py:122`
- **`test_caller_uses_role_not_model_name`** (Function) — `tests/unit/llm/test_s07_ac_compliance.py:149`
- **`test_model_resolved_from_config_not_hardcoded`** (Function) — `tests/unit/llm/test_s07_ac_compliance.py:165`
- **`test_primary_failure_triggers_fallback`** (Function) — `tests/unit/llm/test_s07_ac_compliance.py:190`
- **`test_all_tiers_fail_raises_llm_error`** (Function) — `tests/unit/llm/test_s07_ac_compliance.py:209`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `LLMError` | Class | `src/tta/llm/errors.py` | 7 |
| `TransientLLMError` | Class | `src/tta/llm/errors.py` | 15 |
| `PermanentLLMError` | Class | `src/tta/llm/errors.py` | 19 |
| `AllTiersFailedError` | Class | `src/tta/llm/errors.py` | 23 |
| `BudgetExceededError` | Class | `src/tta/llm/errors.py` | 33 |
| `test_response_envelope_has_required_fields` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 122 |
| `test_caller_uses_role_not_model_name` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 149 |
| `test_model_resolved_from_config_not_hardcoded` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 165 |
| `test_primary_failure_triggers_fallback` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 190 |
| `test_all_tiers_fail_raises_llm_error` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 209 |
| `test_fallback_tier_recorded_in_response` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 226 |
| `test_permanent_error_does_not_use_fallback` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 245 |
| `test_per_turn_cost_tracked_in_response` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 435 |
| `test_cost_defaults_to_zero_when_pricing_unavailable` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 512 |
| `test_mock_intercepts_acompletion_not_real_call` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 535 |
| `test_full_call_path_exercised_in_mock_mode` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 552 |
| `test_mock_mode_configurable_per_role` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 579 |
| `test_litellm_acompletion_is_patched_not_called_directly` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 609 |
| `generate` | Function | `src/tta/llm/litellm_client.py` | 63 |
| `test_metrics_update_on_execute` | Function | `tests/unit/performance/test_s28_performance.py` | 136 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → _is_healthy` | intra_community | 5 |
| `Main → _error_response` | intra_community | 4 |
| `Stream → _is_healthy` | intra_community | 4 |
| `Stream → _error_response` | intra_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| World | 1 calls |

## How to Explore

1. `gitnexus_context({name: "test_response_envelope_has_required_fields"})` — see callers and callees
2. `gitnexus_query({query: "llm"})` — find related execution flows
3. Read key files listed above for implementation details
