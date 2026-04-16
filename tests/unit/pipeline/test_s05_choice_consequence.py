"""Tests for S05 Choice & Consequence pipeline integration (Wave 25).

Covers: AC-5.4 permanent signals, AC-5.10 divergence steering,
AC-5.8 dormant fix + closure, AC-5.1 consequence surfacing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tta.choices.consequence_service import InMemoryConsequenceService
from tta.models.choice import (
    ChoiceClassification,
    ChoiceType,
    ImpactLevel,
    Reversibility,
)
from tta.models.consequence import (
    ConsequenceChain,
    ConsequenceEntry,
    ConsequenceStatus,
    ConsequenceTimescale,
    ConsequenceVisibility,
)
from tta.models.turn import ParsedIntent, TurnState
from tta.pipeline.stages.context import context_stage
from tta.pipeline.stages.generate import _build_generation_prompt
from tta.pipeline.stages.understand import _prune_consequence_chains
from tta.pipeline.types import PipelineDeps

SID = uuid4()
_CHAIN_ID = uuid4()


def _entry(
    trigger: str = "trigger",
    effect: str = "effect",
    **kw: object,
) -> ConsequenceEntry:
    """Create a ConsequenceEntry with required fields filled in."""
    defaults: dict = {
        "chain_id": _CHAIN_ID,
        "trigger": trigger,
        "effect": effect,
        "timescale": ConsequenceTimescale.SHORT_TERM,
        "visibility": ConsequenceVisibility.VISIBLE,
    }
    defaults.update(kw)
    return ConsequenceEntry(**defaults)


def _make_state(**overrides: object) -> TurnState:
    defaults: dict = {
        "session_id": SID,
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


# --- AC-5.4: Permanent Choice Signals ---


class TestPermanentChoiceSignals:
    def test_permanent_signal_injected(self) -> None:
        cc = ChoiceClassification(
            types=[ChoiceType.ACTION],
            primary_type=ChoiceType.ACTION,
            reversibility=Reversibility.PERMANENT,
        )
        state = _make_state(choice_classification=cc)
        prompt = _build_generation_prompt(state)
        assert "PERMANENT" in prompt
        assert "irreversible" in prompt.lower()
        assert "charged atmosphere" in prompt.lower()

    def test_non_permanent_omits_signal(self) -> None:
        cc = ChoiceClassification(
            types=[ChoiceType.ACTION],
            primary_type=ChoiceType.ACTION,
            reversibility=Reversibility.MODERATE,
        )
        state = _make_state(choice_classification=cc)
        prompt = _build_generation_prompt(state)
        assert "PERMANENT" not in prompt

    def test_missing_classification_safe(self) -> None:
        state = _make_state(choice_classification=None)
        prompt = _build_generation_prompt(state)
        assert "PERMANENT" not in prompt
        assert "Generate a narrative response" in prompt


# --- AC-5.10: Divergence Steering ---


class TestDivergenceSteering:
    @pytest.mark.asyncio
    async def test_divergence_guidance_injected_when_high(self) -> None:
        svc = InMemoryConsequenceService()
        # Create enough high-impact chains to trigger divergence >= 0.7
        for i in range(25):
            await svc.create_chain(
                session_id=SID,
                root_trigger=f"trigger-{i}",
                impact_level=ImpactLevel.DEFINING,
                entries=[_entry(trigger=f"t-{i}", effect=f"e-{i}")],
            )
        await svc.add_anchor(
            session_id=SID,
            description="reach the mountain temple",
            target_turn=10,
        )
        state = _make_state(turn_number=5)
        deps = _make_deps(consequence_service=svc)
        result = await context_stage(state, deps)
        assert result.divergence_guidance is not None
        assert "diverging" in result.divergence_guidance.lower()
        assert "mountain temple" in result.divergence_guidance.lower()

    @pytest.mark.asyncio
    async def test_divergence_omitted_when_low(self) -> None:
        svc = InMemoryConsequenceService()
        await svc.create_chain(
            session_id=SID,
            root_trigger="minor event",
            impact_level=ImpactLevel.ATMOSPHERIC,
            entries=[_entry(trigger="small", effect="ripple")],
        )
        state = _make_state(turn_number=5)
        deps = _make_deps(consequence_service=svc)
        result = await context_stage(state, deps)
        assert result.divergence_guidance is None

    def test_divergence_guidance_in_prompt(self) -> None:
        state = _make_state(
            divergence_guidance="The story is diverging. Steer toward: X"
        )
        prompt = _build_generation_prompt(state)
        assert "diverging" in prompt.lower()
        assert "Steer toward: X" in prompt

    @pytest.mark.asyncio
    async def test_no_anchors_still_provides_guidance(self) -> None:
        """Without anchors, divergence is 0.0 — guidance should be None."""
        svc = InMemoryConsequenceService()
        for i in range(25):
            await svc.create_chain(
                session_id=SID,
                root_trigger=f"trigger-{i}",
                impact_level=ImpactLevel.DEFINING,
                entries=[_entry(trigger=f"t-{i}", effect=f"e-{i}")],
            )
        # No anchors set — divergence returns 0.0 (unmeasurable)
        state = _make_state(turn_number=5)
        deps = _make_deps(consequence_service=svc)
        result = await context_stage(state, deps)
        assert result.divergence_guidance is None


# --- AC-5.8: Dormant Fix + Closure ---


class TestDormantFixAndClosure:
    @pytest.mark.asyncio
    async def test_last_active_turn_only_on_activation(self) -> None:
        """Bug fix: last_active_turn should only update when chain activates."""
        svc = InMemoryConsequenceService()
        chain = await svc.create_chain(
            session_id=SID,
            root_trigger="old event",
            impact_level=ImpactLevel.CONSEQUENTIAL,
            entries=[
                _entry(
                    trigger="delayed effect",
                    effect="long term consequence",
                    timescale=ConsequenceTimescale.LONG_TERM,
                )
            ],
        )
        original_turn = chain.last_active_turn
        # Evaluate — entry won't activate from unrelated action
        await svc.evaluate(SID, original_turn + 5, "walk around")
        chains = await svc.get_active_chains(SID)
        assert len(chains) == 1
        # last_active_turn should NOT have changed
        assert chains[0].last_active_turn == original_turn

    @pytest.mark.asyncio
    async def test_prune_returns_closures(self) -> None:
        svc = InMemoryConsequenceService()
        chain = await svc.create_chain(
            session_id=SID,
            root_trigger="forgotten promise",
            impact_level=ImpactLevel.ATMOSPHERIC,
            entries=[_entry(trigger="promise made", effect="waiting")],
        )
        # Simulate chain being inactive for 50+ turns
        chain.last_active_turn = 0
        _pruned_ids, closures = await svc.prune_chains(SID, 60)
        assert "forgotten promise" in closures

    @pytest.mark.asyncio
    async def test_pruning_wired_in_understand(self) -> None:
        svc = InMemoryConsequenceService()
        chain = await svc.create_chain(
            session_id=SID,
            root_trigger="ancient vow",
            impact_level=ImpactLevel.ATMOSPHERIC,
            entries=[_entry(trigger="vow spoken", effect="binding")],
        )
        chain.last_active_turn = 0
        state = _make_state(turn_number=60)
        deps = _make_deps(consequence_service=svc)
        result = await _prune_consequence_chains(state, deps)
        assert result.pruned_chain_closures is not None
        assert "ancient vow" in result.pruned_chain_closures

    def test_closure_hints_in_prompt(self) -> None:
        state = _make_state(
            pruned_chain_closures=["the broken oath", "the lost artifact"]
        )
        prompt = _build_generation_prompt(state)
        assert "broken oath" in prompt
        assert "Fading story threads" in prompt

    @pytest.mark.asyncio
    async def test_no_pruning_safe(self) -> None:
        svc = InMemoryConsequenceService()
        state = _make_state(turn_number=5)
        deps = _make_deps(consequence_service=svc)
        result = await _prune_consequence_chains(state, deps)
        assert result.pruned_chain_closures is None


# --- AC-5.1: Consequence Narrative Surfacing ---


class TestConsequenceSurfacing:
    def test_consequence_details_in_prompt(self) -> None:
        chains = [
            ConsequenceChain(
                session_id=SID,
                root_trigger="betrayed the merchant",
                impact_level=ImpactLevel.PIVOTAL,
                entries=[],
            ),
            ConsequenceChain(
                session_id=SID,
                root_trigger="saved the child",
                impact_level=ImpactLevel.CONSEQUENTIAL,
                entries=[],
            ),
        ]
        state = _make_state(active_consequences=chains)
        prompt = _build_generation_prompt(state)
        assert "betrayed the merchant" in prompt
        assert "saved the child" in prompt
        assert "Consequences manifesting" in prompt

    def test_empty_consequences_no_section(self) -> None:
        state = _make_state(active_consequences=None)
        prompt = _build_generation_prompt(state)
        assert "Consequences manifesting" not in prompt

    def test_resolved_chains_excluded(self) -> None:
        chains = [
            ConsequenceChain(
                session_id=SID,
                root_trigger="resolved event",
                impact_level=ImpactLevel.ATMOSPHERIC,
                entries=[
                    _entry(
                        trigger="old trigger",
                        effect="old effect",
                        status=ConsequenceStatus.RESOLVED,
                    )
                ],
            ),
        ]
        state = _make_state(active_consequences=chains)
        prompt = _build_generation_prompt(state)
        assert "Consequences manifesting" not in prompt
