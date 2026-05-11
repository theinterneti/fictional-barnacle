---
name: simulation
description: "Skill for the Simulation area of fictional-barnacle. 130 symbols across 13 files."
---

# Simulation

130 symbols | 13 files | Cohesion: 87%

## When to Use

- Working with code in `tests/`
- Understanding how test_short_game_single_session, test_medium_game_multi_session, test_long_game_marathon work
- Modifying simulation-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/simulation/test_npc_autonomy.py` | _make_npc, test_default_processor_returns_world_delta, test_empty_npcs_returns_empty_delta, test_key_npc_with_schedule_is_processed, test_key_npc_without_schedule_is_skipped (+14) |
| `tests/simulation/test_gameplay_simulation.py` | _bootstrap_world, _run_turn, _play_script, _success_rate, _unique_narrative_ratio (+13) |
| `tests/unit/simulation/test_consequence.py` | _make_source, test_propagate_returns_list_of_propagation_results, test_hop0_record_created_when_affected_entity_id_set, test_no_hop0_when_no_affected_entity_id, test_faction_shortcut_creates_hop1_record (+11) |
| `tests/unit/simulation/test_world_time.py` | _make_state, _make_deps, _wt_dict, test_deliver_advances_world_time_one_tick, test_failed_turn_no_time_advance (+9) |
| `tests/unit/simulation/test_npc_memory.py` | _make_edge, test_gossip_propagates_max_two_hops, test_reliability_floor_stops_propagation, test_gossip_idempotency_same_episode_not_re_recorded, test_get_relationship_returns_edge (+8) |
| `tests/unit/simulation/test_world_memory.py` | _record, test_record_returns_memory_record, test_get_context_returns_three_tiers, test_get_context_working_tier_is_most_recent, test_budget_cap_drops_records (+7) |
| `tests/simulation/conftest.py` | _classify_input, _pick_narrative, _pick_suggestions, _extract_player_input, _respond (+5) |
| `src/tta/simulation/npc_autonomy.py` | process, _resolve_npc_field, _in_salience_window, _process_rule_based, _process_llm_batch (+1) |
| `src/tta/simulation/npc_memory.py` | _distort_content, propagate_gossip, get_relationship, update_relationship, record_episode (+1) |
| `src/tta/simulation/consequence.py` | propagate, _decay_severity, _fidelity_description, _propagate_one, _make_record (+1) |

## Entry Points

Start here when exploring this area:

- **`test_short_game_single_session`** (Function) — `tests/simulation/test_gameplay_simulation.py:209`
- **`test_medium_game_multi_session`** (Function) — `tests/simulation/test_gameplay_simulation.py:246`
- **`test_long_game_marathon`** (Function) — `tests/simulation/test_gameplay_simulation.py:298`
- **`test_player_surprise_inputs`** (Function) — `tests/simulation/test_gameplay_simulation.py:360`
- **`test_narrative_variety`** (Function) — `tests/simulation/test_gameplay_simulation.py:405`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_short_game_single_session` | Function | `tests/simulation/test_gameplay_simulation.py` | 209 |
| `test_medium_game_multi_session` | Function | `tests/simulation/test_gameplay_simulation.py` | 246 |
| `test_long_game_marathon` | Function | `tests/simulation/test_gameplay_simulation.py` | 298 |
| `test_player_surprise_inputs` | Function | `tests/simulation/test_gameplay_simulation.py` | 360 |
| `test_narrative_variety` | Function | `tests/simulation/test_gameplay_simulation.py` | 405 |
| `test_world_state_evolution` | Function | `tests/simulation/test_gameplay_simulation.py` | 454 |
| `test_intent_classification_coverage` | Function | `tests/simulation/test_gameplay_simulation.py` | 490 |
| `test_suggested_actions_quality` | Function | `tests/simulation/test_gameplay_simulation.py` | 538 |
| `test_empty_input_handling` | Function | `tests/simulation/test_gameplay_simulation.py` | 584 |
| `test_rapid_fire_turns` | Function | `tests/simulation/test_gameplay_simulation.py` | 605 |
| `test_full_simulation_report` | Function | `tests/simulation/test_gameplay_simulation.py` | 649 |
| `test_default_processor_returns_world_delta` | Function | `tests/unit/simulation/test_npc_autonomy.py` | 77 |
| `test_empty_npcs_returns_empty_delta` | Function | `tests/unit/simulation/test_npc_autonomy.py` | 84 |
| `test_key_npc_with_schedule_is_processed` | Function | `tests/unit/simulation/test_npc_autonomy.py` | 98 |
| `test_key_npc_without_schedule_is_skipped` | Function | `tests/unit/simulation/test_npc_autonomy.py` | 108 |
| `test_supporting_npc_in_salience_window_is_processed` | Function | `tests/unit/simulation/test_npc_autonomy.py` | 122 |
| `test_supporting_npc_outside_salience_window_is_skipped` | Function | `tests/unit/simulation/test_npc_autonomy.py` | 132 |
| `test_supporting_npc_no_schedule_skipped` | Function | `tests/unit/simulation/test_npc_autonomy.py` | 147 |
| `test_background_npc_never_processed` | Function | `tests/unit/simulation/test_npc_autonomy.py` | 161 |
| `test_key_npc_never_deferred` | Function | `tests/unit/simulation/test_npc_autonomy.py` | 175 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Generate → _extract_player_input` | intra_community | 4 |
| `Generate → _pick_narrative` | intra_community | 4 |
| `Generate → _pick_suggestions` | intra_community | 4 |
| `Generate → _classify_input` | intra_community | 4 |
| `Stream → _extract_player_input` | intra_community | 4 |
| `Stream → _pick_narrative` | intra_community | 4 |
| `Stream → _pick_suggestions` | intra_community | 4 |
| `Stream → _classify_input` | intra_community | 4 |
| `Process → _resolve_npc_field` | cross_community | 4 |
| `Record → _estimate_tokens` | intra_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| World | 2 calls |

## How to Explore

1. `gitnexus_context({name: "test_short_game_single_session"})` — see callers and callees
2. `gitnexus_query({query: "simulation"})` — find related execution flows
3. Read key files listed above for implementation details
