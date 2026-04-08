"""Tests for the context pipeline stage."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

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
