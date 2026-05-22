"""Batch smoke: 2 personas x 2 seeds = 4 runs."""

import asyncio
import json
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


async def setup_player():
    async with httpx.AsyncClient(base_url=TTA_URL, timeout=httpx.Timeout(TIMEOUT)) as c:
        r = await c.post(
            "/api/v1/auth/anonymous",
            json={
                "handle": "batch-runner",
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {"core_gameplay": True, "llm_processing": True},
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
                "consent_categories": {"core_gameplay": True, "llm_processing": True},
                "age_13_plus_confirmed": True,
            },
        )
        return token


async def main():
    settings = get_settings()
    init_langfuse(settings)
    llm = None
    try:
        token = await setup_player()
        print(f"Player ready. Token: {token[:30]}...")

        config = BatchConfig(
            scenario_seed_ids=["bus-stop-shimmer", "seed-fantasy-tavern"],
            persona_ids=["curious-explorer", "terse-minimalist"],
            runs_per_combination=1,
            max_parallel_runs=1,
            mode="local",
        )
        llm = SmartRouterLLMClient()
        pipeline = EvaluationPipeline(
            config=config, api_base_url=TTA_URL, api_key=token, llm_client=llm
        )
        n_seeds = len(config.scenario_seed_ids)
        n_personas = len(config.persona_ids)
        total = n_seeds * n_personas
        print(f"\nBatch: {total} runs ({n_seeds} seeds x {n_personas} personas)\n")

        result, exit_code = await pipeline.run()

        print("\n=== Results ===")
        c = result.complete_runs
        t = result.total_runs
        e = result.error_runs
        print(f"Complete: {c}/{t}  Errors: {e}")
        print(f"Verdict: {result.batch_verdict}")
        if result.batch_category_medians:
            print(f"Medians: {json.dumps(result.batch_category_medians, indent=2)}")
        for i, r in enumerate(result.quality_reports[:4]):
            print(f"\n  Run {i + 1}: composite={r.composite_score:.3f} ({r.verdict})")
            for c in r.categories:
                if c.status == "scored":
                    print(f"    {c.category_id}: {c.score:.3f}")
        return exit_code
    finally:
        if llm:
            await llm.aclose()
        shutdown_langfuse()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
