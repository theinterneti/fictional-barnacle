---
name: observability
description: "Skill for the Observability area of fictional-barnacle. 46 symbols across 5 files."
---

# Observability

46 symbols | 5 files | Cohesion: 100%

## When to Use

- Working with code in `tests/`
- Understanding how test_shutdown_with_provider, test_tracer_name, test_returns_hex_inside_span work
- Modifying observability-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/observability/test_s15_ac_compliance.py` | _settings, test_json_processor_added_when_log_format_json, test_privacy_filter_in_processor_chain, test_merge_contextvars_in_chain, test_log_level_configurable (+15) |
| `tests/unit/observability/test_tracing.py` | _make_in_memory_provider, test_shutdown_with_provider, test_tracer_name, test_returns_hex_inside_span, test_consistent_within_span (+5) |
| `src/tta/observability/langfuse.py` | record_llm_generation, wrapper, _get_context_ids, _warn_langfuse_error, _sanitize_input (+3) |
| `src/tta/observability/daily_cost.py` | get_daily_costs, get_daily_turns, reset_daily_costs, _seconds_until_midnight_utc, daily_cost_summary_loop |
| `src/tta/observability/pool_metrics.py` | _sample_once, _sampler_loop, start_pool_metrics_sampler |

## Entry Points

Start here when exploring this area:

- **`test_shutdown_with_provider`** (Function) — `tests/unit/observability/test_tracing.py:123`
- **`test_tracer_name`** (Function) — `tests/unit/observability/test_tracing.py:149`
- **`test_returns_hex_inside_span`** (Function) — `tests/unit/observability/test_tracing.py:166`
- **`test_consistent_within_span`** (Function) — `tests/unit/observability/test_tracing.py:176`
- **`test_records_error`** (Function) — `tests/unit/observability/test_tracing.py:195`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_shutdown_with_provider` | Function | `tests/unit/observability/test_tracing.py` | 123 |
| `test_tracer_name` | Function | `tests/unit/observability/test_tracing.py` | 149 |
| `test_returns_hex_inside_span` | Function | `tests/unit/observability/test_tracing.py` | 166 |
| `test_consistent_within_span` | Function | `tests/unit/observability/test_tracing.py` | 176 |
| `test_records_error` | Function | `tests/unit/observability/test_tracing.py` | 195 |
| `test_records_exception_event` | Function | `tests/unit/observability/test_tracing.py` | 207 |
| `test_pipeline_creates_parent_and_child_spans` | Function | `tests/unit/observability/test_tracing.py` | 226 |
| `test_pipeline_span_attributes` | Function | `tests/unit/observability/test_tracing.py` | 258 |
| `test_all_stages_share_trace_id` | Function | `tests/unit/observability/test_tracing.py` | 279 |
| `test_json_processor_added_when_log_format_json` | Function | `tests/unit/observability/test_s15_ac_compliance.py` | 69 |
| `test_privacy_filter_in_processor_chain` | Function | `tests/unit/observability/test_s15_ac_compliance.py` | 79 |
| `test_merge_contextvars_in_chain` | Function | `tests/unit/observability/test_s15_ac_compliance.py` | 86 |
| `test_log_level_configurable` | Function | `tests/unit/observability/test_s15_ac_compliance.py` | 94 |
| `setup_method` | Function | `tests/unit/observability/test_s15_ac_compliance.py` | 124 |
| `test_no_host_leaves_client_none` | Function | `tests/unit/observability/test_s15_ac_compliance.py` | 302 |
| `test_init_with_host_instantiates_client` | Function | `tests/unit/observability/test_s15_ac_compliance.py` | 315 |
| `test_http_requests_total_registered` | Function | `tests/unit/observability/test_s15_ac_compliance.py` | 231 |
| `test_turn_total_registered` | Function | `tests/unit/observability/test_s15_ac_compliance.py` | 236 |
| `test_turn_processing_duration_histogram_registered` | Function | `tests/unit/observability/test_s15_ac_compliance.py` | 241 |
| `test_session_duration_histogram_registered` | Function | `tests/unit/observability/test_s15_ac_compliance.py` | 246 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Wrapper → _sanitize_input` | intra_community | 3 |
| `Start_pool_metrics_sampler → _sample_once` | intra_community | 3 |

## How to Explore

1. `gitnexus_context({name: "test_shutdown_with_provider"})` — see callers and callees
2. `gitnexus_query({query: "observability"})` — find related execution flows
3. Read key files listed above for implementation details
