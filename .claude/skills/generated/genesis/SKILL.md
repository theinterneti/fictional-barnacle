---
name: genesis
description: "Skill for the Genesis area of fictional-barnacle. 93 symbols across 7 files."
---

# Genesis

93 symbols | 7 files | Cohesion: 74%

## When to Use

- Working with code in `tests/`
- Understanding how test_happy_path_completes, test_enrichment_fallback_on_bad_json, test_starting_location_detected work
- Modifying genesis-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/genesis/test_s02_ac_compliance.py` | _valid_enrichment_json, _template_with_start_loc, test_ac_2_6_session_variance_different_prompts, test_ac_2_6_no_variance_without_session_id, test_ac_2_8_single_word_defining_detail_expanded (+19) |
| `src/tta/genesis/genesis_v2.py` | _process_phase, _phase_void, _phase_building_world, _phase_slip, _phase_building_character (+14) |
| `tests/unit/genesis/test_genesis_v2.py` | test_harmful_content_does_not_advance_phase, test_building_character_infers_traits, test_threshold_sets_first_turn_seed, test_genesis_state_round_trips, capture_save (+13) |
| `tests/unit/genesis/test_genesis_npc_seeding.py` | _tiered_template, test_key_npc_has_tier_and_traits, test_background_npc_omits_empty_fields, test_supporting_npc_includes_goals, test_key_npc_gets_rich_defaults (+8) |
| `tests/unit/genesis/test_genesis_lite.py` | _make_test_template, _make_enrichment_json, _make_world_seed, test_happy_path_completes, test_enrichment_fallback_on_bad_json (+6) |
| `src/tta/genesis/genesis_lite.py` | run_genesis_lite, _extract_genesis_elements, _enriched_location_info, enrich_template, _build_template_summary (+2) |
| `src/tta/world/service.py` | create_world_graph |

## Entry Points

Start here when exploring this area:

- **`test_happy_path_completes`** (Function) — `tests/unit/genesis/test_genesis_lite.py:207`
- **`test_enrichment_fallback_on_bad_json`** (Function) — `tests/unit/genesis/test_genesis_lite.py:240`
- **`test_starting_location_detected`** (Function) — `tests/unit/genesis/test_genesis_lite.py:272`
- **`test_narrative_intro_uses_generation_role`** (Function) — `tests/unit/genesis/test_genesis_lite.py:302`
- **`test_world_service_called_with_session`** (Function) — `tests/unit/genesis/test_genesis_lite.py:329`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_happy_path_completes` | Function | `tests/unit/genesis/test_genesis_lite.py` | 207 |
| `test_enrichment_fallback_on_bad_json` | Function | `tests/unit/genesis/test_genesis_lite.py` | 240 |
| `test_starting_location_detected` | Function | `tests/unit/genesis/test_genesis_lite.py` | 272 |
| `test_narrative_intro_uses_generation_role` | Function | `tests/unit/genesis/test_genesis_lite.py` | 302 |
| `test_world_service_called_with_session` | Function | `tests/unit/genesis/test_genesis_lite.py` | 329 |
| `test_valid_json_parsed` | Function | `tests/unit/genesis/test_genesis_lite.py` | 369 |
| `test_fallback_on_invalid_json` | Function | `tests/unit/genesis/test_genesis_lite.py` | 391 |
| `test_uses_archetypes_as_names` | Function | `tests/unit/genesis/test_genesis_lite.py` | 419 |
| `test_ac_2_6_session_variance_different_prompts` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 253 |
| `test_ac_2_6_no_variance_without_session_id` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 280 |
| `test_ac_2_8_single_word_defining_detail_expanded` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 384 |
| `test_ac_2_8_two_word_defining_detail_expanded` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 399 |
| `test_ac_2_8_long_defining_detail_not_expanded` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 413 |
| `test_ac_2_8_missing_fields_get_defaults` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 430 |
| `test_ac_2_9_character_concept_in_prompt` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 452 |
| `test_ac_2_9_different_concepts_produce_different_prompts` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 466 |
| `generate` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 118 |
| `stream` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 126 |
| `generate` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 306 |
| `stream` | Function | `tests/unit/genesis/test_s02_ac_compliance.py` | 317 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Advance → _extract_composition` | cross_community | 4 |
| `Advance → _infer_traits` | cross_community | 4 |
| `Run_genesis_lite → _build_template_summary` | cross_community | 3 |
| `Run_genesis_lite → _parse_enrichment` | cross_community | 3 |
| `Run_genesis_lite → _default_enrichment` | cross_community | 3 |
| `Run_genesis_lite → Generate` | cross_community | 3 |
| `Start → To_dict` | intra_community | 3 |
| `Advance → From_dict` | intra_community | 3 |
| `Advance → To_dict` | cross_community | 3 |
| `Advance → _phase_void` | cross_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| World | 7 calls |
| Choices | 3 calls |

## How to Explore

1. `gitnexus_context({name: "test_happy_path_completes"})` — see callers and callees
2. `gitnexus_query({query: "genesis"})` — find related execution flows
3. Read key files listed above for implementation details
