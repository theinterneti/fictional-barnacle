"""Smoke test: run a single eval pipeline session against live TTA + FMR."""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx

from tta.config import get_settings
from tta.eval.models import BatchConfig
from tta.eval.pipeline import EvaluationPipeline
from tta.llm.smart_router_client import SmartRouterLLMClient
from tta.observability.langfuse import init_langfuse, shutdown_langfuse

TTA_URL = os.getenv("TTA_URL", "http://localhost:8000")
OUTPUT_DIR = Path(os.getenv("TTA_EVAL_OUTPUT_DIR", "data/eval_smoke_output"))
REQUEST_TIMEOUT = float(os.getenv("TTA_SMOKE_HTTP_TIMEOUT", "150"))
RETRYABLE_STATUS_CODES = {429, 503}
DEFAULT_RETRY_DELAY_SECONDS = 2.0


async def _request_with_backoff(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    timeout_budget_seconds: float = 120.0,
    **kwargs: Any,
) -> httpx.Response:
    started = asyncio.get_running_loop().time()
    while True:
        resp = await client.request(method, url, **kwargs)
        if resp.status_code not in RETRYABLE_STATUS_CODES:
            resp.raise_for_status()
            return resp
        retry_after = _retry_after_seconds(resp)
        elapsed = asyncio.get_running_loop().time() - started
        if elapsed + retry_after > timeout_budget_seconds:
            raise TimeoutError(
                "Retry budget exceeded for "
                f"{method} {url} after HTTP {resp.status_code}"
            )
        print(
            "Retrying "
            f"{method} {url} after HTTP {resp.status_code} "
            f"in {retry_after:.1f}s"
        )
        await asyncio.sleep(retry_after)


def _retry_after_seconds(response: httpx.Response) -> float:
    header = response.headers.get("Retry-After", "").strip()
    if not header:
        return DEFAULT_RETRY_DELAY_SECONDS
    try:
        value = float(header)
    except ValueError:
        return DEFAULT_RETRY_DELAY_SECONDS
    return max(value, DEFAULT_RETRY_DELAY_SECONDS)


async def setup_player(handle_suffix: str = "") -> str:
    """Create anonymous player, accept consent, return auth token."""
    handle = f"eval-smoke{handle_suffix}"
    async with httpx.AsyncClient(
        base_url=TTA_URL,
        timeout=httpx.Timeout(REQUEST_TIMEOUT),
    ) as client:
        resp = await _request_with_backoff(
            client,
            "POST",
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
        token = resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await _request_with_backoff(
            client,
            "PATCH",
            "/api/v1/players/me/consent",
            headers=headers,
            json={
                "consent_version": "1.0",
                "consent_categories": {"core_gameplay": True, "llm_processing": True},
                "age_13_plus_confirmed": True,
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Consent patch failed: {resp.status_code} {resp.text}")
        return token


async def run_live_preflight(token: str) -> None:
    """Prove live stack can create a game and accept a real first turn."""
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        base_url=TTA_URL,
        timeout=httpx.Timeout(REQUEST_TIMEOUT),
        headers=headers,
    ) as client:
        create_resp = await _request_with_backoff(
            client,
            "POST",
            "/api/v1/games",
            json={
                "world_id": None,
                "preferences": {},
                "scenario_seed_id": "bus-stop-shimmer",
            },
        )
        create_data = create_resp.json()["data"]
        game_id = str(create_data["game_id"])
        intro = str(create_data.get("narrative_intro") or "").strip()
        if not intro:
            raise RuntimeError("Preflight create_game returned empty narrative_intro")
        print(f"Preflight game ready: {game_id}")

        turn_resp = await _request_with_backoff(
            client,
            "POST",
            f"/api/v1/games/{game_id}/turns",
            json={"input": "Look around and describe the immediate situation."},
        )
        if turn_resp.status_code != 202:
            raise RuntimeError(
                "Preflight turn submit failed: "
                f"{turn_resp.status_code} {turn_resp.text}"
            )
        turn_data = turn_resp.json()["data"]
        stream_url = str(turn_data.get("stream_url") or "").strip()
        if not stream_url:
            raise RuntimeError("Preflight turn submit returned empty stream_url")
        print(
            "Preflight turn accepted: "
            f"turn_id={turn_data['turn_id']} stream_url={stream_url}"
        )


async def main():
    print("=== TTA + FMR Eval Pipeline Smoke Test ===\n")

    settings = get_settings()
    init_langfuse(settings)
    llm: SmartRouterLLMClient | None = None
    try:
        preflight_token = await setup_player(f"-preflight-{uuid.uuid4().hex[:8]}")
        print(f"Preflight player ready. Token: {preflight_token[:30]}...")
        await run_live_preflight(preflight_token)

        token = await setup_player(f"-pipeline-{uuid.uuid4().hex[:8]}")
        print(f"Pipeline player ready. Token: {token[:30]}...")

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
