---
name: persistence
description: "Skill for the Persistence area of fictional-barnacle. 137 symbols across 13 files."
---

# Persistence

137 symbols | 13 files | Cohesion: 86%

## When to Use

- Working with code in `tests/`
- Understanding how test_create_player_returns_player, test_get_player_returns_optional_player, test_create_session_returns_player_session work
- Modifying persistence-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/persistence/test_memory_repos.py` | test_create_game, test_get_game, test_get_game_not_found, test_update_game_status, test_update_game_status_not_found_raises (+42) |
| `src/tta/persistence/memory.py` | create_game, get_game, update_game_status, list_player_games, create_turn (+14) |
| `tests/unit/persistence/test_persistence_sigs.py` | _return_annotation, test_create_player_returns_player, test_get_player_returns_optional_player, test_create_session_returns_player_session, test_get_session_returns_optional_session (+13) |
| `tests/unit/persistence/test_s12_ac_compliance.py` | test_duplicate_turn_number_rejected, test_created_turn_is_retrievable, test_turn_retrievable_across_multiple_sessions, test_completed_turn_is_retrievable_with_narrative, test_sequential_turns_have_monotone_turn_numbers (+5) |
| `tests/unit/persistence/test_redis_session.py` | _make_state, test_cache_hit, test_sets_with_ttl, test_default_ttl, test_returns_cached_state (+4) |
| `tests/unit/persistence/test_consistency.py` | _cached_payload, _sql_row, test_matching_state_is_consistent, test_phantom_session_detected, test_content_mismatch_detected (+2) |
| `src/tta/persistence/redis_session.py` | _key, get_active_session, get_or_reconstruct_session, set_active_session, delete_active_session (+1) |
| `src/tta/persistence/postgres.py` | get_turn, get_processing_turn, get_turn_by_idempotency_key, get_recent_turns, _row_to_dict |
| `src/tta/persistence/engine.py` | _classify_operation, _after_cursor_execute, _handle_error, _ensure_async_url, build_engine |
| `src/tta/persistence/audit_repo.py` | append, decode_cursor, query, create_and_append |

## Entry Points

Start here when exploring this area:

- **`test_create_player_returns_player`** (Function) — `tests/unit/persistence/test_persistence_sigs.py:189`
- **`test_get_player_returns_optional_player`** (Function) — `tests/unit/persistence/test_persistence_sigs.py:193`
- **`test_create_session_returns_player_session`** (Function) — `tests/unit/persistence/test_persistence_sigs.py:198`
- **`test_get_session_returns_optional_session`** (Function) — `tests/unit/persistence/test_persistence_sigs.py:203`
- **`test_delete_session_returns_none`** (Function) — `tests/unit/persistence/test_persistence_sigs.py:208`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_create_player_returns_player` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 189 |
| `test_get_player_returns_optional_player` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 193 |
| `test_create_session_returns_player_session` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 198 |
| `test_get_session_returns_optional_session` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 203 |
| `test_delete_session_returns_none` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 208 |
| `test_create_game_returns_game_session` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 213 |
| `test_get_game_returns_optional_game` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 218 |
| `test_update_game_status_returns_none` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 223 |
| `test_list_player_games_returns_list` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 228 |
| `test_create_turn_returns_dict` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 233 |
| `test_get_turn_returns_optional_dict` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 238 |
| `test_complete_turn_returns_none` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 243 |
| `test_create_world_event_returns_world_event` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 248 |
| `test_get_recent_events_returns_list` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 253 |
| `test_redis_get_returns_optional_game_state` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 258 |
| `test_redis_set_returns_none` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 263 |
| `test_redis_delete_returns_none` | Function | `tests/unit/persistence/test_persistence_sigs.py` | 268 |
| `test_create_game` | Function | `tests/unit/persistence/test_memory_repos.py` | 159 |
| `test_get_game` | Function | `tests/unit/persistence/test_memory_repos.py` | 167 |
| `test_get_game_not_found` | Function | `tests/unit/persistence/test_memory_repos.py` | 174 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Get_or_reconstruct_session → _key` | intra_community | 3 |

## How to Explore

1. `gitnexus_context({name: "test_create_player_returns_player"})` — see callers and callees
2. `gitnexus_query({query: "persistence"})` — find related execution flows
3. Read key files listed above for implementation details
