"""Genesis v2 smoke test — validates world generation quality.

Per TTA-CRITICAL-REVIEW §5: Run Genesis v2 N times, manually evaluate a sample.
This script generates worlds with canned player inputs and reports quality metrics.

Usage:
    uv run python scripts/genesis_v2_smoke.py [--count N] [--verbose]

Requirements:
    - FMR running on localhost:3456
    - PostgreSQL running (TTA_DATABASE_URL set or default)
    - Redis running (for session store)
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tta.genesis.genesis_v2 import (
    _PHASE_ORDER,
    GenesisOrchestrator,
)
from tta.llm.litellm_client import LiteLLMClient

# Canned player inputs — one per phase interaction
# These are intentionally simple to keep the smoke test fast
PLAYER_INPUTS = [  # noqa: E501
    "I want to explore a world where technology and nature have merged into something strange and beautiful.",  # noqa: E501
    "I'm drawn to places where everyday reality feels slightly unstable, like anything could shift.",  # noqa: E501
    "Sometimes I feel like I don't quite fit in my own world. Maybe that's why I'm here.",  # noqa: E501
    "I'm someone who notices details others miss. The small things that hint at bigger truths.",  # noqa: E501
    "I would name myself Kai. It means 'ocean' — something deep and unknowable but familiar.",  # noqa: E501
    "I think about what it means to truly belong somewhere, to something.",
    "I'm ready to step through. Whatever waits on the other side.",
]


async def run_one_genesis(llm: LiteLLMClient, pg_factory, run_id: int) -> dict:
    """Run a single genesis session and return quality metrics."""
    session_id = uuid4()
    universe_id = uuid4()
    result = {
        "run_id": run_id,
        "session_id": str(session_id),
        "universe_id": str(universe_id),
        "phases_completed": 0,
        "total_interactions": 0,
        "narrator_responses": [],
        "final_state": None,
        "errors": [],
        "quality": {
            "completed": False,
            "character_named": False,
            "starting_location_set": False,
            "traits_inferred": 0,
            "first_turn_seed_length": 0,
            "response_lengths": [],
        },
    }

    async with pg_factory() as pg:
        try:
            # Create a game_sessions row — genesis_v2 persists state to
            # game_sessions.genesis_state via UPDATE; the row must exist.
            # Also need a players row for the FK constraint.
            from sqlalchemy import text as sa_text
            player_id = uuid4()
            await pg.execute(
                sa_text(
                    "INSERT INTO players (id, handle, created_at) "
                    "VALUES (:pid, :handle, NOW()) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"pid": player_id, "handle": f"smoke_{run_id}_{session_id.hex[:8]}"},
            )
            await pg.execute(
                sa_text(
                    "INSERT INTO game_sessions (id, player_id, world_seed, status) "
                    "VALUES (:sid, :pid, CAST(:seed AS jsonb), 'creating') "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "sid": session_id,
                    "pid": player_id,
                    "seed": '{"genesis": {"seed_phrase": "smoke test"}}',
                },
            )
            await pg.commit()

            orch = GenesisOrchestrator(llm)
            response, state = await orch.start(session_id, universe_id, pg)
            result["narrator_responses"].append(response)

            input_idx = 0
            while not state.completed and input_idx < len(PLAYER_INPUTS) * 3:
                player_input = PLAYER_INPUTS[min(input_idx, len(PLAYER_INPUTS) - 1)]
                response, state = await orch.advance(session_id, player_input, pg)
                result["narrator_responses"].append(response)
                input_idx += 1

                if state.completed:
                    break

            result["phases_completed"] = (
                _PHASE_ORDER.index(state.current_phase) + 1
                if not state.completed
                else 8
            )
            result["total_interactions"] = len(state.interactions)
            result["final_state"] = state.to_dict()
            result["quality"]["completed"] = state.completed
            result["quality"]["character_named"] = bool(state.character_name)
            result["quality"]["starting_location_set"] = bool(state.starting_location)
            result["quality"]["traits_inferred"] = len(state.inferred_traits)
            result["quality"]["first_turn_seed_length"] = (
                len(state.first_turn_seed) if state.first_turn_seed else 0
            )
            result["quality"]["response_lengths"] = [
                len(r) for r in result["narrator_responses"]
            ]

        except Exception as e:
            result["errors"].append(str(e))

    return result


async def main(count: int = 5, verbose: bool = False):
    """Run N genesis sessions and report results."""

    # Mirror the app's env setup: litellm reads OPENAI_API_KEY,
    # but our .env only defines TTA_OPENAI_API_KEY.
    import os as _os
    _tta_key = _os.environ.get("TTA_OPENAI_API_KEY", "")
    if _tta_key:
        _os.environ.setdefault("OPENAI_API_KEY", _tta_key)
    _os.environ.setdefault("OPENAI_API_BASE", "http://localhost:3456/v1")

    # LLM client (uses FMR via LiteLLM)
    llm = LiteLLMClient()

    # Database — respect TTA_DATABASE_URL if set, otherwise use test defaults
    database_url = _os.environ.get(
        "TTA_DATABASE_URL",
        "postgresql+asyncpg://tta_test:tta_test@localhost:5434/tta_test",
    )
    engine = create_async_engine(database_url, echo=False)
    pg_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print("=== Genesis v2 Smoke Test ===\n", flush=True)
    print(f"Runs: {count}", flush=True)
    print(f"Started: {datetime.now(UTC).isoformat()}\n", flush=True)

    results = []
    for i in range(count):
        print(f"  [{i+1}/{count}] Generating world...", end=" ", flush=True)
        result = await run_one_genesis(llm, pg_factory, i + 1)
        results.append(result)

        status = "✓ COMPLETE" if result["quality"]["completed"] else "✗ INCOMPLETE"
        phases = result["phases_completed"]
        traits = result["quality"]["traits_inferred"]
        named = "named" if result["quality"]["character_named"] else "unnamed"
        located = "located" if result["quality"]["starting_location_set"] else "noloc"
        print(f"{status} | phases={phases} traits={traits} char={named} loc={located}")

        if verbose and result["narrator_responses"]:
            print(f"    Opening: {result['narrator_responses'][0][:120]}...")
            if result["final_state"]:
                fs = result["final_state"]
                print(f"    Character: {fs.get('character_name', 'unnamed')}")
                print(f"    Location: {fs.get('starting_location', 'unknown')}")
                print(f"    Traits: {fs.get('inferred_traits', [])}")

        if result["errors"]:
            print(f"    Errors: {result['errors']}")

    # Summary
    completed = sum(1 for r in results if r["quality"]["completed"])
    named = sum(1 for r in results if r["quality"]["character_named"])
    located = sum(1 for r in results if r["quality"]["starting_location_set"])
    avg_traits = (
        sum(r["quality"]["traits_inferred"] for r in results) / len(results)
        if results
        else 0
    )
    all_lengths = []
    for r in results:
        all_lengths.extend(r["quality"]["response_lengths"])
    avg_response_len = sum(all_lengths) / len(all_lengths) if all_lengths else 0

    print("\n=== Results ===")
    print(f"Completion rate:    {completed}/{count} ({completed/count*100:.0f}%)")
    print(f"Characters named:   {named}/{count}")
    print(f"Locations set:      {located}/{count}"
          "  (note: genesis_v2 does not set starting_location)")
    print(f"Avg traits:         {avg_traits:.1f}")
    print(f"Avg response len:   {avg_response_len:.0f} chars")
    print(f"Errors:             {sum(len(r['errors']) for r in results)}")

    # Save detailed results
    out_path = Path("data/genesis_v2_smoke_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "count": count,
                "summary": {
                    "completed": completed,
                    "named": named,
                    "located": located,
                    "avg_traits": avg_traits,
                    "avg_response_len": avg_response_len,
                },
                "results": results,
            },
            indent=2,
            default=str,
        )
    )
    print(f"\nDetailed results saved to: {out_path}")

    # Gate check — all runs must complete for a clean gate pass.
    # Individual world quality is evaluated manually from the JSON output.
    if completed == count:
        print(f"\n✓ SMOKE TEST PASSED: {completed}/{count} worlds completed")
        return 0
    else:
        print(f"\n✗ SMOKE TEST FAILED: only {completed}/{count} worlds completed")
        return 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--count", type=int, default=5, help="Number of worlds to generate"
    )
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    if args.count < 1:
        print("Error: --count must be >= 1", file=sys.stderr)
        sys.exit(2)

    exit_code = asyncio.run(main(count=args.count, verbose=args.verbose))
    sys.exit(exit_code)
