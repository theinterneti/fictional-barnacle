"""Batch smoke: 2 personas x 2 seeds = 4 runs.

Each run: create player → run pipeline → print progress → next.
Runs sequentially with per-run progress to avoid silent hangs.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx

from tta.config import get_settings
from tta.eval.models import BatchConfig
from tta.eval.pipeline import EvaluationPipeline
from tta.llm.smart_router_client import SmartRouterLLMClient
from tta.observability.langfuse import init_langfuse, shutdown_langfuse

TTA_URL = os.getenv("TTA_URL", "http://localhost:8000")
TIMEOUT = float(os.getenv("TTA_SMOKE_HTTP_TIMEOUT", "30"))


def _flush_print(*args, **kwargs):
    """Print and immediately flush to avoid buffering in background processes."""
    print(*args, **kwargs)
    sys.stdout.flush()


async def setup_player(handle_suffix: str = "") -> str:
    """Create an anonymous player and accept consent. Returns auth token."""
    handle = f"batch-smoke{handle_suffix}"
    async with httpx.AsyncClient(base_url=TTA_URL, timeout=httpx.Timeout(TIMEOUT)) as c:
        r = await c.post(
            "/api/v1/auth/anonymous",
            json={
                "handle": handle,
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": True,
                },
            },
        )
        r.raise_for_status()
        token = r.json()["data"]["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        await c.patch(
            "/api/v1/players/me/consent",
            headers=h,
            json={
                "consent_version": "1.0",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": True,
                },
                "age_13_plus_confirmed": True,
            },
        )
        return token


async def run_one_combination(
    llm: SmartRouterLLMClient,
    seed_id: str,
    persona_id: str,
    run_num: int,
    total: int,
) -> int:
    """Run a single seed × persona combination with progress output."""
    label = f"[{run_num}/{total}]"
    _flush_print(f"{label} Starting: seed={seed_id}, persona={persona_id}")

    token = await setup_player(handle_suffix=f"-{run_num}")
    config = BatchConfig(
        scenario_seed_ids=[seed_id],
        persona_ids=[persona_id],
        runs_per_combination=1,
        max_parallel_runs=1,
        mode="local",
    )
    pipeline = EvaluationPipeline(
        config=config,
        api_base_url=TTA_URL,
        api_key=token,
        llm_client=llm,
    )
    try:
        result, _exit_code = await pipeline.run()
        c = result.complete_runs
        e = result.error_runs
        _flush_print(
            f"{label} Done: {c} complete, {e} errors, verdict={result.batch_verdict}"
        )
        return 0 if c > 0 and e == 0 else 1
    except Exception as exc:
        _flush_print(f"{label} FAILED: {type(exc).__name__}: {exc}")
        return 1


async def main() -> int:
    settings = get_settings()
    init_langfuse(settings)

    seeds = ["bus-stop-shimmer", "seed-fantasy-tavern"]
    personas = ["curious-explorer", "terse-minimalist"]
    total = len(seeds) * len(personas)

    _flush_print(
        f"Batch smoke: {total} runs ({len(seeds)} seeds x {len(personas)} personas)"
    )
    _flush_print(f"TTA_URL={TTA_URL}")

    llm = SmartRouterLLMClient()
    try:
        run_num = 0
        failures = 0
        for seed_id in seeds:
            for persona_id in personas:
                run_num += 1
                failures += await run_one_combination(
                    llm, seed_id, persona_id, run_num, total
                )

        _flush_print(f"\n=== Done: {run_num - failures}/{run_num} passed ===")
        return 0 if failures == 0 else 1
    finally:
        await llm.aclose()
        shutdown_langfuse()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
