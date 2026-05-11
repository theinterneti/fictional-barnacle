---
name: world
description: "Skill for the World area of fictional-barnacle. 339 symbols across 25 files."
---

# World

339 symbols | 25 files | Cohesion: 88%

## When to Use

- Working with code in `tests/`
- Understanding how test_applied_changes_visible_in_subsequent_world_state, test_batch_changes_all_applied_atomically, test_state_consistent_after_multiple_batches work
- Modifying world-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/world/test_neo4j_service.py` | _make_driver, _setup_tx_session, test_satisfies_protocol, test_returns_empty_list, test_player_moved (+34) |
| `tests/unit/world/test_changes.py` | _make_seed, _setup_world, test_valid_movement, test_missing_from_id, test_missing_to_id (+26) |
| `tests/unit/world/test_memory_world_service.py` | _make_seed, test_creates_locations, test_creates_connections, test_creates_npcs, test_creates_items (+22) |
| `tests/unit/world/test_world_service.py` | test_get_recent_events_delegates, test_get_recent_events_empty, get_location_context, test_get_location_context, get_recent_events (+20) |
| `tests/unit/world/test_relationship_service.py` | test_npc_tier_changed, test_relationship_changed_is_noop, test_returns_none_when_absent, test_returns_relationship_after_set, test_returns_deep_copy (+19) |
| `tests/unit/world/test_s04_ac_compliance.py` | test_applied_changes_visible_in_subsequent_world_state, test_batch_changes_all_applied_atomically, test_state_consistent_after_multiple_batches, _make_seed, test_world_context_has_current_location (+15) |
| `tests/unit/world/test_s13_ac_compliance.py` | _minimal_metadata, _minimal_region, _minimal_location, _minimal_template, test_location_valid_region_key_is_accepted (+13) |
| `tests/unit/world/test_dialogue_context.py` | _make_npc, test_returns_context_with_defaults, test_knowledge_hidden_at_zero_trust, test_goals_hidden_at_zero_trust, test_relationship_values_populated (+11) |
| `tests/unit/world/test_template_registry.py` | _minimal_template_dict, _write_template, _make_seed, test_invalid_template_raises, test_duplicate_template_key_raises (+11) |
| `src/tta/world/service.py` | apply_world_changes, validate_movement, get_location_context, get_recent_events, get_player_location (+9) |

## Entry Points

Start here when exploring this area:

- **`test_applied_changes_visible_in_subsequent_world_state`** (Function) — `tests/unit/world/test_s04_ac_compliance.py:227`
- **`test_batch_changes_all_applied_atomically`** (Function) — `tests/unit/world/test_s04_ac_compliance.py:415`
- **`test_state_consistent_after_multiple_batches`** (Function) — `tests/unit/world/test_s04_ac_compliance.py:487`
- **`test_npc_tier_changed`** (Function) — `tests/unit/world/test_relationship_service.py:377`
- **`test_relationship_changed_is_noop`** (Function) — `tests/unit/world/test_relationship_service.py:411`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `TemplateValidationError` | Class | `src/tta/world/template_validator.py` | 11 |
| `DuplicateKeyError` | Class | `src/tta/world/template_validator.py` | 15 |
| `DanglingReferenceError` | Class | `src/tta/world/template_validator.py` | 19 |
| `NoStartingLocationError` | Class | `src/tta/world/template_validator.py` | 23 |
| `DirectionConflictError` | Class | `src/tta/world/template_validator.py` | 27 |
| `ItemPlacementError` | Class | `src/tta/world/template_validator.py` | 31 |
| `EmptyTemplateError` | Class | `src/tta/world/template_validator.py` | 35 |
| `DisconnectedGraphError` | Class | `src/tta/world/template_validator.py` | 39 |
| `test_applied_changes_visible_in_subsequent_world_state` | Function | `tests/unit/world/test_s04_ac_compliance.py` | 227 |
| `test_batch_changes_all_applied_atomically` | Function | `tests/unit/world/test_s04_ac_compliance.py` | 415 |
| `test_state_consistent_after_multiple_batches` | Function | `tests/unit/world/test_s04_ac_compliance.py` | 487 |
| `test_npc_tier_changed` | Function | `tests/unit/world/test_relationship_service.py` | 377 |
| `test_relationship_changed_is_noop` | Function | `tests/unit/world/test_relationship_service.py` | 411 |
| `test_creates_locations` | Function | `tests/unit/world/test_memory_world_service.py` | 106 |
| `test_creates_connections` | Function | `tests/unit/world/test_memory_world_service.py` | 119 |
| `test_creates_npcs` | Function | `tests/unit/world/test_memory_world_service.py` | 129 |
| `test_creates_items` | Function | `tests/unit/world/test_memory_world_service.py` | 139 |
| `test_bidirectional_connections` | Function | `tests/unit/world/test_memory_world_service.py` | 149 |
| `test_raises_on_unknown_location` | Function | `tests/unit/world/test_memory_world_service.py` | 171 |
| `test_returns_context` | Function | `tests/unit/world/test_memory_world_service.py` | 178 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Apply_changes → Validate_movement` | intra_community | 4 |
| `Main → _parse_statements` | intra_community | 4 |
| `Update_relationship → _node_pattern` | intra_community | 3 |
| `Update_relationship → _record_to_relationship` | intra_community | 3 |
| `Apply_changes → _validate_item_taken` | intra_community | 3 |
| `Apply_changes → _validate_item_dropped` | intra_community | 3 |
| `Apply_changes → _validate_npc_moved` | intra_community | 3 |
| `Select_by_preferences → Get` | intra_community | 3 |
| `Set_relationship → _node_pattern` | intra_community | 3 |
| `Check_companion_eligible → _node_pattern` | intra_community | 3 |

## How to Explore

1. `gitnexus_context({name: "test_applied_changes_visible_in_subsequent_world_state"})` — see callers and callees
2. `gitnexus_query({query: "world"})` — find related execution flows
3. Read key files listed above for implementation details
