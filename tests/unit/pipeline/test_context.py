"""Tests for the context pipeline stage."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tta.models.turn import ParsedIntent, TurnState
from tta.models.world import (
    TemplateConnection,
    TemplateItem,
    TemplateLocation,
    TemplateMetadata,
    TemplateNPC,
    TemplateRegion,
    WorldEvent,
    WorldSeed,
    WorldTemplate,
)
from tta.pipeline.stages.context import context_stage
from tta.pipeline.types import PipelineDeps
from tta.world.memory_service import InMemoryWorldService


def _make_state(**overrides: object) -> TurnState:
    defaults: dict = {
        "session_id": uuid4(),
        "turn_number": 1,
        "player_input": "look around",
        "game_state": {"location": "tavern", "hp": 100},
    }
    defaults.update(overrides)
    return TurnState(**defaults)


def _make_deps() -> PipelineDeps:
    """Deps with a failing world mock — triggers fallback."""
    world = AsyncMock()
    world.get_player_location.side_effect = ValueError("no world data")
    world.get_recent_events.return_value = []
    return PipelineDeps(
        llm=AsyncMock(),
        world=world,
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=AsyncMock(),
        safety_pre_gen=AsyncMock(),
        safety_post_gen=AsyncMock(),
    )


def _make_seed() -> WorldSeed:
    """Minimal world seed for integration tests."""
    meta = TemplateMetadata(
        template_key="test",
        display_name="Test World",
    )
    return WorldSeed(
        template=WorldTemplate(
            metadata=meta,
            regions=[
                TemplateRegion(
                    key="town",
                    archetype="A small town",
                ),
            ],
            locations=[
                TemplateLocation(
                    key="tavern",
                    region_key="town",
                    type="interior",
                    archetype="A dimly lit tavern",
                    is_starting_location=True,
                ),
                TemplateLocation(
                    key="market",
                    region_key="town",
                    type="exterior",
                    archetype="A bustling market",
                ),
            ],
            connections=[
                TemplateConnection(
                    from_key="tavern",
                    to_key="market",
                    direction="e",
                    bidirectional=True,
                ),
            ],
            npcs=[
                TemplateNPC(
                    key="barkeep",
                    location_key="tavern",
                    role="merchant",
                    archetype="A gruff barkeep",
                ),
            ],
            items=[
                TemplateItem(
                    key="rusty_sword",
                    location_key="tavern",
                    type="weapon",
                    archetype="A rusty sword",
                ),
            ],
        ),
    )


async def _make_live_deps(
    session_id,
) -> tuple[PipelineDeps, InMemoryWorldService]:
    """Deps with a real InMemoryWorldService seeded with data."""
    svc = InMemoryWorldService()
    await svc.create_world_graph(session_id, _make_seed())
    deps = PipelineDeps(
        llm=AsyncMock(),
        world=svc,
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=AsyncMock(),
        safety_pre_gen=AsyncMock(),
        safety_post_gen=AsyncMock(),
    )
    return deps, svc


# ── Fallback (V1 stub) behaviour ─────────────────────────────────


async def test_context_includes_game_state() -> None:
    state = _make_state()
    result = await context_stage(state, _make_deps())

    assert result.world_context is not None
    assert result.world_context["game_state"] == {
        "location": "tavern",
        "hp": 100,
    }


async def test_context_includes_intent() -> None:
    state = _make_state(parsed_intent=ParsedIntent(intent="examine", confidence=0.9))
    result = await context_stage(state, _make_deps())

    assert result.world_context is not None
    assert result.world_context["intent"] == "examine"


async def test_context_intent_defaults_to_unknown() -> None:
    state = _make_state(parsed_intent=None)
    result = await context_stage(state, _make_deps())

    assert result.world_context is not None
    assert result.world_context["intent"] == "unknown"


async def test_context_includes_turn_number() -> None:
    state = _make_state(turn_number=5)
    result = await context_stage(state, _make_deps())

    assert result.world_context is not None
    assert result.world_context["turn_number"] == 5


async def test_context_includes_session_id() -> None:
    sid = uuid4()
    state = _make_state(session_id=sid)
    result = await context_stage(state, _make_deps())

    assert result.world_context is not None
    assert result.world_context["session_id"] == str(sid)


async def test_context_partial_is_true() -> None:
    """context_partial=True while location context unavailable."""
    state = _make_state()
    result = await context_stage(state, _make_deps())
    assert result.context_partial is True


async def test_original_state_not_mutated() -> None:
    state = _make_state()
    result = await context_stage(state, _make_deps())

    assert state.world_context is None
    assert result.world_context is not None
    assert state is not result


# ── Recent events in fallback path ────────────────────────────────


async def test_context_includes_recent_events() -> None:
    """Recent events from WorldService are serialized into context."""
    sid = uuid4()
    event = WorldEvent(
        session_id=sid,
        event_type="npc_moved",
        entity_id="npc-1",
        payload={"from": "tavern", "to": "market"},
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    deps = _make_deps()
    deps.world.get_recent_events.return_value = [event]
    state = _make_state(session_id=sid)

    result = await context_stage(state, deps)

    assert result.world_context is not None
    events = result.world_context["recent_events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "npc_moved"
    assert events[0]["entity_id"] == "npc-1"


async def test_context_empty_recent_events() -> None:
    """Empty events list is included when no events exist."""
    result = await context_stage(_make_state(), _make_deps())

    assert result.world_context is not None
    assert result.world_context["recent_events"] == []


async def test_context_event_fetch_failure_graceful() -> None:
    """WorldService event errors don't crash the stage."""
    deps = _make_deps()
    deps.world.get_recent_events.side_effect = RuntimeError("db down")
    state = _make_state()

    result = await context_stage(state, deps)

    assert result.world_context is not None
    assert result.world_context["recent_events"] == []
    assert result.context_partial is True


