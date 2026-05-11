---
name: genesis
description: "Skill for the Genesis area of fictional-barnacle. 93 symbols across 7 files."
---

# Genesis

93 symbols | 7 files | Cohesion: 89%

## When to Use

- Working with code in `tests/`
- Understanding how test_phase_does_not_advance_before_min_interactions, test_phase_advances_after_min_interactions, test_harmful_content_does_not_advance_phase work
- Modifying genesis-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/genesis/test_s02_ac_compliance.py` | _valid_enrichment_json, _template_with_start_loc, test_ac_2_6_session_variance_different_prompts, test_ac_2_6_no_variance_without_session_id, test_ac_2_8_single_word_defining_detail_expanded (+19) |
| `src/tta/genesis/genesis_v2.py` | to_dict, from_dict, _is_harmful, start, advance (+14) |
| `tests/unit/genesis/test_genesis_v2.py` | _make_llm, _make_pg, test_phase_does_not_advance_before_min_interactions, test_phase_advances_after_min_interactions, test_harmful_content_does_not_advance_phase (+13) |
| `tests/unit/genesis/test_genesis_npc_seeding.py` | _tiered_template, test_key_npc_has_tier_and_traits, test_background_npc_omits_empty_fields, test_supporting_npc_includes_goals, test_key_npc_gets_rich_defaults (+8) |
| `tests/unit/genesis/test_genesis_lite.py` | _make_test_template, _make_enrichment_json, _make_world_seed, test_happy_path_completes, test_enrichment_fallback_on_bad_json (+6) |
| `src/tta/genesis/genesis_lite.py` | run_genesis_lite, _extract_genesis_elements, _enriched_location_info, enrich_template, _build_template_summary (+2) |
| `src/tta/world/service.py` | create_world_graph |

## Entry Points

Start here when exploring this area:

- **`test_phase_does_not_advance_before_min_interactions`** (Function) — `tests/unit/genesis/test_genesis_v2.py:63`
- **`test_phase_advances_after_min_interactions`** (Function) — `tests/unit/genesis/test_genesis_v2.py:82`
- **`test_harmful_content_does_not_advance_phase`** (Function) — `tests/unit/genesis/test_genesis_v2.py:120`
- **`test_genesis_state_round_trips`** (Function) — `tests/unit/genesis/test_genesis_v2.py:146`
- **`test_state_is_saved_on_advance`** (Function) — `tests/unit/genesis/test_genesis_v2.py:164`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_phase_does_not_advance_before_min_interactions` | Function | `tests/unit/genesis/test_genesis_v2.py` | 63 |
| `test_phase_advances_after_min_interactions` | Function | `tests/unit/genesis/test_genesis_v2.py` | 82 |
| `test_harmful_content_does_not_advance_phase` | Function | `tests/unit/genesis/test_genesis_v2.py` | 120 |
| `test_genesis_state_round_trips` | Function | `tests/unit/genesis/test_genesis_v2.py` | 146 |
| `test_state_is_saved_on_advance` | Function | `tests/unit/genesis/test_genesis_v2.py` | 164 |
| `capture_save` | Function | `tests/unit/genesis/test_genesis_v2.py` | 168 |
| `test_start_emits_structlog_event` | Function | `tests/unit/genesis/test_genesis_v2.py` | 193 |
| `test_building_world_extracts_composition` | Function | `tests/unit/genesis/test_genesis_v2.py` | 214 |
| `test_building_character_infers_traits` | Function | `tests/unit/genesis/test_genesis_v2.py` | 251 |
| `test_first_light_sets_narrator_form` | Function | `tests/unit/genesis/test_genesis_v2.py` | 275 |
| `test_becoming_captures_character_name` | Function | `tests/unit/genesis/test_genesis_v2.py` | 301 |
| `test_threshold_sets_first_turn_seed` | Function | `tests/unit/genesis/test_genesis_v2.py` | 325 |
| `test_threshold_marks_completed` | Function | `tests/unit/genesis/test_genesis_v2.py` | 353 |
| `test_advance_on_completed_state_returns_gracefully` | Function | `tests/unit/genesis/test_genesis_v2.py` | 380 |
| `test_slip_phase_captures_slip_event` | Function | `tests/unit/genesis/test_genesis_v2.py` | 432 |
| `test_interactions_list_accumulates` | Function | `tests/unit/genesis/test_genesis_v2.py` | 456 |
| `to_dict` | Function | `src/tta/genesis/genesis_v2.py` | 134 |
| `from_dict` | Function | `src/tta/genesis/genesis_v2.py` | 153 |
| `start` | Function | `src/tta/genesis/genesis_v2.py` | 209 |
| `advance` | Function | `src/tta/genesis/genesis_v2.py` | 233 |

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
| `Advance → To_dict` | intra_community | 3 |
| `Advance → _phase_void` | cross_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| World | 7 calls |
| Choices | 3 calls |

## How to Explore

1. `gitnexus_context({name: "test_phase_does_not_advance_before_min_interactions"})` — see callers and callees
2. `gitnexus_query({query: "genesis"})` — find related execution flows
3. Read key files listed above for implementation details
