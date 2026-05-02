"""Integration tests — Neo4j query latency for S13/S12 acceptance criteria.

ACs covered:
  AC-13.04 — get_location_context(depth=1) p95 < 50 ms on 1 000-node world
  AC-13.05 — validate_movement p95 < 10 ms on 1 000-node world
  AC-13.06 — get_location_context(depth=2) p95 < 200 ms on 1 000-node world
  AC-12.08 — two-hop neighbour query p95 < 200 ms (same query as AC-13.06)
"""

from __future__ import annotations

import statistics
import time
import uuid
from typing import Any

import pytest

from tta.world.neo4j_service import Neo4jWorldService

pytestmark = pytest.mark.integration

# Must match _LARGE_WORLD_SESSION_ID in tests/integration/conftest.py exactly.
LARGE_SESSION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Location IDs from world_large.cypher: large-loc-{region}-{index}
_START_LOC = "large-loc-0-0"
_NEXT_LOC = "large-loc-0-1"

_SAMPLES = 20


def _p95(latencies: list[float]) -> float:
    """Return the 95th-percentile value from *latencies* (in seconds)."""
    # statistics.quantiles(n=20) returns 19 cut points; index 18 = 95th pct.
    return statistics.quantiles(latencies, n=20)[18]


@pytest.mark.spec("AC-13.04")
class TestAC1304LocationContextLatency:
    """get_location_context(depth=1) p95 must be < 50 ms on the large world."""

    @pytest.mark.asyncio
    async def test_p95_under_50ms(self, neo4j_large_world: Any) -> None:
        service = Neo4jWorldService(driver=neo4j_large_world)
        latencies: list[float] = []

        for _ in range(_SAMPLES):
            t0 = time.perf_counter()
            await service.get_location_context(LARGE_SESSION_ID, _START_LOC, depth=1)
            latencies.append(time.perf_counter() - t0)

        p95_ms = _p95(latencies) * 1000
        assert p95_ms < 50, (
            f"AC-13.04 FAIL: get_location_context(depth=1) p95={p95_ms:.1f} ms >= 50 ms"
        )


@pytest.mark.spec("AC-13.05")
class TestAC1305MovementValidationLatency:
    """validate_movement p95 must be < 10 ms on the large world."""

    @pytest.mark.asyncio
    async def test_p95_under_10ms(self, neo4j_large_world: Any) -> None:
        service = Neo4jWorldService(driver=neo4j_large_world)
        latencies: list[float] = []

        for _ in range(_SAMPLES):
            t0 = time.perf_counter()
            await service.validate_movement(LARGE_SESSION_ID, _START_LOC, _NEXT_LOC)
            latencies.append(time.perf_counter() - t0)

        p95_ms = _p95(latencies) * 1000
        assert p95_ms < 10, (
            f"AC-13.05 FAIL: validate_movement p95={p95_ms:.1f} ms >= 10 ms"
        )


@pytest.mark.spec("AC-13.06")
@pytest.mark.spec("AC-12.08")
class TestAC1306TwoHopLatency:
    """get_location_context(depth=2) p95 must be < 200 ms on the large world.

    Covers both AC-13.06 (world-graph two-hop query) and AC-12.08
    (persistence layer two-hop neighbour retrieval).
    """

    @pytest.mark.asyncio
    async def test_p95_under_200ms(self, neo4j_large_world: Any) -> None:
        service = Neo4jWorldService(driver=neo4j_large_world)
        latencies: list[float] = []

        for _ in range(_SAMPLES):
            t0 = time.perf_counter()
            await service.get_location_context(LARGE_SESSION_ID, _START_LOC, depth=2)
            latencies.append(time.perf_counter() - t0)

        p95_ms = _p95(latencies) * 1000
        assert p95_ms < 200, (
            f"AC-13.06/AC-12.08 FAIL: get_location_context(depth=2) "
            f"p95={p95_ms:.1f} ms >= 200 ms"
        )
