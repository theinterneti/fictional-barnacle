"""Unit tests for Consequence Propagation (S36, AC-36.01–36.08)."""

from __future__ import annotations

import pytest

from tta.simulation.consequence import (
    DefaultConsequencePropagator,
    MemoryConsequencePropagator,
    _decay_severity,
    _fidelity_description,
)
from tta.simulation.types import (
    ConsequenceRecord,
    PropagationResult,
    PropagationSource,
    WorldTime,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORLD_TIME = WorldTime(
    total_ticks=10,
    day_count=0,
    hour=9,
    minute=0,
    time_of_day_label="morning",
)

_UNIVERSE_ID = "uni-consequence-test"


def _make_source(
    severity: str = "major",
    faction_id: str | None = None,
    affected_entity_id: str | None = "entity-1",
    affected_entity_type: str | None = "npc",
    description: str = "A fight broke out at the tavern.",
) -> PropagationSource:
    return PropagationSource(
        source_event_id="evt-001",
        source_type="player_action",
        source_location_id="loc-tavern",
        original_severity=severity,  # type: ignore[arg-type]
        description=description,
        faction_id=faction_id,
        affected_entity_id=affected_entity_id,
        affected_entity_type=affected_entity_type,
    )


# ---------------------------------------------------------------------------
# AC-36.02 — ConsequencePropagator protocol conformance
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-36.02")
@pytest.mark.asyncio
async def test_propagate_returns_list_of_propagation_results() -> None:
    prop = DefaultConsequencePropagator()
    source = _make_source()
    results = await prop.propagate([source], _UNIVERSE_ID, _WORLD_TIME)
    assert isinstance(results, list)
    assert all(isinstance(r, PropagationResult) for r in results)


@pytest.mark.spec("AC-36.02")
@pytest.mark.asyncio
async def test_memory_propagator_returns_preset() -> None:
    preset = [PropagationResult(source_event_id="evt-preset")]
    prop = MemoryConsequencePropagator(preset=preset)
    results = await prop.propagate([], _UNIVERSE_ID, _WORLD_TIME)
    assert results is preset


@pytest.mark.spec("AC-36.02")
@pytest.mark.asyncio
async def test_propagate_empty_sources_returns_empty_list() -> None:
    prop = DefaultConsequencePropagator()
    results = await prop.propagate([], _UNIVERSE_ID, _WORLD_TIME)
    assert results == []


@pytest.mark.spec("AC-36.02")
@pytest.mark.asyncio
async def test_propagate_one_result_per_source_event() -> None:
    prop = DefaultConsequencePropagator()
    sources = [_make_source("major"), _make_source("notable")]
    results = await prop.propagate(sources, _UNIVERSE_ID, _WORLD_TIME)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# AC-36.02 — Notable event propagates to correct depths only
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-36.02")
@pytest.mark.asyncio
async def test_hop0_record_created_when_affected_entity_id_set() -> None:
    prop = DefaultConsequencePropagator()
    source = _make_source(affected_entity_id="entity-hop0")
    results = await prop.propagate([source], _UNIVERSE_ID, _WORLD_TIME)
    assert results
    hop0_records = [r for r in results[0].records if r.hop_distance == 0]
    assert len(hop0_records) == 1
    assert hop0_records[0].affected_entity_id == "entity-hop0"


@pytest.mark.spec("AC-36.02")
@pytest.mark.asyncio
async def test_hop0_record_fields_match_source() -> None:
    prop = DefaultConsequencePropagator()
    source = _make_source(
        severity="major",
        affected_entity_id="entity-fields",
        description="Brawl erupted.",
    )
    results = await prop.propagate([source], _UNIVERSE_ID, _WORLD_TIME)
    hop0 = results[0].records[0]
    assert hop0.source_event_id == "evt-001"
    assert hop0.hop_distance == 0
    assert hop0.original_severity == "major"
    assert hop0.propagated_severity == "major"
    assert isinstance(hop0, ConsequenceRecord)


@pytest.mark.spec("AC-36.02")
@pytest.mark.asyncio
async def test_no_hop0_when_no_affected_entity_id() -> None:
    prop = DefaultConsequencePropagator()
    source = _make_source(affected_entity_id=None)
    results = await prop.propagate([source], _UNIVERSE_ID, _WORLD_TIME)
    assert results[0].records == []


# ---------------------------------------------------------------------------
# AC-36.01 — Minor events do not propagate
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-36.01")
@pytest.mark.asyncio
async def test_minor_severity_is_filtered() -> None:
    prop = DefaultConsequencePropagator()
    source = _make_source(severity="minor")
    results = await prop.propagate([source], _UNIVERSE_ID, _WORLD_TIME)
    assert results[0].records == []
    assert results[0].faction_records == []
    assert results[0].total_records == 0
    assert results[0].skipped_minor == 1


# ---------------------------------------------------------------------------
# AC-36.03 — Critical event propagates with correct severity decay
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-36.03")
def test_decay_critical_hop0() -> None:
    assert _decay_severity("critical", 0) == "critical"


@pytest.mark.spec("AC-36.03")
def test_decay_critical_hop1() -> None:
    assert _decay_severity("critical", 1) == "major"


@pytest.mark.spec("AC-36.03")
def test_decay_critical_hop2() -> None:
    assert _decay_severity("critical", 2) == "notable"


@pytest.mark.spec("AC-36.03")
def test_decay_critical_hop3() -> None:
    assert _decay_severity("critical", 3) == "minor"


@pytest.mark.spec("AC-36.03")
def test_decay_critical_hop4_filtered() -> None:
    assert _decay_severity("critical", 4) is None


@pytest.mark.spec("AC-36.03")
def test_decay_major_hop1() -> None:
    assert _decay_severity("major", 1) == "notable"


@pytest.mark.spec("AC-36.03")
def test_decay_major_hop2() -> None:
    assert _decay_severity("major", 2) == "minor"


@pytest.mark.spec("AC-36.03")
def test_decay_major_hop3_filtered() -> None:
    assert _decay_severity("major", 3) is None


@pytest.mark.spec("AC-36.03")
def test_decay_notable_hop1() -> None:
    assert _decay_severity("notable", 1) == "minor"


@pytest.mark.spec("AC-36.03")
def test_decay_notable_hop2_filtered() -> None:
    assert _decay_severity("notable", 2) is None


@pytest.mark.spec("AC-36.03")
def test_decay_minor_hop1_filtered() -> None:
    # minor has empty decay path — any hop > 0 returns None
    assert _decay_severity("minor", 1) is None


# ---------------------------------------------------------------------------
# AC-36.04 — Faction members receive hop-1 record regardless of distance
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-36.04")
@pytest.mark.asyncio
async def test_faction_shortcut_creates_hop1_record() -> None:
    prop = DefaultConsequencePropagator(max_depth=3)
    source = _make_source(severity="major", faction_id="guild-thieves")
    results = await prop.propagate([source], _UNIVERSE_ID, _WORLD_TIME)
    faction_recs = results[0].faction_records
    assert len(faction_recs) == 1
    assert faction_recs[0].affected_entity_id == "faction:guild-thieves"
    assert faction_recs[0].affected_entity_type == "faction"
    assert faction_recs[0].hop_distance == 1


@pytest.mark.spec("AC-36.04")
@pytest.mark.asyncio
async def test_no_faction_record_when_no_faction_id() -> None:
    prop = DefaultConsequencePropagator(max_depth=3)
    source = _make_source(severity="major", faction_id=None)
    results = await prop.propagate([source], _UNIVERSE_ID, _WORLD_TIME)
    assert results[0].faction_records == []


# ---------------------------------------------------------------------------
# AC-36.02 — Notable event propagates to correct depths only
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-36.02")
@pytest.mark.asyncio
async def test_propagation_depth_reached_does_not_exceed_max_depth() -> None:
    prop = DefaultConsequencePropagator(max_depth=2)
    source = _make_source(severity="critical", faction_id="faction-x")
    results = await prop.propagate([source], _UNIVERSE_ID, _WORLD_TIME)
    assert results[0].propagation_depth_reached <= 2


@pytest.mark.spec("AC-36.02")
@pytest.mark.asyncio
async def test_faction_record_respects_max_depth_1() -> None:
    # max_depth=1 → faction shortcut should still fire (hop 1 == max_depth)
    prop = DefaultConsequencePropagator(max_depth=1)
    source = _make_source(severity="critical", faction_id="faction-y")
    results = await prop.propagate([source], _UNIVERSE_ID, _WORLD_TIME)
    assert results[0].propagation_depth_reached <= 1


# ---------------------------------------------------------------------------
# AC-36.05 — Hop-2 description falls back to template on LLM failure
# ---------------------------------------------------------------------------

_SHORT_DESC = "Brawl erupted."
_LONG_DESC = "A" * 90  # > 80 chars


@pytest.mark.spec("AC-36.05")
def test_fidelity_hop0_verbatim() -> None:
    assert _fidelity_description(_SHORT_DESC, 0) == _SHORT_DESC


@pytest.mark.spec("AC-36.05")
def test_fidelity_hop1_verbatim() -> None:
    assert _fidelity_description(_SHORT_DESC, 1) == _SHORT_DESC


@pytest.mark.spec("AC-36.05")
def test_fidelity_hop2_truncates_long_description() -> None:
    result = _fidelity_description(_LONG_DESC, 2)
    assert result.endswith("…")
    # "Word has reached here that " (27 chars) + 60 chars + "…" = 88 max
    assert len(result) <= 88


@pytest.mark.spec("AC-36.05")
def test_fidelity_hop2_verbatim_when_short() -> None:
    result = _fidelity_description(_SHORT_DESC, 2)
    # short descriptions are not truncated
    assert result == _SHORT_DESC


@pytest.mark.spec("AC-36.05")
def test_fidelity_hop3_uses_template() -> None:
    result = _fidelity_description(_SHORT_DESC, 3)
    assert result.startswith("There are vague rumors of ")


@pytest.mark.spec("AC-36.05")
def test_fidelity_hop4_uses_template() -> None:
    result = _fidelity_description(_SHORT_DESC, 4)
    assert result.startswith("There are vague rumors of ")


# ---------------------------------------------------------------------------
# AC-36.07 — Budget exceeded returns partial result without error
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-36.07")
def test_max_depth_zero_treated_as_one() -> None:
    prop = DefaultConsequencePropagator(max_depth=0)
    assert prop.max_depth == 1


@pytest.mark.spec("AC-36.07")
@pytest.mark.asyncio
async def test_max_depth_zero_still_propagates_to_hop1() -> None:
    prop = DefaultConsequencePropagator(max_depth=0)
    source = _make_source(severity="critical", faction_id="faction-z")
    results = await prop.propagate([source], _UNIVERSE_ID, _WORLD_TIME)
    # With effective max_depth=1, faction shortcut fires at hop 1
    assert results[0].propagation_depth_reached <= 1
    assert len(results[0].faction_records) == 1
