"""Unit tests for NPC Autonomy (S35, AC-35.01–35.10)."""

from __future__ import annotations

import pytest

from tta.simulation.npc_autonomy import (
    DefaultAutonomyProcessor,
    MemoryAutonomyProcessor,
)
from tta.simulation.types import (
    NPCStateChange,
    WorldDelta,
    WorldEvent,
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

_UNIVERSE_ID = "uni-test"


def _make_npc(
    npc_id: str,
    tier: str,
    schedule: str | None = "morning",
    state: str = "idle",
) -> dict:
    return {
        "id": npc_id,
        "tier": tier,
        "schedule": schedule,
        "state": state,
    }


# ---------------------------------------------------------------------------
# MemoryAutonomyProcessor (fixture / protocol conformance)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.01")
def test_memory_processor_returns_world_delta() -> None:
    proc = MemoryAutonomyProcessor()
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [])
    assert isinstance(delta, WorldDelta)


@pytest.mark.spec("AC-35.01")
def test_memory_processor_preset_is_returned() -> None:
    preset = WorldDelta(
        from_tick=0,
        to_tick=1,
        world_time=_WORLD_TIME,
        was_capped=False,
    )
    proc = MemoryAutonomyProcessor(preset=preset)
    result = proc.process(_UNIVERSE_ID, _WORLD_TIME, [])
    assert result is preset


# ---------------------------------------------------------------------------
# AC-35.01 — process() returns WorldDelta
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.01")
def test_default_processor_returns_world_delta() -> None:
    proc = DefaultAutonomyProcessor()
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [])
    assert isinstance(delta, WorldDelta)


@pytest.mark.spec("AC-35.01")
def test_empty_npcs_returns_empty_delta() -> None:
    proc = DefaultAutonomyProcessor()
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [])
    assert delta.changes == []
    assert delta.events == []
    assert delta.deferred_npcs == []


# ---------------------------------------------------------------------------
# AC-35.02 — KEY NPCs with a schedule are always processed
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.02")
def test_key_npc_with_schedule_is_processed() -> None:
    proc = DefaultAutonomyProcessor()
    npc = _make_npc("npc-key", "key", schedule="morning")
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [npc])
    # KEY NPCs with a schedule produce at least one state change
    processed_ids = {c.npc_id for c in delta.changes}
    assert "npc-key" in processed_ids


@pytest.mark.spec("AC-35.02")
def test_key_npc_without_schedule_is_skipped() -> None:
    proc = DefaultAutonomyProcessor()
    npc = _make_npc("npc-key-no-sched", "key", schedule=None)
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [npc])
    processed_ids = {c.npc_id for c in delta.changes}
    assert "npc-key-no-sched" not in processed_ids


# ---------------------------------------------------------------------------
# AC-35.03 — SUPPORTING NPCs with a schedule and in the salience window
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.03")
def test_supporting_npc_in_salience_window_is_processed() -> None:
    proc = DefaultAutonomyProcessor()
    # schedule="morning", world_time.hour=9 → in salience window
    npc = _make_npc("npc-sup", "supporting", schedule="morning")
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [npc])
    processed_ids = {c.npc_id for c in delta.changes}
    assert "npc-sup" in processed_ids


@pytest.mark.spec("AC-35.03")
def test_supporting_npc_outside_salience_window_is_skipped() -> None:
    proc = DefaultAutonomyProcessor()
    # schedule="night" but world_time.hour=9 → outside salience window
    npc = _make_npc("npc-sup-night", "supporting", schedule="night")
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [npc])
    processed_ids = {c.npc_id for c in delta.changes}
    assert "npc-sup-night" not in processed_ids


# ---------------------------------------------------------------------------
# AC-35.04 — SUPPORTING NPCs with no schedule are skipped
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.04")
def test_supporting_npc_no_schedule_skipped() -> None:
    proc = DefaultAutonomyProcessor()
    npc = _make_npc("npc-sup-no-sched", "supporting", schedule=None)
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [npc])
    processed_ids = {c.npc_id for c in delta.changes}
    assert "npc-sup-no-sched" not in processed_ids


