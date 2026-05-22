---
name: eval
description: "Skill for the Eval area of fictional-barnacle. 41 symbols across 3 files."
---

# Eval

41 symbols | 3 files | Cohesion: 69%

## When to Use

- Working with code in `tests/`
- Understanding how run_llm_playtesters, evaluate_sessions, compute_batch_medians work
- Modifying eval-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/eval/test_s45_ac_compliance.py` | _make_pipeline, test_emit_verdict_exit_2_when_error_rate_exceeds_25_pct, test_emit_verdict_exit_2_at_exactly_26_pct, test_emit_verdict_no_abort_at_25_pct_exactly, test_emit_verdict_exit_1_on_regression (+20) |
| `src/tta/eval/pipeline.py` | run_llm_playtesters, _run_via_arq, evaluate_sessions, compute_batch_medians, load_baseline (+8) |
| `src/tta/eval/__main__.py` | _build_parser, _main, main |

## Entry Points

Start here when exploring this area:

- **`run_llm_playtesters`** (Function) — `src/tta/eval/pipeline.py:75`
- **`evaluate_sessions`** (Function) — `src/tta/eval/pipeline.py:248`
- **`compute_batch_medians`** (Function) — `src/tta/eval/pipeline.py:292`
- **`load_baseline`** (Function) — `src/tta/eval/pipeline.py:312`
- **`write_outputs`** (Function) — `src/tta/eval/pipeline.py:410`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `run_llm_playtesters` | Function | `src/tta/eval/pipeline.py` | 75 |
| `evaluate_sessions` | Function | `src/tta/eval/pipeline.py` | 248 |
| `compute_batch_medians` | Function | `src/tta/eval/pipeline.py` | 292 |
| `load_baseline` | Function | `src/tta/eval/pipeline.py` | 312 |
| `write_outputs` | Function | `src/tta/eval/pipeline.py` | 410 |
| `run` | Function | `src/tta/eval/pipeline.py` | 447 |
| `main` | Function | `src/tta/eval/__main__.py` | 78 |
| `test_emit_verdict_exit_2_when_error_rate_exceeds_25_pct` | Function | `tests/unit/eval/test_s45_ac_compliance.py` | 279 |
| `test_emit_verdict_exit_2_at_exactly_26_pct` | Function | `tests/unit/eval/test_s45_ac_compliance.py` | 292 |
| `test_emit_verdict_no_abort_at_25_pct_exactly` | Function | `tests/unit/eval/test_s45_ac_compliance.py` | 305 |
| `test_emit_verdict_exit_1_on_regression` | Function | `tests/unit/eval/test_s45_ac_compliance.py` | 318 |
| `test_emit_verdict_exit_1_on_fail_verdict` | Function | `tests/unit/eval/test_s45_ac_compliance.py` | 332 |
| `test_emit_verdict_exit_0_on_pass` | Function | `tests/unit/eval/test_s45_ac_compliance.py` | 345 |
| `emit_verdict` | Function | `src/tta/eval/pipeline.py` | 387 |
| `test_load_human_feedback_loads_granted_records` | Function | `tests/unit/eval/test_s45_ac_compliance.py` | 362 |
| `test_load_human_feedback_skips_not_granted` | Function | `tests/unit/eval/test_s45_ac_compliance.py` | 373 |
| `test_load_human_feedback_skips_withdrawn` | Function | `tests/unit/eval/test_s45_ac_compliance.py` | 383 |
| `test_load_human_feedback_empty_dir_returns_empty` | Function | `tests/unit/eval/test_s45_ac_compliance.py` | 393 |
| `test_load_human_feedback_none_dir_returns_empty` | Function | `tests/unit/eval/test_s45_ac_compliance.py` | 399 |
| `load_human_feedback` | Function | `src/tta/eval/pipeline.py` | 216 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → _submit_and_poll` | cross_community | 8 |
| `Main → _build_report` | cross_community | 8 |
| `Run → _verbosity_description` | cross_community | 7 |
| `Run → _boldness_description` | cross_community | 7 |
| `Main → _submit_and_poll` | cross_community | 7 |
| `Main → _build_report` | cross_community | 7 |
| `Main → _blank_commentary` | cross_community | 7 |
| `Main → _count_contradictions` | cross_community | 7 |
| `Main → _check_first_turn_character` | cross_community | 7 |
| `Main → _blank_commentary` | cross_community | 6 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Playtest | 1 calls |
| Quality | 1 calls |

## How to Explore

1. `gitnexus_context({name: "run_llm_playtesters"})` — see callers and callees
2. `gitnexus_query({query: "eval"})` — find related execution flows
3. Read key files listed above for implementation details
