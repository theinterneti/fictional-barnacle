---
name: scripts
description: "Skill for the Scripts area of fictional-barnacle. 46 symbols across 5 files."
---

# Scripts

46 symbols | 5 files | Cohesion: 85%

## When to Use

- Working with code in `scripts/`
- Understanding how run, main, register_player work
- Modifying scripts-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `scripts/playtest.py` | _green, _parse_sse_lines, register_player, create_game, submit_turn (+8) |
| `scripts/run_sims.py` | _mean, _stdev, print_tier_summary, print_per_qc_insights, _pearson (+8) |
| `scripts/sim_runner.py` | _c, _register_player, _create_game, _run_scenario, _print_report (+7) |
| `scripts/migrate_validate_v2.py` | _fail, _ok, _check, _check_gt, validate (+1) |
| `scripts/load_test.py` | _consume_sse, submit_turn |

## Entry Points

Start here when exploring this area:

- **`run`** (Function) — `scripts/sim_runner.py:509`
- **`main`** (Function) — `scripts/sim_runner.py:615`
- **`register_player`** (Function) — `scripts/playtest.py:67`
- **`create_game`** (Function) — `scripts/playtest.py:76`
- **`submit_turn`** (Function) — `scripts/playtest.py:83`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `run` | Function | `scripts/sim_runner.py` | 509 |
| `main` | Function | `scripts/sim_runner.py` | 615 |
| `register_player` | Function | `scripts/playtest.py` | 67 |
| `create_game` | Function | `scripts/playtest.py` | 76 |
| `submit_turn` | Function | `scripts/playtest.py` | 83 |
| `stream_narrative` | Function | `scripts/playtest.py` | 93 |
| `main` | Function | `scripts/playtest.py` | 161 |
| `validate` | Function | `scripts/migrate_validate_v2.py` | 47 |
| `main` | Function | `scripts/migrate_validate_v2.py` | 135 |
| `print_tier_summary` | Function | `scripts/run_sims.py` | 280 |
| `print_per_qc_insights` | Function | `scripts/run_sims.py` | 373 |
| `run_tier` | Function | `scripts/run_sims.py` | 211 |
| `print_persona_breakdown` | Function | `scripts/run_sims.py` | 342 |
| `print_attention_dropout` | Function | `scripts/run_sims.py` | 421 |
| `main` | Function | `scripts/run_sims.py` | 437 |
| `submit_turn` | Function | `scripts/load_test.py` | 133 |
| `_c` | Function | `scripts/sim_runner.py` | 45 |
| `_register_player` | Function | `scripts/sim_runner.py` | 201 |
| `_create_game` | Function | `scripts/sim_runner.py` | 233 |
| `_run_scenario` | Function | `scripts/sim_runner.py` | 349 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → _parse_sse_block` | cross_community | 6 |
| `Main → _extract_narrative` | cross_community | 5 |
| `Main → _count_contradictions` | cross_community | 5 |
| `Main → _check_first_turn_character` | cross_community | 5 |
| `Main → _register_player` | intra_community | 4 |
| `Main → _create_game` | intra_community | 4 |
| `Main → _make_commentary` | cross_community | 4 |
| `Main → _score_qc02` | cross_community | 4 |
| `Main → _score_qc03` | cross_community | 4 |
| `Stream_narrative → _color` | cross_community | 4 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Quality | 1 calls |

## How to Explore

1. `gitnexus_context({name: "run"})` — see callers and callees
2. `gitnexus_query({query: "scripts"})` — find related execution flows
3. Read key files listed above for implementation details
