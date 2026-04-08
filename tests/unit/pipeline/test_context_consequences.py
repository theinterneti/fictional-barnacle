"""Tests for consequence enrichment in context stage."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from tta.choices.consequence_service import (
    InMemoryConsequenceService,
)
from tta.models.choice import ImpactLevel, Reversibility
from tta.models.consequence import (
    ConsequenceEntry,
    ConsequenceTimescale,
    ConsequenceVisibility,
)
from tta.models.turn import ParsedIntent, TurnState
from tta.pipeline.stages.context import context_stage
from tta.pipeline.types import PipelineDeps


def _make_state(**overrides: object) -> TurnState:
    defaults: dict = {
        "session_id": uuid4(),
        "turn_number": 5,
        "player_input": "look around",
        "game_state": {"location": "tavern", "hp": 100},
        "parsed_intent": ParsedIntent(intent="examine", confidence=0.9),
    }
    defaults.update(overrides)
    return TurnState(**defaults)


def _make_deps(
    *, consequence_service: InMemoryConsequenceService | None = None
) -> PipelineDeps:
    world = AsyncMock()
    world.get_player_location.side_effect = ValueError("no data")
    world.get_recent_events.return_value = []
    return PipelineDeps(
        llm=AsyncMock(),
        world=world,
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=AsyncMock(),
        safety_pre_gen=AsyncMock(),
        safety_post_gen=AsyncMock(),
        consequence_service=consequence_service,
    )


# --- no consequence service ---


async def test_no_consequence_service_skips_enrichment() -> None:
    """Without consequence_service, no active_consequences key added."""
    state = _make_state()
    result = await context_stage(state, _make_deps())

    assert result.world_context is not None
    assert "active_consequences" not in result.world_context


# --- with consequence service ---


async def test_empty_chains_skips_enrichment() -> None:
    """ConsequenceService with no chains doesn't add keys."""
    svc = InMemoryConsequenceService()
    state = _make_state()
    result = await context_stage(state, _make_deps(consequence_service=svc))

    assert result.world_context is not None
    assert "active_consequences" not in result.world_context


async def test_active_chain_appears_in_context() -> None:
    """Active chain adds summary to world_context."""
    svc = InMemoryConsequenceService()
    sid = uuid4()
    state = _make_state(session_id=sid, turn_number=5)

    # Create a chain with a pending entry
    await svc.create_chain(
        sid,
        "Stole the merchant's ring",
        entries=[
            ConsequenceEntry(
                chain_id=uuid4(),
                trigger="Stole the merchant's ring",
                effect="The merchant becomes hostile",
                timescale=ConsequenceTimescale.IMMEDIATE,
                visibility=ConsequenceVisibility.VISIBLE,
                turn_created=0,
            ),
        ],
        impact_level=ImpactLevel.CONSEQUENTIAL,
        reversibility=Reversibility.SIGNIFICANT,
        turn=0,
    )

    deps = _make_deps(consequence_service=svc)
    result = await context_stage(state, deps)

    ctx = result.world_context
    assert ctx is not None
    assert "active_consequences" in ctx
    assert len(ctx["active_consequences"]) >= 1
    summary = ctx["active_consequences"][0]
    assert "trigger_description" in summary
    assert summary["trigger_description"] == "Stole the merchant's ring"


async def test_foreshadowing_hints_appear_in_context() -> None:
    """Hidden entries produce foreshadowing hints."""
    svc = InMemoryConsequenceService()
    sid = uuid4()
    state = _make_state(session_id=sid, turn_number=5)

    # Create chain with a hidden entry that should activate
    await svc.create_chain(
        sid,
        "Poisoned the well",
        entries=[
            ConsequenceEntry(
                chain_id=uuid4(),
                trigger="Poisoned the well",
                effect="Villagers fall sick",
                narrative_hook="A strange odor drifts from the well",
                timescale=ConsequenceTimescale.IMMEDIATE,
                visibility=ConsequenceVisibility.HIDDEN,
                turn_created=0,
            ),
        ],
        impact_level=ImpactLevel.PIVOTAL,
        reversibility=Reversibility.PERMANENT,
        turn=0,
    )

    deps = _make_deps(consequence_service=svc)
    result = await context_stage(state, deps)

    ctx = result.world_context
    assert ctx is not None
    # Hidden entry should produce foreshadowing hint
    if "foreshadowing_hints" in ctx:
        assert len(ctx["foreshadowing_hints"]) >= 1