# ---------------------------------------------------------------------------
# AC-35.05 — BACKGROUND NPCs are never processed
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.05")
def test_background_npc_never_processed() -> None:
    proc = DefaultAutonomyProcessor()
    npc = _make_npc("npc-bg", "background", schedule="morning")
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [npc])
    processed_ids = {c.npc_id for c in delta.changes}
    assert "npc-bg" not in processed_ids


# ---------------------------------------------------------------------------
# AC-35.06 — KEY NPCs are NEVER deferred, regardless of budget
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.06")
def test_key_npc_never_deferred() -> None:
    # budget_ms=0 forces budget-exceeded path immediately
    proc = DefaultAutonomyProcessor(budget_ms=0)
    npc = _make_npc("npc-key-budget", "key", schedule="morning")
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [npc])
    assert "npc-key-budget" not in delta.deferred_npcs


# ---------------------------------------------------------------------------
# AC-35.07 — SUPPORTING NPCs deferred when budget exceeded
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.07")
def test_supporting_npc_deferred_when_budget_zero() -> None:
    proc = DefaultAutonomyProcessor(budget_ms=0)
    npc = _make_npc("npc-sup-defer", "supporting", schedule="morning")
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [npc])
    assert "npc-sup-defer" in delta.deferred_npcs


# ---------------------------------------------------------------------------
# AC-35.08 — LLM batch is attempted for KEY-tier NPCs when llm is None
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.08", "AC-35.09")
def test_no_llm_falls_back_to_rule_based() -> None:
    # llm=None triggers fallback path (AC-35.09)
    proc = DefaultAutonomyProcessor(llm=None)
    npc = _make_npc("npc-key-llm", "key", schedule="morning")
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [npc])
    # Still produces a WorldDelta without error
    assert isinstance(delta, WorldDelta)
    assert "npc-key-llm" not in delta.deferred_npcs


# ---------------------------------------------------------------------------
# AC-35.10 — Unmatched triggers (world_event, player_visited) are in the set
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.10")
def test_world_event_trigger_is_unmatched() -> None:
    from tta.simulation.npc_autonomy import _UNMATCHED_TRIGGERS

    assert "world_event" in _UNMATCHED_TRIGGERS


@pytest.mark.spec("AC-35.10")
def test_player_visited_trigger_is_unmatched() -> None:
    from tta.simulation.npc_autonomy import _UNMATCHED_TRIGGERS

    assert "player_visited" in _UNMATCHED_TRIGGERS


@pytest.mark.spec("AC-35.10")
def test_active_triggers_not_in_unmatched() -> None:
    from tta.simulation.npc_autonomy import _UNMATCHED_TRIGGERS

    assert "time_of_day" not in _UNMATCHED_TRIGGERS
    assert "tick_elapsed" not in _UNMATCHED_TRIGGERS


# ---------------------------------------------------------------------------
# WorldDelta field invariants
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.01")
def test_world_delta_changes_are_npc_state_changes() -> None:
    proc = DefaultAutonomyProcessor()
    npc = _make_npc("npc-chk", "key", schedule="morning")
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [npc])
    for c in delta.changes:
        assert isinstance(c, NPCStateChange)
        assert isinstance(c.npc_id, str)
        assert isinstance(c.action_type, str)


@pytest.mark.spec("AC-35.01")
def test_world_delta_events_are_world_events() -> None:
    proc = DefaultAutonomyProcessor()
    npc = _make_npc("npc-ev", "key", schedule="morning")
    delta = proc.process(_UNIVERSE_ID, _WORLD_TIME, [npc])
    for e in delta.events:
        assert isinstance(e, WorldEvent)
        assert isinstance(e.event_id, str)
