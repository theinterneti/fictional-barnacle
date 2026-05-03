---
name: models
description: "Skill for the Models area of fictional-barnacle. 86 symbols across 9 files."
---

# Models

86 symbols | 9 files | Cohesion: 92%

## When to Use

- Working with code in `tests/`
- Understanding how test_thinking_event_type_is_defined, test_sse_wire_format_clean, test_wire_format_structure work
- Modifying models-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/models/test_world_models.py` | _template_metadata, test_defaults, test_full, test_typed_template, test_empty_lists_default (+29) |
| `src/tta/models/events.py` | format_sse, SSEEvent, TurnStartEvent, NarrativeTokenEvent, NarrativeBlockEvent (+12) |
| `tests/unit/models/test_events.py` | test_wire_format_structure, test_data_is_valid_json, test_event_type_excluded_from_data, test_keepalive_sse_format, test_world_update_serializes_changes (+9) |
| `tests/unit/models/test_consequence_models.py` | _entry, test_defaults, test_hidden_entry, test_entry_has_unique_id, test_parent_ids_for_merging (+7) |
| `src/tta/models/world.py` | clamped, apply_relationship_change, _clamp, trust_to_label, label |
| `tests/unit/pipeline/test_s08_ac_compliance.py` | test_thinking_event_type_is_defined |
| `tests/unit/moderation/test_s24_metadata_leakage.py` | test_sse_wire_format_clean |
| `tests/unit/api/test_turn_atomicity.py` | test_error_event_format_sse_includes_all_fields |
| `tests/unit/api/test_sse_moderation.py` | test_format_sse |

## Entry Points

Start here when exploring this area:

- **`test_thinking_event_type_is_defined`** (Function) — `tests/unit/pipeline/test_s08_ac_compliance.py:431`
- **`test_sse_wire_format_clean`** (Function) — `tests/unit/moderation/test_s24_metadata_leakage.py:56`
- **`test_wire_format_structure`** (Function) — `tests/unit/models/test_events.py:155`
- **`test_data_is_valid_json`** (Function) — `tests/unit/models/test_events.py:162`
- **`test_event_type_excluded_from_data`** (Function) — `tests/unit/models/test_events.py:174`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `SSEEvent` | Class | `src/tta/models/events.py` | 33 |
| `TurnStartEvent` | Class | `src/tta/models/events.py` | 46 |
| `NarrativeTokenEvent` | Class | `src/tta/models/events.py` | 55 |
| `NarrativeBlockEvent` | Class | `src/tta/models/events.py` | 62 |
| `WorldUpdateEvent` | Class | `src/tta/models/events.py` | 69 |
| `ThinkingEvent` | Class | `src/tta/models/events.py` | 76 |
| `StillThinkingEvent` | Class | `src/tta/models/events.py` | 82 |
| `TurnCompleteEvent` | Class | `src/tta/models/events.py` | 88 |
| `ModerationEvent` | Class | `src/tta/models/events.py` | 98 |
| `ErrorEvent` | Class | `src/tta/models/events.py` | 109 |
| `KeepaliveEvent` | Class | `src/tta/models/events.py` | 121 |
| `NarrativeEvent` | Class | `src/tta/models/events.py` | 132 |
| `NarrativeEndEvent` | Class | `src/tta/models/events.py` | 144 |
| `StateUpdateEvent` | Class | `src/tta/models/events.py` | 152 |
| `LocationChangeEvent` | Class | `src/tta/models/events.py` | 163 |
| `HeartbeatEvent` | Class | `src/tta/models/events.py` | 173 |
| `test_thinking_event_type_is_defined` | Function | `tests/unit/pipeline/test_s08_ac_compliance.py` | 431 |
| `test_sse_wire_format_clean` | Function | `tests/unit/moderation/test_s24_metadata_leakage.py` | 56 |
| `test_wire_format_structure` | Function | `tests/unit/models/test_events.py` | 155 |
| `test_data_is_valid_json` | Function | `tests/unit/models/test_events.py` | 162 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Apply_relationship_change → _clamp` | intra_community | 3 |

## How to Explore

1. `gitnexus_context({name: "test_thinking_event_type_is_defined"})` — see callers and callees
2. `gitnexus_query({query: "models"})` — find related execution flows
3. Read key files listed above for implementation details