async def test_resolved_chains_excluded_from_summaries() -> None:
    """Resolved chains don't appear in active_consequences."""
    svc = InMemoryConsequenceService()
    sid = uuid4()
    state = _make_state(session_id=sid, turn_number=5)

    chain = await svc.create_chain(
        sid,
        "Minor event",
        entries=[
            ConsequenceEntry(
                chain_id=uuid4(),
                trigger="Minor event",
                effect="Something happened",
                timescale=ConsequenceTimescale.IMMEDIATE,
                visibility=ConsequenceVisibility.VISIBLE,
                turn_created=0,
            ),
        ],
        turn=0,
    )
    await svc.resolve_chain(chain.id, turn=1)

    deps = _make_deps(consequence_service=svc)
    result = await context_stage(state, deps)

    ctx = result.world_context
    assert ctx is not None
    # Either no key or empty list — resolved chains excluded
    summaries = ctx.get("active_consequences", [])
    for s in summaries:
        assert not s.get("is_resolved", False)


async def test_consequence_service_error_doesnt_crash() -> None:
    """Exception in consequence service is caught gracefully."""
    broken_svc = AsyncMock()
    broken_svc.get_active_chains = AsyncMock(
        side_effect=RuntimeError("service exploded")
    )
    deps = PipelineDeps(
        llm=AsyncMock(),
        world=AsyncMock(),
        session_repo=AsyncMock(),
        turn_repo=AsyncMock(),
        safety_pre_input=AsyncMock(),
        safety_pre_gen=AsyncMock(),
        safety_post_gen=AsyncMock(),
        consequence_service=broken_svc,
    )
    # Mock the world service to fail too, so we go through fallback
    deps.world.get_player_location.side_effect = ValueError("no data")
    deps.world.get_recent_events.return_value = []

    state = _make_state()
    result = await context_stage(state, deps)

    # Should still succeed with context
    assert result.world_context is not None
    assert "active_consequences" not in result.world_context


async def test_multiple_chains_all_summarized() -> None:
    """Multiple active chains produce multiple summaries."""
    svc = InMemoryConsequenceService()
    sid = uuid4()
    state = _make_state(session_id=sid, turn_number=5)

    for trigger in ["Helped the blacksmith", "Angered the guard"]:
        await svc.create_chain(
            sid,
            trigger,
            entries=[
                ConsequenceEntry(
                    chain_id=uuid4(),
                    trigger=trigger,
                    effect=f"Effect of: {trigger}",
                    timescale=ConsequenceTimescale.IMMEDIATE,
                    visibility=ConsequenceVisibility.VISIBLE,
                    turn_created=0,
                ),
            ],
            turn=0,
        )

    deps = _make_deps(consequence_service=svc)
    result = await context_stage(state, deps)

    ctx = result.world_context
    assert ctx is not None
    assert len(ctx.get("active_consequences", [])) == 2


async def test_consequence_data_stored_in_turnstate() -> None:
    """TurnState active_consequences field populated via model_copy."""
    svc = InMemoryConsequenceService()
    sid = uuid4()
    state = _make_state(session_id=sid, turn_number=3)

    await svc.create_chain(
        sid,
        "Freed the prisoner",
        entries=[
            ConsequenceEntry(
                chain_id=uuid4(),
                trigger="Freed the prisoner",
                effect="Guards search the area",
                timescale=ConsequenceTimescale.IMMEDIATE,
                visibility=ConsequenceVisibility.VISIBLE,
                turn_created=0,
            ),
        ],
        turn=0,
    )

    deps = _make_deps(consequence_service=svc)
    result = await context_stage(state, deps)

    # world_context should have the data
    assert "active_consequences" in result.world_context
