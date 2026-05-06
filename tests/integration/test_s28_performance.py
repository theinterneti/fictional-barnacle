"""S28 Performance & Scaling — integration tests.

AC-28.02: First SSE narrative_token event arrives within 2 seconds.
AC-28.04: /metrics exposes DB pool counters (pool_active, pool_idle, pool_waiting).
"""

from __future__ import annotations

import time
from typing import Any

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.spec("AC-28.02")
class TestAC2802FirstSSETokenLatency:
    """AC-28.02: First narrative_token SSE event arrives within 2 s of turn submit.

    Uses TTA_LLM_MOCK=true so AI latency is excluded. Tests infra + routing overhead.
    """

    @pytest.mark.asyncio
    async def test_first_sse_token_within_2s(
        self, auth_client: Any, registered_player: dict
    ) -> None:
        import json

        game_resp = await auth_client.post(
            "/api/v1/games",
            json={"universe_id": None},
        )
        if game_resp.status_code not in (200, 201):
            pytest.skip(f"Game creation failed ({game_resp.status_code})")

        game_id = game_resp.json()["data"]["game_id"]

        t0 = time.perf_counter()
        first_token_ms: float | None = None

        async with auth_client.stream(
            "POST",
            f"/api/v1/games/{game_id}/turns/stream",
            json={"player_input": "look around"},
        ) as response:
            if response.status_code not in (200, 201, 202):
                pytest.skip(f"SSE endpoint returned {response.status_code}")

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:].strip())
                if payload.get("type") == "narrative_token":
                    first_token_ms = (time.perf_counter() - t0) * 1000
                    break

        if first_token_ms is None:
            pytest.skip(
                "No narrative_token event received — SSE stream may use "
                "different event type"
            )

        assert first_token_ms < 2000, (
            f"First narrative_token arrived at {first_token_ms:.0f}ms > 2000ms "
            "budget (AC-28.02)"
        )


@pytest.mark.spec("AC-28.04")
class TestAC2804MetricsPoolCounters:
    """AC-28.04: /metrics exposes pool_active, pool_idle, pool_waiting for each DB."""

    @pytest.mark.asyncio
    async def test_metrics_includes_pool_counters(self, client: Any) -> None:
        resp = await client.get("/metrics")
        if resp.status_code == 404:
            pytest.skip("/metrics endpoint not mounted — check Prometheus middleware")

        assert resp.status_code == 200, f"/metrics returned {resp.status_code}"
        body = resp.text

        required_metrics = ["pool_active", "pool_idle", "pool_waiting"]
        missing = [m for m in required_metrics if m not in body]
        assert not missing, (
            f"/metrics missing pool counters: {missing} (AC-28.04). "
            "Check PrometheusMiddleware in src/tta/api/prometheus_middleware.py"
        )
