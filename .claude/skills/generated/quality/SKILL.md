---
name: quality
description: "Skill for the Quality area of fictional-barnacle. 37 symbols across 5 files."
---

# Quality

37 symbols | 5 files | Cohesion: 65%

## When to Use

- Working with code in `tests/`
- Understanding how test_verdict_inconclusive_when_three_or_more_not_evaluated, test_verdict_inconclusive_fail_reasons_empty, is_evaluated work
- Modifying quality-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/quality/test_s44_ac_compliance.py` | test_verdict_inconclusive_when_three_or_more_not_evaluated, test_verdict_inconclusive_fail_reasons_empty, test_qc03_not_evaluated_when_no_feedback, test_qc04_auto_zero_when_character_name_absent_from_first_turn, test_qc04_notes_mention_enforcement_miss (+11) |
| `src/tta/quality/evaluator.py` | evaluate, _score_qc01, _score_qc02, _score_qc03, _score_qc04 (+8) |
| `src/tta/quality/feedback.py` | _normalize, wonder_normalized, consequence_normalized, character_normalized |
| `tests/unit/quality/conftest.py` | make_report, full_report, make_turn |
| `src/tta/quality/models.py` | is_evaluated |

## Entry Points

Start here when exploring this area:

- **`test_verdict_inconclusive_when_three_or_more_not_evaluated`** (Function) — `tests/unit/quality/test_s44_ac_compliance.py:246`
- **`test_verdict_inconclusive_fail_reasons_empty`** (Function) — `tests/unit/quality/test_s44_ac_compliance.py:297`
- **`is_evaluated`** (Function) — `src/tta/quality/models.py:54`
- **`evaluate`** (Function) — `src/tta/quality/evaluator.py:68`
- **`test_qc03_not_evaluated_when_no_feedback`** (Function) — `tests/unit/quality/test_s44_ac_compliance.py:114`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_verdict_inconclusive_when_three_or_more_not_evaluated` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 246 |
| `test_verdict_inconclusive_fail_reasons_empty` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 297 |
| `is_evaluated` | Function | `src/tta/quality/models.py` | 54 |
| `evaluate` | Function | `src/tta/quality/evaluator.py` | 68 |
| `test_qc03_not_evaluated_when_no_feedback` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 114 |
| `test_qc04_auto_zero_when_character_name_absent_from_first_turn` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 165 |
| `test_qc04_notes_mention_enforcement_miss` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 189 |
| `test_verdict_fail_populates_fail_reasons` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 228 |
| `test_qc05_not_evaluated_when_no_llm` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 363 |
| `test_report_id_is_unique` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 417 |
| `test_composite_score_within_range` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 427 |
| `make_report` | Function | `tests/unit/quality/conftest.py` | 39 |
| `full_report` | Function | `tests/unit/quality/conftest.py` | 68 |
| `test_all_categories_scored_when_full_data_present` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 65 |
| `test_qc03_not_evaluated_weight_redistributed` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 128 |
| `test_verdict_fail_when_individual_category_below_threshold` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 208 |
| `test_verdict_pass_when_all_above_thresholds` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 338 |
| `test_qc05_uses_temperature_zero` | Function | `tests/unit/quality/test_s44_ac_compliance.py` | 375 |
| `make_turn` | Function | `tests/unit/quality/conftest.py` | 10 |
| `wonder_normalized` | Function | `src/tta/quality/feedback.py` | 36 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → _count_contradictions` | cross_community | 7 |
| `Main → _check_first_turn_character` | cross_community | 7 |
| `Main → _count_contradictions` | cross_community | 6 |
| `Main → _check_first_turn_character` | cross_community | 6 |
| `Main → _score_qc02` | cross_community | 6 |
| `Main → _score_qc03` | cross_community | 6 |
| `Main → _count_contradictions` | cross_community | 5 |
| `Main → _check_first_turn_character` | cross_community | 5 |
| `Main → _score_qc02` | cross_community | 5 |
| `Main → _score_qc03` | cross_community | 5 |

## How to Explore

1. `gitnexus_context({name: "test_verdict_inconclusive_when_three_or_more_not_evaluated"})` — see callers and callees
2. `gitnexus_query({query: "quality"})` — find related execution flows
3. Read key files listed above for implementation details
