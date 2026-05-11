---
name: universe
description: "Skill for the Universe area of fictional-barnacle. 84 symbols across 8 files."
---

# Universe

84 symbols | 8 files | Cohesion: 78%

## When to Use

- Working with code in `tests/`
- Understanding how test_theme_limit_exceeded_returns_error, test_trope_limit_exceeded_returns_error, test_archetype_limit_exceeded_returns_error work
- Modifying universe-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/universe/test_service.py` | _make_universe_row, test_activate_transitions_dormant_to_active, test_activate_raises_when_already_in_active_session, test_activate_raises_for_archived_universe, test_activate_raises_for_already_active (+13) |
| `tests/unit/universe/test_composition.py` | test_theme_limit_exceeded_returns_error, test_trope_limit_exceeded_returns_error, test_archetype_limit_exceeded_returns_error, test_genre_twist_limit_exceeded_returns_error, test_invalid_theme_name_rejected (+9) |
| `tests/unit/universe/test_actor_service.py` | _make_state_row, test_get_or_create_creates_state_when_absent, test_get_or_create_returns_existing_state, test_upsert_raises_when_state_absent, test_upsert_updates_specified_fields (+7) |
| `src/tta/universe/service.py` | pause, activate, get, _lock_row, patch_config (+6) |
| `src/tta/universe/exceptions.py` | UniverseError, UniverseNotFoundError, UniverseAlreadyActiveError, UniverseArchivedError, UniverseStatusTransitionError (+4) |
| `tests/unit/universe/test_s30_session_universe_binding.py` | test_pause_called_on_session_end, _make_universe_row, _make_activate_pg, test_dormant_universe_can_be_activated, test_paused_universe_can_be_activated_resume (+3) |
| `src/tta/universe/actor_service.py` | get_or_create_character_state, upsert_character_state, _row_to_character_state, get_character_state, _row_to_actor (+3) |
| `src/tta/universe/composition.py` | _max_limit, validate, derive_tone_profile, from_config |

## Entry Points

Start here when exploring this area:

- **`test_theme_limit_exceeded_returns_error`** (Function) — `tests/unit/universe/test_composition.py:79`
- **`test_trope_limit_exceeded_returns_error`** (Function) — `tests/unit/universe/test_composition.py:92`
- **`test_archetype_limit_exceeded_returns_error`** (Function) — `tests/unit/universe/test_composition.py:105`
- **`test_genre_twist_limit_exceeded_returns_error`** (Function) — `tests/unit/universe/test_composition.py:120`
- **`test_invalid_theme_name_rejected`** (Function) — `tests/unit/universe/test_composition.py:185`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `UniverseError` | Class | `src/tta/universe/exceptions.py` | 3 |
| `UniverseNotFoundError` | Class | `src/tta/universe/exceptions.py` | 7 |
| `UniverseAlreadyActiveError` | Class | `src/tta/universe/exceptions.py` | 11 |
| `UniverseArchivedError` | Class | `src/tta/universe/exceptions.py` | 15 |
| `UniverseStatusTransitionError` | Class | `src/tta/universe/exceptions.py` | 19 |
| `ActorNotFoundError` | Class | `src/tta/universe/exceptions.py` | 30 |
| `CharacterStateNotFoundError` | Class | `src/tta/universe/exceptions.py` | 34 |
| `CompositionValidationError` | Class | `src/tta/universe/exceptions.py` | 38 |
| `SeedImmutabilityError` | Class | `src/tta/universe/exceptions.py` | 46 |
| `test_theme_limit_exceeded_returns_error` | Function | `tests/unit/universe/test_composition.py` | 79 |
| `test_trope_limit_exceeded_returns_error` | Function | `tests/unit/universe/test_composition.py` | 92 |
| `test_archetype_limit_exceeded_returns_error` | Function | `tests/unit/universe/test_composition.py` | 105 |
| `test_genre_twist_limit_exceeded_returns_error` | Function | `tests/unit/universe/test_composition.py` | 120 |
| `test_invalid_theme_name_rejected` | Function | `tests/unit/universe/test_composition.py` | 185 |
| `test_valid_theme_name_accepted` | Function | `tests/unit/universe/test_composition.py` | 198 |
| `test_invalid_pacing_rejected` | Function | `tests/unit/universe/test_composition.py` | 216 |
| `test_invalid_density_rejected` | Function | `tests/unit/universe/test_composition.py` | 229 |
| `test_valid_prose_config_accepted` | Function | `tests/unit/universe/test_composition.py` | 242 |
| `test_validator_does_not_reject_subsystem_namespaces` | Function | `tests/unit/universe/test_composition.py` | 334 |
| `test_validate_emits_log_on_success` | Function | `tests/unit/universe/test_composition.py` | 354 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Archive → _row_to_universe` | cross_community | 4 |
| `Pause → _row_to_universe` | cross_community | 4 |
| `Activate → _row_to_universe` | cross_community | 4 |
| `Patch_config → _row_to_universe` | cross_community | 3 |
| `Patch_config → _max_limit` | cross_community | 3 |
| `Ensure_seed → _row_to_universe` | cross_community | 3 |
| `Get_or_create_character_state → _row_to_character_state` | cross_community | 3 |
| `Upsert_character_state → _row_to_character_state` | cross_community | 3 |

## How to Explore

1. `gitnexus_context({name: "test_theme_limit_exceeded_returns_error"})` — see callers and callees
2. `gitnexus_query({query: "universe"})` — find related execution flows
3. Read key files listed above for implementation details