# ── WorldService integration ─────────────────────────────────────


async def test_live_world_context_not_partial() -> None:
    """When WorldService has data, context_partial is False."""
    sid = uuid4()
    state = _make_state(session_id=sid)
    deps, _ = await _make_live_deps(sid)

    result = await context_stage(state, deps)

    assert result.context_partial is False


async def test_live_world_context_has_location() -> None:
    """Live context includes location dict from WorldService."""
    sid = uuid4()
    state = _make_state(session_id=sid)
    deps, _ = await _make_live_deps(sid)

    result = await context_stage(state, deps)

    assert result.world_context is not None
    assert "location" in result.world_context
    assert result.world_context["location"]["name"] == "tavern"


async def test_live_world_context_has_adjacent() -> None:
    """Live context includes adjacent locations."""
    sid = uuid4()
    state = _make_state(session_id=sid)
    deps, _ = await _make_live_deps(sid)

    result = await context_stage(state, deps)

    ctx = result.world_context
    assert ctx is not None
    assert len(ctx["adjacent_locations"]) == 1
    assert ctx["adjacent_locations"][0]["name"] == "market"


async def test_live_world_context_has_npcs() -> None:
    """Live context includes NPCs at current location."""
    sid = uuid4()
    state = _make_state(session_id=sid)
    deps, _ = await _make_live_deps(sid)

    result = await context_stage(state, deps)

    ctx = result.world_context
    assert ctx is not None
    assert len(ctx["npcs_present"]) == 1


async def test_live_world_context_has_items() -> None:
    """Live context includes items at current location."""
    sid = uuid4()
    state = _make_state(session_id=sid)
    deps, _ = await _make_live_deps(sid)

    result = await context_stage(state, deps)

    ctx = result.world_context
    assert ctx is not None
    assert len(ctx["items_here"]) == 1


async def test_live_context_includes_intent() -> None:
    """Live context still includes intent and turn_number."""
    sid = uuid4()
    state = _make_state(
        session_id=sid,
        parsed_intent=ParsedIntent(intent="examine", confidence=0.9),
        turn_number=3,
    )
    deps, _ = await _make_live_deps(sid)

    result = await context_stage(state, deps)

    ctx = result.world_context
    assert ctx is not None
    assert ctx["intent"] == "examine"
    assert ctx["turn_number"] == 3


async def test_fallback_on_world_service_error() -> None:
    """Explicit test: exception in WorldService → fallback."""
    world = AsyncMock()
    world.get_player_location.side_effect = RuntimeError("service down")
    world.get_recent_events.return_value = []
    deps = PipelineDeps(
        llm=AsyncMock(),
        world=world,
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=AsyncMock(),
        safety_pre_gen=AsyncMock(),
        safety_post_gen=AsyncMock(),
    )

    state = _make_state()
    result = await context_stage(state, deps)

    assert result.context_partial is True
    assert result.world_context is not None
    assert "game_state" in result.world_context


# ===========================================================================
# AC-35.05 — Autonomous NPC changes injected into world_context
# AC-36.06 — Propagated consequences injected into world_context
# ===========================================================================


