---
name: resilience
description: "Skill for the Resilience area of fictional-barnacle. 62 symbols across 7 files."
---

# Resilience

62 symbols | 7 files | Cohesion: 93%

## When to Use

- Working with code in `tests/`
- Understanding how test_no_cooldown_initially, test_violation_below_threshold_no_cooldown, test_cooldown_blocks_identity work
- Modifying resilience-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/resilience/test_retry.py` | test_raises_app_error_after_exhaustion, always_fails, test_exhaustion_preserves_cause, test_db_retry_raises_app_error_after_exhaustion, test_redis_retry_raises_app_error_after_exhaustion (+22) |
| `tests/unit/resilience/test_anti_abuse.py` | test_no_cooldown_initially, test_violation_below_threshold_no_cooldown, test_cooldown_blocks_identity, test_different_identities_independent, test_different_patterns_independent (+5) |
| `src/tta/resilience/circuit_breaker.py` | __aenter__, __aexit__, _record_failure, _window_failures, _cooldown_elapsed (+4) |
| `tests/unit/resilience/test_rate_limiter.py` | test_allows_under_limit, test_rejects_over_limit, test_rejected_not_counted, test_window_expiry, test_separate_keys_independent (+3) |
| `src/tta/resilience/anti_abuse.py` | check_cooldown, _calculate_cooldown, record_violation, record_violation |
| `src/tta/resilience/rate_limiter.py` | check, check |
| `src/tta/resilience/retry.py` | decorator, _make_retry_filter |

## Entry Points

Start here when exploring this area:

- **`test_no_cooldown_initially`** (Function) — `tests/unit/resilience/test_anti_abuse.py:73`
- **`test_violation_below_threshold_no_cooldown`** (Function) — `tests/unit/resilience/test_anti_abuse.py:79`
- **`test_cooldown_blocks_identity`** (Function) — `tests/unit/resilience/test_anti_abuse.py:109`
- **`test_different_identities_independent`** (Function) — `tests/unit/resilience/test_anti_abuse.py:155`
- **`test_different_patterns_independent`** (Function) — `tests/unit/resilience/test_anti_abuse.py:171`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_no_cooldown_initially` | Function | `tests/unit/resilience/test_anti_abuse.py` | 73 |
| `test_violation_below_threshold_no_cooldown` | Function | `tests/unit/resilience/test_anti_abuse.py` | 79 |
| `test_cooldown_blocks_identity` | Function | `tests/unit/resilience/test_anti_abuse.py` | 109 |
| `test_different_identities_independent` | Function | `tests/unit/resilience/test_anti_abuse.py` | 155 |
| `test_different_patterns_independent` | Function | `tests/unit/resilience/test_anti_abuse.py` | 171 |
| `test_expired_cooldown_clears` | Function | `tests/unit/resilience/test_anti_abuse.py` | 190 |
| `check_cooldown` | Function | `src/tta/resilience/anti_abuse.py` | 164 |
| `test_rapid_fire_triggers_above_threshold` | Function | `tests/unit/resilience/test_anti_abuse.py` | 95 |
| `test_escalation_doubles_cooldown` | Function | `tests/unit/resilience/test_anti_abuse.py` | 122 |
| `test_credential_stuffing_threshold` | Function | `tests/unit/resilience/test_anti_abuse.py` | 137 |
| `test_max_cooldown_cap` | Function | `tests/unit/resilience/test_anti_abuse.py` | 219 |
| `record_violation` | Function | `src/tta/resilience/anti_abuse.py` | 183 |
| `record_violation` | Function | `src/tta/resilience/anti_abuse.py` | 276 |
| `test_allows_under_limit` | Function | `tests/unit/resilience/test_rate_limiter.py` | 42 |
| `test_rejects_over_limit` | Function | `tests/unit/resilience/test_rate_limiter.py` | 50 |
| `test_rejected_not_counted` | Function | `tests/unit/resilience/test_rate_limiter.py` | 61 |
| `test_window_expiry` | Function | `tests/unit/resilience/test_rate_limiter.py` | 75 |
| `test_separate_keys_independent` | Function | `tests/unit/resilience/test_rate_limiter.py` | 89 |
| `check` | Function | `src/tta/resilience/rate_limiter.py` | 78 |
| `test_raises_app_error_after_exhaustion` | Function | `tests/unit/resilience/test_retry.py` | 103 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `__aexit__ → _transition` | intra_community | 3 |

## How to Explore

1. `gitnexus_context({name: "test_no_cooldown_initially"})` — see callers and callees
2. `gitnexus_query({query: "resilience"})` — find related execution flows
3. Read key files listed above for implementation details
