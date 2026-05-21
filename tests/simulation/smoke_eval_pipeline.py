"""Smoke test: run a single eval pipeline session against live TTA + FMR."""

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
OUTPUT_DIR = Path(os.getenv("TTA_EVAL_OUTPUT_DIR", "data/eval_smoke_output"))
REQUEST_TIMEOUT = float(os.getenv("TTA_SMOKE_HTTP_TIMEOUT", "30"))


async def setup_player() -> str:
    """Create anonymous player, accept consent, return auth token."""
    async with httpx.AsyncClient(
        base_url=TTA_URL,
        timeout=httpx.Timeout(REQUEST_TIMEOUT),
    ) as client:
        # 1. Create anonymous player
        resp = await client.post(
            "/api/v1/auth/anonymous",
            json={
                "handle": "eval-smoke",
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": True,
                },
            },
        )
        resp.raise_for_status()
        token = resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Accept consent with age confirmation
        resp = await client.patch(
            "/api/v1/players/me/consent",
            headers=headers,
            json={
                "consent_version": "1.0",
                "consent_categories": {"core_gameplay": True, "llm_processing": True},
                "age_13_plus_confirmed": True,
            },
        )
        resp.raise_for_status()
        return token


async def main():
    print("=== TTA + FMR Eval Pipeline Smoke Test ===\n")

    settings = get_settings()
    init_langfuse(settings)
    llm: SmartRouterLLMClient | None = None
    try:
        token = await setup_player()
        print(f"Player ready. Token: {token[:30]}...")

        config = BatchConfig(
            scenario_seed_ids=["bus-stop-shimmer"],
            persona_ids=["curious-explorer"],
            runs_per_combination=1,
            max_parallel_runs=1,
            mode="local",
            output_dir=str(OUTPUT_DIR),
        )

        llm = SmartRouterLLMClient()
        pipeline = EvaluationPipeline(
            config=config,
            api_base_url=TTA_URL,
            api_key=token,
            llm_client=llm,
        )

        print(f"Running: {config.scenario_seed_ids[0]} × {config.persona_ids[0]}")
        print("(Genesis + 5+ turns through FMR free models — may take 3-8 minutes)\n")
        result, exit_code = await pipeline.run()

        print("\n=== Results ===")
        print(
            f"Total: {result.total_runs} | "
            f"Complete: {result.complete_runs} | "
            f"Errors: {result.error_runs}"
        )
        print(f"Verdict: {result.batch_verdict}")
        print(f"Medians: {json.dumps(result.batch_category_medians, indent=2)}")

        if result.quality_reports:
            r = result.quality_reports[0]
            print(f"\nComposite: {r.composite_score:.3f} ({r.verdict})")
            for c in r.categories:
                print(f"  {c.category_id} ({c.status}): {c.score}")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = OUTPUT_DIR / "smoke_result.json"
        composite = (
            result.quality_reports[0].composite_score
            if result.quality_reports
            else None
        )
        report_path.write_text(
            json.dumps(
                {
                    "verdict": result.batch_verdict,
                    "complete": result.complete_runs,
                    "errors": result.error_runs,
                    "medians": result.batch_category_medians,
                    "composite": composite,
                },
                indent=2,
            )
        )
        return exit_code
    finally:
        if llm is not None:
            await llm.aclose()
        shutdown_langfuse()


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
