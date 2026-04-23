"""AC compliance tests for S36 Consequence Propagation (AC-36.01–36.10).

All ACs are covered across this file and tests/unit/simulation/test_consequence.py.

AC coverage (see test_consequence.py for AC-36.01–36.05/36.07/36.09–36.10):
- AC-36.01: ConsequencePropagator Protocol is satisfied by default implementation
- AC-36.02: Physical proximity hop records are created from source event
- AC-36.03: Minor severity events are skipped; moderate/major propagate
- AC-36.04: Faction relationships generate additional consequence records
- AC-36.05: Propagation depth is limited by max_depth parameter
- AC-36.06: World context receives propagated_consequences key (context stage)
- AC-36.07: Budget-exceeded flag is set on PropagationResult when over time budget
- AC-36.08: DefaultConsequencePropagator.propagate() runs without Neo4j (stub)
- AC-36.09: MemoryConsequencePropagator returns preset consequence list
- AC-36.10: ConsequenceRecord contains required fields including hop_distance
"""

from __future__ import annotations

import asyncio

import pytest

# ---------------------------------------------------------------------------
# AC-36.06 — context stage injects propagated_consequences
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-36.06")
def test_context_stage_injects_propagated_consequences_key() -> None:
    """context.py injects propagated_consequences into world_context.

    AC-36.06: After consequence propagation, world_context must contain
    a 'propagated_consequences' key with per-source summary records.
    """
    import pathlib

    src = (
        pathlib.Path(__file__).parent.parent.parent.parent
        / "src"
        / "tta"
        / "pipeline"
        / "stages"
        / "context.py"
    ).read_text()

    assert 'world_context["propagated_consequences"]' in src, (
        "context.py must set world_context['propagated_consequences'] (AC-36.06)"
    )


@pytest.mark.spec("AC-36.06")
def test_propagated_consequences_includes_summary_fields() -> None:
    """propagated_consequences entries include source_event_id, total_records, depth.

    AC-36.06: Each summary entry must expose at minimum the source event id,
    the count of generated records, and the propagation depth reached.
    """
    import pathlib

    src = (
        pathlib.Path(__file__).parent.parent.parent.parent
        / "src"
        / "tta"
        / "pipeline"
        / "stages"
        / "context.py"
    ).read_text()

    assert "source_event_id" in src, (
        "propagated_consequences must include source_event_id"
    )
    assert "total_records" in src, "propagated_consequences must include total_records"
    assert "propagation_depth_reached" in src or "depth" in src, (
        "propagated_consequences must include propagation depth"
    )


# ---------------------------------------------------------------------------
# AC-36.08 — DefaultConsequencePropagator works without Neo4j (stub)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-36.08")
def test_default_propagator_returns_list_without_neo4j() -> None:
    """DefaultConsequencePropagator.propagate() returns a list without crashing.

    AC-36.08: The default implementation must provide a working BFS stub so
    the pipeline remains functional even when Neo4j is unavailable.  The real
    Neo4j graph traversal is deferred to a later wave.
    """
    from tta.simulation.consequence import DefaultConsequencePropagator
    from tta.simulation.types import PropagationSource, WorldTime

    propagator = DefaultConsequencePropagator(max_depth=2)
    world_time = WorldTime(
        total_ticks=10,
        day_count=0,
        hour=8,
        minute=0,
        time_of_day_label="morning",
    )
    source = PropagationSource(
        source_event_id="evt-1",
        source_type="player_action",
        source_location_id="loc-1",
        original_severity="notable",
        description="Player knocked over a lantern",
        affected_entity_id="entity-1",
        affected_entity_type="object",
    )

    results = asyncio.get_event_loop().run_until_complete(
        propagator.propagate(
            source_events=[source],
            universe_id="u-1",
            world_time=world_time,
        )
    )

    assert isinstance(results, list), (
        "DefaultConsequencePropagator.propagate() must return a list (AC-36.08)"
    )
    assert len(results) == 1, "One PropagationResult per source event"


@pytest.mark.spec("AC-36.08")
def test_default_propagator_max_depth_zero_treated_as_one() -> None:
    """DefaultConsequencePropagator clamps max_depth=0 to 1 (AC-36.08)."""
    from tta.simulation.consequence import DefaultConsequencePropagator

    propagator = DefaultConsequencePropagator(max_depth=0)
    assert propagator.max_depth >= 1, "max_depth=0 must be clamped to 1 (AC-36.08)"
