"""Performance benchmarks for S05 consequence operations (AC-5.6).

NFR targets (S05 L328-336):
- evaluate() < 300ms for 30 active chains
- calculate_divergence() < 100ms
- prune_chains() < 100ms
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest

from tta.choices.consequence_service import InMemoryConsequenceService
from tta.models.choice import ImpactLevel
from tta.models.consequence import (
    MAX_ACTIVE_CHAINS,
    ConsequenceEntry,
    ConsequenceTimescale,
    ConsequenceVisibility,
)

SID = uuid4()
WARMUP = 3
ITERATIONS = 10


async def _populate_service(
    svc: InMemoryConsequenceService,
    n_chains: int = MAX_ACTIVE_CHAINS,
    entries_per_chain: int = 4,
) -> None:
    for i in range(n_chains):
        chain_id = uuid4()
        entries = [
            ConsequenceEntry(
                chain_id=chain_id,
                trigger=f"trigger-{i}-{j}",
                effect=f"effect-{i}-{j}",
                timescale=ConsequenceTimescale.SHORT_TERM,
                visibility=ConsequenceVisibility.VISIBLE,
            )
            for j in range(entries_per_chain)
        ]
        await svc.create_chain(
            session_id=SID,
            root_trigger=f"trigger-{i}",
            impact_level=ImpactLevel.CONSEQUENTIAL,
            entries=entries,
        )


@pytest.mark.asyncio
async def test_evaluate_30_chains_under_300ms() -> None:
    """AC-5.6: evaluate() < 300ms for 30 active chains."""
    svc = InMemoryConsequenceService()
    await _populate_service(svc, n_chains=30)

    # Warmup
    for _ in range(WARMUP):
        await svc.evaluate(SID, 5, "test input")

    # Measure
    times: list[float] = []
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        await svc.evaluate(SID, 5, "the hero opens the chest")
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

    median = sorted(times)[ITERATIONS // 2]
    assert median < 300, f"evaluate() median {median:.1f}ms exceeds 300ms"


@pytest.mark.asyncio
async def test_calculate_divergence_under_100ms() -> None:
    """AC-5.6: calculate_divergence() < 100ms."""
    svc = InMemoryConsequenceService()
    await _populate_service(svc, n_chains=30)
    await svc.add_anchor(SID, "reach the temple", target_turn=20)

    for _ in range(WARMUP):
        await svc.calculate_divergence(SID, 10)

    times: list[float] = []
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        await svc.calculate_divergence(SID, 10)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

    median = sorted(times)[ITERATIONS // 2]
    assert median < 100, f"calculate_divergence() median {median:.1f}ms exceeds 100ms"


@pytest.mark.asyncio
async def test_prune_chains_under_100ms() -> None:
    """AC-5.6: prune_chains() < 100ms."""
    svc = InMemoryConsequenceService()
    await _populate_service(svc, n_chains=30)
    # Mark all chains as dormant
    for chain in svc._chains.get(SID, []):
        chain.last_active_turn = 0

    for _ in range(WARMUP):
        await svc.prune_chains(SID, 60)
        # Re-populate after prune
        svc._chains[SID] = []
        await _populate_service(svc, n_chains=30)
        for chain in svc._chains.get(SID, []):
            chain.last_active_turn = 0

    times: list[float] = []
    for _ in range(ITERATIONS):
        svc._chains[SID] = []
        await _populate_service(svc, n_chains=30)
        for chain in svc._chains.get(SID, []):
            chain.last_active_turn = 0
        start = time.perf_counter()
        await svc.prune_chains(SID, 60)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

    median = sorted(times)[ITERATIONS // 2]
    assert median < 100, f"prune_chains() median {median:.1f}ms exceeds 100ms"