@pytest.mark.spec("AC-35.05")
@pytest.mark.asyncio
async def test_autonomous_changes_injected_into_world_context() -> None:
    """When autonomy_processor + world_time_service present, world_context gains
    autonomous_changes."""
    from unittest.mock import MagicMock
    from uuid import uuid4

    from tta.simulation.types import (
        NPCStateChange,
        WorldDelta,
        WorldTime,
    )

    universe_id = str(uuid4())
    wt = WorldTime(
        total_ticks=5, day_count=0, hour=8, minute=0, time_of_day_label="morning"
    )
    empty_delta = WorldDelta(from_tick=5, to_tick=6, world_time=wt, was_capped=False)
    change_delta = WorldDelta(
        from_tick=5,
        to_tick=6,
        world_time=wt,
        was_capped=False,
        changes=[
            NPCStateChange(
                npc_id="npc-01",
                action_type="state_change",
                before={"state": "idle"},
                after={"state": "working"},
            )
        ],
        events=[],
    )

    world_time_service = MagicMock()
    world_time_service.tick.return_value = empty_delta

    autonomy_processor = MagicMock()
    autonomy_processor.process.return_value = change_delta

    deps = _make_deps()
    deps = PipelineDeps(
        llm=deps.llm,
        world=deps.world,
        session_repo=deps.session_repo,
        turn_repo=deps.turn_repo,
        safety_pre_input=deps.safety_pre_input,
        safety_pre_gen=deps.safety_pre_gen,
        safety_post_gen=deps.safety_post_gen,
        world_time_service=world_time_service,
        autonomy_processor=autonomy_processor,
    )

    state = _make_state(game_state={"location": "tavern", "universe_id": universe_id})
    result_state = await context_stage(state, deps)
    world_context = result_state.world_context or {}

    assert "autonomous_changes" in world_context, (
        "world_context must contain 'autonomous_changes' "
        "when autonomy_processor is active"
    )
    assert len(world_context["autonomous_changes"]) == 1
    assert world_context["autonomous_changes"][0]["npc_id"] == "npc-01"


@pytest.mark.spec("AC-36.06")
@pytest.mark.asyncio
async def test_propagated_consequences_injected_into_world_context() -> None:
    """When consequence_propagator is present and events fire, world_context gains
    propagated_consequences."""
    from datetime import UTC, datetime
    from unittest.mock import MagicMock
    from uuid import uuid4

    from tta.simulation.types import (
        PropagationResult,
        WorldDelta,
        WorldEvent,
        WorldTime,
    )

    universe_id = str(uuid4())
    wt = WorldTime(
        total_ticks=5, day_count=0, hour=8, minute=0, time_of_day_label="morning"
    )
    event = WorldEvent(
        event_id="evt-01",
        universe_id=universe_id,
        event_type="narrative",
        description="A fire breaks out",
        severity="critical",
        triggered_at_tick=5,
        created_at=datetime.now(UTC),
    )
    autonomy_delta_with_events = WorldDelta(
        from_tick=5, to_tick=6, world_time=wt, was_capped=False, events=[event]
    )
    tick_delta = WorldDelta(from_tick=5, to_tick=6, world_time=wt, was_capped=False)

    world_time_service = MagicMock()
    world_time_service.tick.return_value = tick_delta

    autonomy_processor = MagicMock()
    autonomy_processor.process.return_value = autonomy_delta_with_events

    consequence_propagator = AsyncMock()
    consequence_propagator.propagate.return_value = [
        PropagationResult(
            source_event_id="evt-01", total_records=2, propagation_depth_reached=1
        )
    ]

    deps = _make_deps()
    deps = PipelineDeps(
        llm=deps.llm,
        world=deps.world,
        session_repo=deps.session_repo,
        turn_repo=deps.turn_repo,
        safety_pre_input=deps.safety_pre_input,
        safety_pre_gen=deps.safety_pre_gen,
        safety_post_gen=deps.safety_post_gen,
        world_time_service=world_time_service,
        autonomy_processor=autonomy_processor,
        consequence_propagator=consequence_propagator,
    )

    state = _make_state(game_state={"location": "tavern", "universe_id": universe_id})
    result_state = await context_stage(state, deps)
    world_context = result_state.world_context or {}

    assert "propagated_consequences" in world_context, (
        "world_context must contain 'propagated_consequences' "
        "when consequence_propagator is active"
    )
    assert len(world_context["propagated_consequences"]) == 1
    result = world_context["propagated_consequences"][0]
    assert result["source_event_id"] == "evt-01"
    assert result["total_records"] == 2
