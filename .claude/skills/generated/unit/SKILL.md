---
name: unit
description: "Skill for the Unit area of fictional-barnacle. 120 symbols across 9 files."
---

# Unit

120 symbols | 9 files | Cohesion: 100%

## When to Use

- Working with code in `tests/`
- Understanding how test_trace_created, test_generation_recorded, test_error_updates_trace work
- Modifying unit-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/test_wave18.py` | _make, test_normal_text_unchanged, test_strips_zero_width_space, test_strips_bom, test_strips_zero_width_joiner (+22) |
| `tests/unit/test_observability.py` | _fake_llm_response, _install_mock_client, test_trace_created, _call, test_generation_recorded (+21) |
| `tests/unit/test_s15_observability.py` | test_record_llm_generation_no_output_truncation, _make_llm_response, test_record_llm_generation_noop_when_disabled, test_record_llm_generation_calls_langfuse, test_record_llm_generation_uses_v4_observation_api_when_trace_missing (+10) |
| `tests/unit/test_wave19.py` | _sample_value, test_after_observes_duration, test_error_cleans_timing_and_observes, test_get_increments, test_set_increments (+9) |
| `tests/unit/test_config.py` | build_settings, test_with_required_env, test_missing_database_url_raises, test_missing_neo4j_password_raises, test_default_values (+8) |
| `tests/unit/test_logging.py` | _make_settings, test_redacts_player_input_by_default, test_allows_player_input_when_sensitive, test_redacts_all_pii_content_fields, test_credential_fields_always_redacted (+6) |
| `tests/unit/test_context_and_cost.py` | _make_chunk, test_all_fit, test_p3_dropped_first, test_p2_dropped_after_p3, test_p0_never_dropped (+5) |
| `tests/unit/llm/test_s07_ac_compliance.py` | test_session_budget_check_returns_exceeded_at_cap, test_session_budget_check_returns_warning_near_cap, test_session_budget_check_returns_ok_under_cap |
| `src/tta/privacy/cost.py` | check_session_budget |

## Entry Points

Start here when exploring this area:

- **`test_trace_created`** (Function) — `tests/unit/test_observability.py:164`
- **`test_generation_recorded`** (Function) — `tests/unit/test_observability.py:180`
- **`test_error_updates_trace`** (Function) — `tests/unit/test_observability.py:201`
- **`test_kwargs_passed_as_input`** (Function) — `tests/unit/test_observability.py:218`
- **`test_session_id_in_trace`** (Function) — `tests/unit/test_observability.py:234`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_trace_created` | Function | `tests/unit/test_observability.py` | 164 |
| `test_generation_recorded` | Function | `tests/unit/test_observability.py` | 180 |
| `test_error_updates_trace` | Function | `tests/unit/test_observability.py` | 201 |
| `test_kwargs_passed_as_input` | Function | `tests/unit/test_observability.py` | 218 |
| `test_session_id_in_trace` | Function | `tests/unit/test_observability.py` | 234 |
| `test_correlation_id_in_metadata` | Function | `tests/unit/test_observability.py` | 248 |
| `test_turn_id_in_generation_metadata` | Function | `tests/unit/test_observability.py` | 262 |
| `test_no_session_id_omitted_from_trace` | Function | `tests/unit/test_observability.py` | 277 |
| `test_trace_creation_failure` | Function | `tests/unit/test_observability.py` | 297 |
| `test_generation_record_failure` | Function | `tests/unit/test_observability.py` | 310 |
| `test_error_update_failure` | Function | `tests/unit/test_observability.py` | 325 |
| `test_trace_tagged_user_input` | Function | `tests/unit/test_observability.py` | 358 |
| `test_error_message_sanitized_in_trace` | Function | `tests/unit/test_observability.py` | 403 |
| `test_record_llm_generation_no_output_truncation` | Function | `tests/unit/test_s15_observability.py` | 175 |
| `test_record_llm_generation_noop_when_disabled` | Function | `tests/unit/test_s15_observability.py` | 236 |
| `test_record_llm_generation_calls_langfuse` | Function | `tests/unit/test_s15_observability.py` | 251 |
| `test_record_llm_generation_uses_v4_observation_api_when_trace_missing` | Function | `tests/unit/test_s15_observability.py` | 295 |
| `test_record_llm_generation_strips_pii` | Function | `tests/unit/test_s15_observability.py` | 336 |
| `test_record_llm_generation_pseudonymizes_player` | Function | `tests/unit/test_s15_observability.py` | 380 |
| `test_record_llm_generation_includes_prompt_provenance_metadata` | Function | `tests/unit/test_s15_observability.py` | 415 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Resilience | 1 calls |

## How to Explore

1. `gitnexus_context({name: "test_trace_created"})` — see callers and callees
2. `gitnexus_query({query: "unit"})` — find related execution flows
3. Read key files listed above for implementation details
