---
name: api
description: "Skill for the Api area of fictional-barnacle. 279 symbols across 27 files."
---

# Api

279 symbols | 27 files | Cohesion: 91%

## When to Use

- Working with code in `tests/`
- Understanding how client, test_redis_down_returns_degraded, test_neo4j_down_returns_degraded work
- Modifying api-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/api/test_commands.py` | _game_row, _make_result, test_status_returns_game_info, test_commands_rejected_on_ended_game, test_character_returns_details (+29) |
| `tests/unit/api/test_s26_ac_compliance.py` | _settings, _auth, _build_client, test_missing_auth_returns_401, test_wrong_key_returns_403 (+23) |
| `tests/unit/api/test_auth_routes.py` | _make_result, test_creates_anon_player_and_returns_tokens, test_sets_auth_cookie, test_commits_to_database, test_inserts_player_and_session (+19) |
| `tests/unit/api/test_s27_ac_compliance.py` | _make_result, test_post_games_returns_201, test_post_games_returns_required_fields, test_post_games_player_id_matches_authenticated_player, test_get_game_not_found_returns_404 (+17) |
| `tests/unit/api/test_health.py` | _make_stub, _make_failing_stub, _build_client, client, test_redis_down_returns_degraded (+16) |
| `tests/unit/api/test_s11_ac_compliance.py` | _make_result, _game_row, test_anonymous_returns_201, test_anonymous_response_contains_player_id, test_anonymous_response_contains_access_token (+14) |
| `tests/unit/api/test_s01_ac_compliance.py` | _make_result, _game_row, test_empty_string_returns_400, test_whitespace_only_returns_400, test_save_returns_confirmation_message (+8) |
| `tests/unit/api/test_gameplay_e2e.py` | _make_result, _game_row, test_step1_create_game, test_step2_submit_narrative_turn, test_step3_empty_input_returns_400 (+8) |
| `tests/unit/api/test_sse_replay.py` | _make_redis, test_get_next_id_increments_counter, test_append_stores_event_and_refreshes_ttl, test_append_evicts_oldest_when_over_cap, test_replay_after_hit_returns_events (+7) |
| `tests/unit/api/test_genesis_integration.py` | _make_result, _genesis_result_mock, test_genesis_success_returns_narrative_intro, test_genesis_failure_still_creates_game, test_genesis_uses_world_id_for_template_lookup (+7) |

## Entry Points

Start here when exploring this area:

- **`client`** (Function) — `tests/unit/api/test_health.py:80`
- **`test_redis_down_returns_degraded`** (Function) — `tests/unit/api/test_health.py:117`
- **`test_neo4j_down_returns_degraded`** (Function) — `tests/unit/api/test_health.py:131`
- **`test_redis_and_neo4j_down_still_degraded`** (Function) — `tests/unit/api/test_health.py:142`
- **`test_postgres_down_returns_unhealthy`** (Function) — `tests/unit/api/test_health.py:163`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `client` | Function | `tests/unit/api/test_health.py` | 80 |
| `test_redis_down_returns_degraded` | Function | `tests/unit/api/test_health.py` | 117 |
| `test_neo4j_down_returns_degraded` | Function | `tests/unit/api/test_health.py` | 131 |
| `test_redis_and_neo4j_down_still_degraded` | Function | `tests/unit/api/test_health.py` | 142 |
| `test_postgres_down_returns_unhealthy` | Function | `tests/unit/api/test_health.py` | 163 |
| `test_all_down_returns_unhealthy` | Function | `tests/unit/api/test_health.py` | 175 |
| `test_neo4j_not_configured_is_healthy` | Function | `tests/unit/api/test_health.py` | 195 |
| `test_returns_503_when_postgres_fails` | Function | `tests/unit/api/test_health.py` | 232 |
| `test_returns_503_when_redis_fails` | Function | `tests/unit/api/test_health.py` | 244 |
| `test_not_configured_is_ready` | Function | `tests/unit/api/test_health.py` | 253 |
| `test_moderation_disabled_is_healthy` | Function | `tests/unit/api/test_health.py` | 273 |
| `test_moderation_ok_is_healthy` | Function | `tests/unit/api/test_health.py` | 285 |
| `test_moderation_unavailable_degrades` | Function | `tests/unit/api/test_health.py` | 297 |
| `test_breaker_open_degrades_health` | Function | `tests/unit/api/test_health.py` | 318 |
| `test_breaker_half_open_degrades_health` | Function | `tests/unit/api/test_health.py` | 330 |
| `test_breaker_open_blocks_readiness` | Function | `tests/unit/api/test_health.py` | 342 |
| `test_breaker_half_open_blocks_readiness` | Function | `tests/unit/api/test_health.py` | 353 |
| `test_breaker_not_configured_is_ready` | Function | `tests/unit/api/test_health.py` | 364 |
| `test_status_returns_game_info` | Function | `tests/unit/api/test_commands.py` | 192 |
| `test_commands_rejected_on_ended_game` | Function | `tests/unit/api/test_commands.py` | 250 |

## How to Explore

1. `gitnexus_context({name: "client"})` — see callers and callees
2. `gitnexus_query({query: "api"})` — find related execution flows
3. Read key files listed above for implementation details
