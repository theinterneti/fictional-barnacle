---
name: choices
description: "Skill for the Choices area of fictional-barnacle. 68 symbols across 9 files."
---

# Choices

68 symbols | 9 files | Cohesion: 67%

## When to Use

- Working with code in `tests/`
- Understanding how test_last_active_turn_only_on_activation, test_short_term_entry_inactive_at_creation_turn, test_short_term_entry_activates_within_window work
- Modifying choices-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/choices/test_consequence_service.py` | test_create_returns_chain, test_create_with_entries, test_create_with_parent_chain, test_immediate_entry_activates, test_short_term_waits_one_turn (+21) |
| `tests/unit/choices/test_s05_ac_compliance.py` | test_short_term_entry_inactive_at_creation_turn, test_short_term_entry_activates_within_window, test_long_term_entry_manifests_after_ten_turns, test_permanent_reversibility_stored_correctly, test_permanent_chain_distinguishable_from_trivial_chain (+12) |
| `src/tta/choices/consequence_service.py` | create_chain, evaluate, get_foreshadowing_hints, reveal_hidden_entry, clear (+6) |
| `tests/unit/choices/test_consequence_performance.py` | _populate_service, test_evaluate_30_chains_under_300ms, test_prune_chains_under_100ms, test_calculate_divergence_under_100ms |
| `tests/unit/choices/test_classifier.py` | _llm_response, test_successful_llm_classification, test_llm_invalid_types_falls_back, test_llm_partial_valid_types |
| `tests/unit/pipeline/test_s05_choice_consequence.py` | test_last_active_turn_only_on_activation, test_divergence_guidance_injected_when_high |
| `src/tta/choices/classifier.py` | classify_choice, classify_choice_with_llm |
| `src/tta/llm/client.py` | generate |
| `src/tta/genesis/genesis_lite.py` | _generate_intro |

## Entry Points

Start here when exploring this area:

- **`test_last_active_turn_only_on_activation`** (Function) — `tests/unit/pipeline/test_s05_choice_consequence.py:189`
- **`test_short_term_entry_inactive_at_creation_turn`** (Function) — `tests/unit/choices/test_s05_ac_compliance.py:45`
- **`test_short_term_entry_activates_within_window`** (Function) — `tests/unit/choices/test_s05_ac_compliance.py:65`
- **`test_long_term_entry_manifests_after_ten_turns`** (Function) — `tests/unit/choices/test_s05_ac_compliance.py:86`
- **`test_permanent_reversibility_stored_correctly`** (Function) — `tests/unit/choices/test_s05_ac_compliance.py:225`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_last_active_turn_only_on_activation` | Function | `tests/unit/pipeline/test_s05_choice_consequence.py` | 189 |
| `test_short_term_entry_inactive_at_creation_turn` | Function | `tests/unit/choices/test_s05_ac_compliance.py` | 45 |
| `test_short_term_entry_activates_within_window` | Function | `tests/unit/choices/test_s05_ac_compliance.py` | 65 |
| `test_long_term_entry_manifests_after_ten_turns` | Function | `tests/unit/choices/test_s05_ac_compliance.py` | 86 |
| `test_permanent_reversibility_stored_correctly` | Function | `tests/unit/choices/test_s05_ac_compliance.py` | 225 |
| `test_permanent_chain_distinguishable_from_trivial_chain` | Function | `tests/unit/choices/test_s05_ac_compliance.py` | 257 |
| `test_thirty_chains_evaluated_under_300ms` | Function | `tests/unit/choices/test_s05_ac_compliance.py` | 291 |
| `test_branching_chains_have_distinct_ids` | Function | `tests/unit/choices/test_s05_ac_compliance.py` | 579 |
| `test_create_returns_chain` | Function | `tests/unit/choices/test_consequence_service.py` | 43 |
| `test_create_with_entries` | Function | `tests/unit/choices/test_consequence_service.py` | 50 |
| `test_create_with_parent_chain` | Function | `tests/unit/choices/test_consequence_service.py` | 69 |
| `test_immediate_entry_activates` | Function | `tests/unit/choices/test_consequence_service.py` | 99 |
| `test_short_term_waits_one_turn` | Function | `tests/unit/choices/test_consequence_service.py` | 112 |
| `test_long_term_waits_many_turns` | Function | `tests/unit/choices/test_consequence_service.py` | 128 |
| `test_hidden_entry_generates_hint_not_change` | Function | `tests/unit/choices/test_consequence_service.py` | 142 |
| `test_foreshadowed_entry_hints` | Function | `tests/unit/choices/test_consequence_service.py` | 159 |
| `test_resolved_chain_skipped` | Function | `tests/unit/choices/test_consequence_service.py` | 173 |
| `test_hidden_entries_foreshadow` | Function | `tests/unit/choices/test_consequence_service.py` | 306 |
| `test_no_hints_for_visible` | Function | `tests/unit/choices/test_consequence_service.py` | 319 |
| `test_reveal_hidden` | Function | `tests/unit/choices/test_consequence_service.py` | 337 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Run_genesis_lite → Generate` | cross_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Pipeline | 4 calls |

## How to Explore

1. `gitnexus_context({name: "test_last_active_turn_only_on_activation"})` — see callers and callees
2. `gitnexus_query({query: "choices"})` — find related execution flows
3. Read key files listed above for implementation details
