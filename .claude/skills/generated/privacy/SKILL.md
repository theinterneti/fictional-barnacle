---
name: privacy
description: "Skill for the Privacy area of fictional-barnacle. 38 symbols across 7 files."
---

# Privacy

38 symbols | 7 files | Cohesion: 92%

## When to Use

- Working with code in `tests/`
- Understanding how run_purge, purge_loop, test_completed_session_retention_90_days work
- Modifying privacy-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/privacy/test_s17_ac_compliance.py` | _by_name, test_completed_session_retention_90_days, test_application_logs_retention_30_days, test_traces_retention_7_days, test_player_profile_retention_none (+9) |
| `tests/unit/privacy/test_gdpr_endpoints.py` | _configure_session_ids, test_redis_sessions_evicted, test_neo4j_worlds_cleaned, test_redis_failure_does_not_block_neo4j, test_no_sessions_skips_cleanup (+3) |
| `src/tta/privacy/purge.py` | _retention_days, _soft_delete_retention_days, _completed_retention_days, _collect_session_ids, _delete_sessions (+2) |
| `tests/unit/privacy/test_purge.py` | _make_factory, test_noop_when_no_sessions, test_dry_run_counts_without_deleting, test_real_purge_deletes_and_commits, test_cutoffs_use_correct_retention |
| `src/tta/privacy/cost.py` | estimate_cost, record |
| `tests/unit/test_context_and_cost.py` | test_record_accumulates |
| `tests/unit/llm/test_s07_ac_compliance.py` | test_session_cost_accumulates_across_calls |

## Entry Points

Start here when exploring this area:

- **`run_purge`** (Function) — `src/tta/privacy/purge.py:102`
- **`purge_loop`** (Function) — `src/tta/privacy/purge.py:176`
- **`test_completed_session_retention_90_days`** (Function) — `tests/unit/privacy/test_s17_ac_compliance.py:204`
- **`test_application_logs_retention_30_days`** (Function) — `tests/unit/privacy/test_s17_ac_compliance.py:210`
- **`test_traces_retention_7_days`** (Function) — `tests/unit/privacy/test_s17_ac_compliance.py:216`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `run_purge` | Function | `src/tta/privacy/purge.py` | 102 |
| `purge_loop` | Function | `src/tta/privacy/purge.py` | 176 |
| `test_completed_session_retention_90_days` | Function | `tests/unit/privacy/test_s17_ac_compliance.py` | 204 |
| `test_application_logs_retention_30_days` | Function | `tests/unit/privacy/test_s17_ac_compliance.py` | 210 |
| `test_traces_retention_7_days` | Function | `tests/unit/privacy/test_s17_ac_compliance.py` | 216 |
| `test_player_profile_retention_none` | Function | `tests/unit/privacy/test_s17_ac_compliance.py` | 222 |
| `test_retention_policy_immutable` | Function | `tests/unit/privacy/test_s17_ac_compliance.py` | 239 |
| `test_noop_when_no_sessions` | Function | `tests/unit/privacy/test_purge.py` | 126 |
| `test_dry_run_counts_without_deleting` | Function | `tests/unit/privacy/test_purge.py` | 140 |
| `test_real_purge_deletes_and_commits` | Function | `tests/unit/privacy/test_purge.py` | 161 |
| `test_cutoffs_use_correct_retention` | Function | `tests/unit/privacy/test_purge.py` | 190 |
| `test_redis_sessions_evicted` | Function | `tests/unit/privacy/test_gdpr_endpoints.py` | 215 |
| `test_neo4j_worlds_cleaned` | Function | `tests/unit/privacy/test_gdpr_endpoints.py` | 228 |
| `test_redis_failure_does_not_block_neo4j` | Function | `tests/unit/privacy/test_gdpr_endpoints.py` | 241 |
| `test_no_sessions_skips_cleanup` | Function | `tests/unit/privacy/test_gdpr_endpoints.py` | 268 |
| `test_record_accumulates` | Function | `tests/unit/test_context_and_cost.py` | 138 |
| `test_session_cost_accumulates_across_calls` | Function | `tests/unit/llm/test_s07_ac_compliance.py` | 446 |
| `estimate_cost` | Function | `src/tta/privacy/cost.py` | 139 |
| `record` | Function | `src/tta/privacy/cost.py` | 200 |
| `test_age_gate_accepts_confirmed` | Function | `tests/unit/privacy/test_s17_ac_compliance.py` | 336 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Purge_loop → _retention_days` | intra_community | 4 |
| `Purge_loop → _collect_session_ids` | intra_community | 3 |
| `Purge_loop → _delete_sessions` | intra_community | 3 |

## How to Explore

1. `gitnexus_context({name: "run_purge"})` — see callers and callees
2. `gitnexus_query({query: "privacy"})` — find related execution flows
3. Read key files listed above for implementation details
