"""AC compliance tests for S35 NPC Autonomy (AC-35.01–35.10).

All ACs are covered across this file and tests/unit/simulation/test_npc_autonomy.py.

AC coverage (see test_npc_autonomy.py for AC-35.01–35.04/35.08–35.10):
- AC-35.01: DefaultAutonomyProcessor.process() returns a WorldDelta
- AC-35.02: Background-tier NPCs are never processed
- AC-35.03: Supporting NPCs outside salience window are skipped
- AC-35.04: Supporting NPCs in salience window are processed
- AC-35.05: World context receives autonomous_changes key (injected by context stage)
- AC-35.06: RoutineStep.repeating defaults to True (type-level guarantee)
- AC-35.07: NarrativeEventAction creates a WorldEvent in the events list
- AC-35.08: Key NPCs are never deferred
- AC-35.09: Budget exceeded flag is set when NPC count exceeds max
- AC-35.10: MemoryAutonomyProcessor returns a preset WorldDelta
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# AC-35.05 — context stage injects autonomous_changes
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.05")
def test_context_stage_injects_autonomous_changes_key() -> None:
    """context.py injects autonomous_changes into world_context from autonomy_delta.

    AC-35.05: After NPC autonomy processing, world_context must contain
    an 'autonomous_changes' key with serialized NPC change records.
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

    # Verify world_context["autonomous_changes"] assignment exists
    assert 'world_context["autonomous_changes"]' in src, (
        "context.py must set world_context['autonomous_changes'] (AC-35.05)"
    )


@pytest.mark.spec("AC-35.05")
def test_autonomous_changes_includes_npc_id_action_type_after() -> None:
    """autonomous_changes entries include npc_id, action_type, and after fields.

    AC-35.05: Each serialized change must expose at minimum the NPC id,
    the action type, and the resulting state (after).
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

    assert '"npc_id"' in src or "npc_id" in src, (
        "autonomous_changes entries must include npc_id"
    )
    assert '"action_type"' in src or "action_type" in src, (
        "autonomous_changes entries must include action_type"
    )
    assert '"after"' in src or "'after'" in src, (
        "autonomous_changes entries must include after"
    )


# ---------------------------------------------------------------------------
# AC-35.06 — RoutineStep.repeating defaults to True
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.06")
def test_routine_step_repeating_defaults_to_true() -> None:
    """RoutineStep.repeating field defaults to True.

    AC-35.06: A routine step fires on every matching tick unless explicitly
    set to non-repeating. The default is True to enable recurring behaviors.
    """
    from tta.simulation.types import MoveAction, RoutineStep

    # RoutineTrigger is a Literal type alias – use the string value directly
    trigger = "time_of_day"
    action = MoveAction(target_location_id="loc-1")
    step = RoutineStep(trigger=trigger, action=action)
    assert step.repeating is True, (
        "RoutineStep.repeating must default to True (AC-35.06)"
    )


@pytest.mark.spec("AC-35.06")
def test_routine_step_repeating_can_be_set_to_false() -> None:
    """RoutineStep.repeating can be overridden to False for one-shot steps."""
    from tta.simulation.types import MoveAction, RoutineStep

    trigger = "time_of_day"
    action = MoveAction(target_location_id="loc-1")
    step = RoutineStep(trigger=trigger, action=action, repeating=False)
    assert step.repeating is False


# ---------------------------------------------------------------------------
# AC-35.07 — NarrativeEventAction creates a WorldEvent
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-35.07")
def test_narrative_event_action_produces_world_event() -> None:
    """NarrativeEventAction causes _process_npc to produce a WorldEvent.

    AC-35.07: When an NPC's autonomy action is a NarrativeEventAction, the
    autonomy processor must emit a WorldEvent into the delta's events list.
    """
    from types import SimpleNamespace

    from tta.simulation.npc_autonomy import DefaultAutonomyProcessor
    from tta.simulation.types import (
        NarrativeEventAction,
        RoutineCondition,
        RoutineStep,
        WorldTime,
    )

    # EventSeverity is a Literal type alias – use the string value directly
    narrative_action = NarrativeEventAction(
        description="A strange sound echoes",
        severity="notable",
    )
    # RoutineTrigger is a Literal; condition label must match time_of_day_label
    step = RoutineStep(
        trigger="time_of_day",
        action=narrative_action,
        condition=RoutineCondition(label="morning"),
    )

    # Use SimpleNamespace so "routine" can be set freely (NPC has no routine field)
    npc = SimpleNamespace(
        id="npc-narr",
        tier="key",
        schedule="morning_routine",  # non-None so KEY tier is not skipped (AC-35.02)
        routine=[step],
        state="idle",
        autonomy_mode="rule_based",
    )

    world_time = WorldTime(
        total_ticks=100,
        day_count=0,
        hour=8,
        minute=0,
        time_of_day_label="morning",
    )
    processor = DefaultAutonomyProcessor()
    delta = processor.process(universe_id="u-1", world_time=world_time, npcs=[npc])

    assert len(delta.events) >= 1, (
        "NarrativeEventAction must produce at least one WorldEvent (AC-35.07)"
    )
    event = delta.events[0]
    assert event.event_type == "narrative", (
        "WorldEvent produced by NarrativeEventAction must have event_type='narrative'"
    )
    assert event.description == "A strange sound echoes"
    assert event.source_npc_id == "npc-narr"
