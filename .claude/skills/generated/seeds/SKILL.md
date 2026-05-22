---
name: seeds
description: "Skill for the Seeds area of fictional-barnacle. 43 symbols across 5 files."
---

# Seeds

43 symbols | 5 files | Cohesion: 93%

## When to Use

- Working with code in `tests/`
- Understanding how test_wrong_version_raises, test_correct_version_ok, test_id_with_uppercase_raises work
- Modifying seeds-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/seeds/test_seeds.py` | _write_seed, test_wrong_version_raises, test_correct_version_ok, test_id_with_uppercase_raises, test_id_with_underscore_raises (+14) |
| `tests/unit/seeds/test_s41_ac_compliance.py` | test_get_by_id_returns_manifest, test_get_by_id_correct_genre, test_get_unknown_id_returns_none, test_valid_seeds_survive_invalid_peer, test_all_canonical_seeds_load (+5) |
| `src/tta/seeds/validator.py` | load_and_validate, _load_yaml, _check_required, _check_description, _check_schema_version (+3) |
| `src/tta/seeds/registry.py` | __init__, _load, get, loaded_count, list |
| `src/tta/genesis/genesis_v2.py` | apply_seed_composition |

## Entry Points

Start here when exploring this area:

- **`test_wrong_version_raises`** (Function) — `tests/unit/seeds/test_seeds.py:53`
- **`test_correct_version_ok`** (Function) — `tests/unit/seeds/test_seeds.py:59`
- **`test_id_with_uppercase_raises`** (Function) — `tests/unit/seeds/test_seeds.py:71`
- **`test_id_with_underscore_raises`** (Function) — `tests/unit/seeds/test_seeds.py:77`
- **`test_id_too_long_raises`** (Function) — `tests/unit/seeds/test_seeds.py:83`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_wrong_version_raises` | Function | `tests/unit/seeds/test_seeds.py` | 53 |
| `test_correct_version_ok` | Function | `tests/unit/seeds/test_seeds.py` | 59 |
| `test_id_with_uppercase_raises` | Function | `tests/unit/seeds/test_seeds.py` | 71 |
| `test_id_with_underscore_raises` | Function | `tests/unit/seeds/test_seeds.py` | 77 |
| `test_id_too_long_raises` | Function | `tests/unit/seeds/test_seeds.py` | 83 |
| `test_id_exactly_64_chars_ok` | Function | `tests/unit/seeds/test_seeds.py` | 89 |
| `test_id_with_digits_ok` | Function | `tests/unit/seeds/test_seeds.py` | 95 |
| `test_empty_tags_raises` | Function | `tests/unit/seeds/test_seeds.py` | 108 |
| `test_eleven_tags_raises` | Function | `tests/unit/seeds/test_seeds.py` | 114 |
| `test_ten_tags_ok` | Function | `tests/unit/seeds/test_seeds.py` | 120 |
| `test_tags_not_list_raises` | Function | `tests/unit/seeds/test_seeds.py` | 126 |
| `test_short_description_raises` | Function | `tests/unit/seeds/test_seeds.py` | 139 |
| `test_minimum_description_ok` | Function | `tests/unit/seeds/test_seeds.py` | 145 |
| `test_missing_required_field_raises` | Function | `tests/unit/seeds/test_seeds.py` | 170 |
| `test_dirty_frodo_tags_portal_not_strange_mundane` | Function | `tests/unit/seeds/test_seeds.py` | 249 |
| `test_get_by_id_returns_manifest` | Function | `tests/unit/seeds/test_s41_ac_compliance.py` | 100 |
| `test_get_by_id_correct_genre` | Function | `tests/unit/seeds/test_s41_ac_compliance.py` | 108 |
| `test_get_unknown_id_returns_none` | Function | `tests/unit/seeds/test_s41_ac_compliance.py` | 116 |
| `test_valid_seeds_survive_invalid_peer` | Function | `tests/unit/seeds/test_s41_ac_compliance.py` | 180 |
| `get` | Function | `src/tta/seeds/registry.py` | 80 |

## How to Explore

1. `gitnexus_context({name: "test_wrong_version_raises"})` — see callers and callees
2. `gitnexus_query({query: "seeds"})` — find related execution flows
3. Read key files listed above for implementation details
