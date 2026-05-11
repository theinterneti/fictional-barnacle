---
name: pipeline
description: "Skill for the Pipeline area of fictional-barnacle. 233 symbols across 19 files."
---

# Pipeline

233 symbols | 19 files | Cohesion: 73%

## When to Use

- Working with code in `tests/`
- Understanding how test_examine_prompt_includes_exploration_hook, test_move_prompt_includes_exploration_hook, test_non_explore_intents_do_not_get_hook work
- Modifying pipeline-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/pipeline/test_generate.py` | _make_state, test_generate_sets_narrative_output, test_generate_sets_model_used, test_generate_sets_generation_prompt, test_generate_calls_extraction_after_generation (+19) |
| `tests/unit/pipeline/test_s03_ac_compliance.py` | _make_state, test_examine_prompt_includes_exploration_hook, test_move_prompt_includes_exploration_hook, test_non_explore_intents_do_not_get_hook, test_failure_narrated_as_meaningful_beat (+18) |
| `tests/unit/pipeline/test_context.py` | _make_state, _make_deps, test_context_includes_game_state, test_context_includes_intent, test_context_intent_defaults_to_unknown (+18) |
| `tests/unit/pipeline/test_s08_ac_compliance.py` | _make_state, test_all_pipeline_stages_execute, test_known_intent_classified, test_meta_command_flagged_and_does_not_enter_narrative_pipeline, test_context_assembled_includes_game_state (+15) |
| `tests/unit/pipeline/test_generate_narrative.py` | _make_state, test_word_range_injected_per_intent, test_unknown_intent_uses_default_range, test_tone_present_in_prompt, test_genre_present_in_prompt (+13) |
| `tests/unit/pipeline/test_s05_choice_consequence.py` | _make_state, test_permanent_signal_injected, test_non_permanent_omits_signal, test_missing_classification_safe, test_divergence_guidance_in_prompt (+11) |
| `tests/unit/pipeline/test_first_turn.py` | _build_deps, _fresh_state, test_pipeline_completes_successfully, test_pipeline_produces_narrative, test_pipeline_classifies_intent (+10) |
| `tests/unit/pipeline/test_understand.py` | _make_state, test_regex_classification, test_meta_takes_priority_over_move_for_quit, test_llm_fallback_unknown_intent_becomes_other, test_safety_blocks_input (+9) |
| `tests/unit/pipeline/test_orchestrator.py` | _make_state, _safe_result, _make_deps, test_full_pipeline_happy_path, test_pipeline_preserves_session_id (+6) |
| `tests/unit/pipeline/test_moderation_flow.py` | _make_state, _safe, _block_with_redirect, _block_without_redirect, _make_deps (+6) |

## Entry Points

Start here when exploring this area:

- **`test_examine_prompt_includes_exploration_hook`** (Function) — `tests/unit/pipeline/test_s03_ac_compliance.py:108`
- **`test_move_prompt_includes_exploration_hook`** (Function) — `tests/unit/pipeline/test_s03_ac_compliance.py:121`
- **`test_non_explore_intents_do_not_get_hook`** (Function) — `tests/unit/pipeline/test_s03_ac_compliance.py:133`
- **`test_failure_narrated_as_meaningful_beat`** (Function) — `tests/unit/pipeline/test_s03_ac_compliance.py:144`
- **`test_session_summary_injects_prior_visit_knowledge`** (Function) — `tests/unit/pipeline/test_s03_ac_compliance.py:179`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_examine_prompt_includes_exploration_hook` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 108 |
| `test_move_prompt_includes_exploration_hook` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 121 |
| `test_non_explore_intents_do_not_get_hook` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 133 |
| `test_failure_narrated_as_meaningful_beat` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 144 |
| `test_session_summary_injects_prior_visit_knowledge` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 179 |
| `test_no_summary_means_no_prior_visit_signal` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 192 |
| `test_summary_reaches_generation_prompt` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 200 |
| `test_fantasy_tone_and_genre_both_injected_together` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 230 |
| `test_fantasy_genre_surfaces_in_generation_prompt` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 252 |
| `test_no_world_seed_no_style_section` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 272 |
| `test_examine_prompt_includes_two_hook_detail` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 449 |
| `test_deliver_marks_complete_when_narrative_present` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 486 |
| `test_deliver_fails_when_narrative_absent` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 500 |
| `test_deliver_does_not_mutate_narrative` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 512 |
| `test_inject_tone_is_deterministic` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 535 |
| `test_inject_summary_is_deterministic` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 545 |
| `test_inject_genesis_elements_is_deterministic` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 553 |
| `test_build_generation_prompt_is_deterministic` | Function | `tests/unit/pipeline/test_s03_ac_compliance.py` | 570 |
| `test_pipeline_completes_successfully` | Function | `tests/unit/pipeline/test_first_turn.py` | 59 |
| `test_pipeline_produces_narrative` | Function | `tests/unit/pipeline/test_first_turn.py` | 67 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Choices | 11 calls |
| World | 1 calls |

## How to Explore

1. `gitnexus_context({name: "test_examine_prompt_includes_exploration_hook"})` — see callers and callees
2. `gitnexus_query({query: "pipeline"})` — find related execution flows
3. Read key files listed above for implementation details
