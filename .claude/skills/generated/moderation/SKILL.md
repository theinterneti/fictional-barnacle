---
name: moderation
description: "Skill for the Moderation area of fictional-barnacle. 95 symbols across 9 files."
---

# Moderation

95 symbols | 9 files | Cohesion: 90%

## When to Use

- Working with code in `tests/`
- Understanding how test_normal_game_input, test_combat_narrative, test_empty_string work
- Modifying moderation-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/moderation/test_keyword_moderator.py` | test_normal_game_input, test_combat_narrative, test_empty_string, test_content_hash_is_sha256, test_dismember (+27) |
| `tests/unit/moderation/test_hook.py` | _make_state, _pass_result, _block_result, _flag_result, _mock_recorder (+26) |
| `tests/unit/moderation/test_flagging.py` | test_below_threshold_returns_false, test_at_threshold_returns_true, test_above_threshold_does_not_retrigger, test_expired_entries_pruned, test_different_games_tracked_independently (+2) |
| `src/tta/moderation/keyword_moderator.py` | moderate_input, _content_hash, _resolve_verdict, moderate_output, _scan (+1) |
| `src/tta/moderation/hook.py` | pre_generation_check, post_generation_check, _post_check, _checked_call, _build_context (+1) |
| `tests/unit/moderation/test_s24_fail_closed.py` | _turn_state, test_exception_blocks_in_fail_closed, test_exception_passes_in_fail_open, test_fail_closed_has_redirect_content, test_output_exception_blocks_in_fail_closed (+1) |
| `tests/unit/moderation/test_recorder.py` | _make_record, test_save_executes_insert, test_save_passes_all_fields, test_save_logs_error_on_failure |
| `src/tta/moderation/flagging.py` | record_block, reset |
| `src/tta/moderation/recorder.py` | save |

## Entry Points

Start here when exploring this area:

- **`test_normal_game_input`** (Function) — `tests/unit/moderation/test_keyword_moderator.py:27`
- **`test_combat_narrative`** (Function) — `tests/unit/moderation/test_keyword_moderator.py:35`
- **`test_empty_string`** (Function) — `tests/unit/moderation/test_keyword_moderator.py:39`
- **`test_content_hash_is_sha256`** (Function) — `tests/unit/moderation/test_keyword_moderator.py:43`
- **`test_dismember`** (Function) — `tests/unit/moderation/test_keyword_moderator.py:56`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_normal_game_input` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 27 |
| `test_combat_narrative` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 35 |
| `test_empty_string` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 39 |
| `test_content_hash_is_sha256` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 43 |
| `test_dismember` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 56 |
| `test_decapitate` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 61 |
| `test_torture` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 65 |
| `test_case_insensitive` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 69 |
| `test_explicit` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 80 |
| `test_pornographic` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 85 |
| `test_kill_myself` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 96 |
| `test_self_harm_keyword` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 101 |
| `test_how_to_overdose` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 105 |
| `test_ethnic_cleansing` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 116 |
| `test_dehumanize` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 121 |
| `test_bomb_instructions` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 132 |
| `test_drug_synthesis` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 137 |
| `test_ignore_instructions` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 148 |
| `test_dan_mode` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 153 |
| `test_system_prefix` | Function | `tests/unit/moderation/test_keyword_moderator.py` | 157 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Moderate_output → _content_hash` | intra_community | 3 |
| `Moderate_output → _resolve_verdict` | intra_community | 3 |
| `Moderate_output → _severity` | intra_community | 3 |

## How to Explore

1. `gitnexus_context({name: "test_normal_game_input"})` — see callers and callees
2. `gitnexus_query({query: "moderation"})` — find related execution flows
3. Read key files listed above for implementation details
