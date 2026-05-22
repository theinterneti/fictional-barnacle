---
name: prompts
description: "Skill for the Prompts area of fictional-barnacle. 117 symbols across 7 files."
---

# Prompts

117 symbols | 7 files | Cohesion: 73%

## When to Use

- Working with code in `tests/`
- Understanding how test_required_variable_injected, test_optional_variable_injected_when_provided, test_optional_variable_absent_does_not_error work
- Modifying prompts-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/prompts/test_s09_ac_compliance.py` | test_required_variable_injected, test_optional_variable_injected_when_provided, test_optional_variable_absent_does_not_error, test_missing_required_variable_raises_value_error, test_rendered_result_carries_template_id_and_version (+25) |
| `tests/unit/prompts/test_prompt_loader.py` | test_render_unknown_template_raises, test_render_narrative_generate, test_render_classification_intent, test_render_extraction_world_changes, test_get_unknown_template_raises (+21) |
| `tests/unit/prompts/test_golden_snapshots.py` | test_renders_without_variables, test_contains_core_instructions, test_tone_variable_renders, test_word_range_overridable, test_prompt_hash_stable (+14) |
| `src/tta/prompts/loader.py` | _estimate_tokens, render, get, _detect_circular_refs, _dfs (+12) |
| `tests/unit/prompts/test_langfuse_bridge.py` | test_refresh_raises_when_langfuse_disabled, test_preview_renders_with_label, test_render_fetches_when_not_cached, test_seed_creates_new_prompts, test_seed_skips_when_hash_matches (+5) |
| `src/tta/prompts/langfuse_bridge.py` | _to_langfuse_name, _seed_one, refresh, render, preview (+4) |
| `tests/unit/prompts/test_guardrails.py` | test_generation_role_gets_preamble, test_classification_role_gets_preamble, test_extraction_role_no_preamble, test_current_templates_have_no_cycles, test_validate_passes_with_all_templates (+1) |

## Entry Points

Start here when exploring this area:

- **`test_required_variable_injected`** (Function) — `tests/unit/prompts/test_s09_ac_compliance.py:158`
- **`test_optional_variable_injected_when_provided`** (Function) — `tests/unit/prompts/test_s09_ac_compliance.py:162`
- **`test_optional_variable_absent_does_not_error`** (Function) — `tests/unit/prompts/test_s09_ac_compliance.py:170`
- **`test_missing_required_variable_raises_value_error`** (Function) — `tests/unit/prompts/test_s09_ac_compliance.py:177`
- **`test_rendered_result_carries_template_id_and_version`** (Function) — `tests/unit/prompts/test_s09_ac_compliance.py:184`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_required_variable_injected` | Function | `tests/unit/prompts/test_s09_ac_compliance.py` | 158 |
| `test_optional_variable_injected_when_provided` | Function | `tests/unit/prompts/test_s09_ac_compliance.py` | 162 |
| `test_optional_variable_absent_does_not_error` | Function | `tests/unit/prompts/test_s09_ac_compliance.py` | 170 |
| `test_missing_required_variable_raises_value_error` | Function | `tests/unit/prompts/test_s09_ac_compliance.py` | 177 |
| `test_rendered_result_carries_template_id_and_version` | Function | `tests/unit/prompts/test_s09_ac_compliance.py` | 184 |
| `test_fragment_version_tracked_in_rendered_result` | Function | `tests/unit/prompts/test_s09_ac_compliance.py` | 263 |
| `test_rendered_hash_is_stable_across_calls` | Function | `tests/unit/prompts/test_s09_ac_compliance.py` | 315 |
| `test_hash_changes_when_variables_change` | Function | `tests/unit/prompts/test_s09_ac_compliance.py` | 323 |
| `test_template_version_present_in_result` | Function | `tests/unit/prompts/test_s09_ac_compliance.py` | 331 |
| `test_narrative_generate_core_instructions_stable` | Function | `tests/unit/prompts/test_s09_ac_compliance.py` | 347 |
| `test_classification_intent_categories_stable` | Function | `tests/unit/prompts/test_s09_ac_compliance.py` | 356 |
| `test_render_unknown_template_raises` | Function | `tests/unit/prompts/test_prompt_loader.py` | 260 |
| `test_render_narrative_generate` | Function | `tests/unit/prompts/test_prompt_loader.py` | 414 |
| `test_render_classification_intent` | Function | `tests/unit/prompts/test_prompt_loader.py` | 422 |
| `test_render_extraction_world_changes` | Function | `tests/unit/prompts/test_prompt_loader.py` | 430 |
| `test_renders_without_variables` | Function | `tests/unit/prompts/test_golden_snapshots.py` | 30 |
| `test_contains_core_instructions` | Function | `tests/unit/prompts/test_golden_snapshots.py` | 35 |
| `test_tone_variable_renders` | Function | `tests/unit/prompts/test_golden_snapshots.py` | 42 |
| `test_word_range_overridable` | Function | `tests/unit/prompts/test_golden_snapshots.py` | 46 |
| `test_prompt_hash_stable` | Function | `tests/unit/prompts/test_golden_snapshots.py` | 60 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Preview → _to_langfuse_name` | intra_community | 4 |
| `Preview → _sha256` | intra_community | 4 |
| `__init__ → _parse_front_matter` | intra_community | 4 |
| `__init__ → _path_to_template_id` | intra_community | 4 |
| `__init__ → Get` | cross_community | 4 |
| `__init__ → _hash_prompt` | intra_community | 3 |
| `__init__ → _extract_includes` | cross_community | 3 |

## How to Explore

1. `gitnexus_context({name: "test_required_variable_injected"})` — see callers and callees
2. `gitnexus_query({query: "prompts"})` — find related execution flows
3. Read key files listed above for implementation details
