"""Tests for ConsequenceService protocol and InMemory impl.

Covers chain creation, evaluation, resolution, pruning,
foreshadowing, hidden reveal, anchors, and divergence.
(S05 FR-3, FR-4, FR-7, FR-8)
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tta.choices.consequence_service import (
    EvaluateResult,
    InMemoryConsequenceService,
    _chain_prune_score,
)
from tta.models.choice import ImpactLevel, Reversibility
from tta.models.consequence import (
    ConsequenceChain,
    ConsequenceEntry,
    ConsequenceStatus,
    ConsequenceTimescale,
    ConsequenceVisibility,
)


@pytest.fixture
def svc() -> InMemoryConsequenceService:
    return InMemoryConsequenceService()


@pytest.fixture
def session_id():
    return uuid4()


# --- Chain creation ---


class TestCreateChain:
    @pytest.mark.asyncio
    async def test_create_returns_chain(self, svc, session_id) -> None:
        chain = await svc.create_chain(session_id, "Player stole the gem")
        assert chain.session_id == session_id
        assert chain.root_trigger == "Player stole the gem"
        assert chain.impact_level == ImpactLevel.ATMOSPHERIC

    @pytest.mark.asyncio
    async def test_create_with_entries(self, svc, session_id) -> None:
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="stole gem",
            effect="guards alerted",
            timescale=ConsequenceTimescale.SHORT_TERM,
        )
        chain = await svc.create_chain(
            session_id,
            "Theft",
            entries=[entry],
            impact_level=ImpactLevel.CONSEQUENTIAL,
            turn=5,
        )
        assert len(chain.entries) == 1
        assert chain.entries[0].chain_id == chain.id
        assert chain.entries[0].turn_created == 5

    @pytest.mark.asyncio
    async def test_create_with_parent_chain(self, svc, session_id) -> None:
        parent = await svc.create_chain(session_id, "Root cause")
        child = await svc.create_chain(
            session_id,
            "Branch effect",
            parent_chain_id=parent.id,
        )
        assert child.parent_chain_id == parent.id

    @pytest.mark.asyncio
    async def test_create_stores_in_session(self, svc, session_id) -> None:
        await svc.create_chain(session_id, "Chain 1")
        await svc.create_chain(session_id, "Chain 2")
        active = await svc.get_active_chains(session_id)
        assert len(active) == 2

    @pytest.mark.asyncio
    async def test_sessions_isolated(self, svc) -> None:
        s1, s2 = uuid4(), uuid4()
        await svc.create_chain(s1, "Session 1 chain")
        await svc.create_chain(s2, "Session 2 chain")
        assert len(await svc.get_active_chains(s1)) == 1
        assert len(await svc.get_active_chains(s2)) == 1


# --- Evaluation ---


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_immediate_entry_activates(self, svc, session_id) -> None:
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="picked up cursed ring",
            effect="hand tingles",
            timescale=ConsequenceTimescale.IMMEDIATE,
        )
        await svc.create_chain(session_id, "Cursed ring", entries=[entry], turn=0)
        result = await svc.evaluate(session_id, 0, "wear ring")
        assert len(result.world_changes) == 1
        assert result.world_changes[0].payload["effect"] == "hand tingles"

    @pytest.mark.asyncio
    async def test_short_term_waits_one_turn(self, svc, session_id) -> None:
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="alerted guards",
            effect="patrol arrives",
            timescale=ConsequenceTimescale.SHORT_TERM,
        )
        await svc.create_chain(session_id, "Alert", entries=[entry], turn=0)
        # Turn 0: too early
        r0 = await svc.evaluate(session_id, 0, "wait")
        assert len(r0.world_changes) == 0
        # Turn 1: should activate
        r1 = await svc.evaluate(session_id, 1, "wait")
        assert len(r1.world_changes) == 1

    @pytest.mark.asyncio
    async def test_long_term_waits_many_turns(self, svc, session_id) -> None:
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="betrayed the king",
            effect="kingdom falls",
            timescale=ConsequenceTimescale.LONG_TERM,
        )
        await svc.create_chain(session_id, "Betrayal", entries=[entry], turn=0)
        r5 = await svc.evaluate(session_id, 5, "wait")
        assert len(r5.world_changes) == 0
        r11 = await svc.evaluate(session_id, 11, "wait")
        assert len(r11.world_changes) == 1

    @pytest.mark.asyncio
    async def test_hidden_entry_generates_hint_not_change(
        self, svc, session_id
    ) -> None:
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="drank the potion",
            effect="slow transformation",
            visibility=ConsequenceVisibility.HIDDEN,
            timescale=ConsequenceTimescale.IMMEDIATE,
            narrative_hook="Your skin feels oddly warm.",
        )
        await svc.create_chain(session_id, "Potion effect", entries=[entry], turn=0)
        result = await svc.evaluate(session_id, 0, "continue")
        assert len(result.world_changes) == 0
        assert "Your skin feels oddly warm." in result.hints

    @pytest.mark.asyncio
    async def test_foreshadowed_entry_hints(self, svc, session_id) -> None:
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="angered the witch",
            effect="curse activates",
            visibility=ConsequenceVisibility.FORESHADOWED,
            timescale=ConsequenceTimescale.SHORT_TERM,
            narrative_hook="A cold wind follows you.",
        )
        await svc.create_chain(session_id, "Witch curse", entries=[entry], turn=0)
        result = await svc.evaluate(session_id, 0, "walk")
        assert "A cold wind follows you." in result.hints

    @pytest.mark.asyncio
    async def test_resolved_chain_skipped(self, svc, session_id) -> None:
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="t",
            effect="e",
            timescale=ConsequenceTimescale.IMMEDIATE,
        )
        chain = await svc.create_chain(
            session_id, "Done chain", entries=[entry], turn=0
        )
        await svc.resolve_chain(chain.id, 1)
        result = await svc.evaluate(session_id, 2, "wait")
        assert len(result.world_changes) == 0

    @pytest.mark.asyncio
    async def test_evaluate_result_is_bundle(self) -> None:
        r = EvaluateResult()
        assert r.chain_updates == []
        assert r.world_changes == []
        assert r.hints == []


# --- Resolution ---


class TestResolveChain:
    @pytest.mark.asyncio
    async def test_resolve_marks_all_entries(self, svc, session_id) -> None:
        e1 = ConsequenceEntry(chain_id=uuid4(), trigger="t1", effect="e1")
        e2 = ConsequenceEntry(chain_id=uuid4(), trigger="t2", effect="e2")
        chain = await svc.create_chain(session_id, "Multi", entries=[e1, e2], turn=0)
        resolved = await svc.resolve_chain(chain.id, 5)
        assert resolved is not None
        assert all(e.status == ConsequenceStatus.RESOLVED for e in resolved.entries)
        assert all(e.turn_resolved == 5 for e in resolved.entries)

    @pytest.mark.asyncio
    async def test_resolve_unknown_returns_none(self, svc) -> None:
        result = await svc.resolve_chain(uuid4(), 5)
        assert result is None

    @pytest.mark.asyncio
    async def test_resolved_chain_not_in_active(self, svc, session_id) -> None:
        entry = ConsequenceEntry(chain_id=uuid4(), trigger="t", effect="e")
        chain = await svc.create_chain(session_id, "C", entries=[entry], turn=0)
        await svc.resolve_chain(chain.id, 1)
        active = await svc.get_active_chains(session_id)
        assert len(active) == 0


# --- Pruning ---


class TestPruneChains:
    @pytest.mark.asyncio
    async def test_prune_excess_chains(self, svc, session_id) -> None:
        for i in range(5):
            entry = ConsequenceEntry(chain_id=uuid4(), trigger=f"t{i}", effect=f"e{i}")
            await svc.create_chain(session_id, f"chain_{i}", entries=[entry], turn=0)
        pruned = await svc.prune_chains(session_id, 10, max_chains=3)
        assert len(pruned) == 2
        active = await svc.get_active_chains(session_id)
        assert len(active) == 3

    @pytest.mark.asyncio
    async def test_no_prune_under_limit(self, svc, session_id) -> None:
        await svc.create_chain(session_id, "Only one", turn=0)
        pruned = await svc.prune_chains(session_id, 10)
        assert len(pruned) == 0

    @pytest.mark.asyncio
    async def test_resolved_pruned_first(self, svc, session_id) -> None:
        # Create 3 chains, resolve 1
        e1 = ConsequenceEntry(chain_id=uuid4(), trigger="t", effect="e")
        c1 = await svc.create_chain(session_id, "Will resolve", entries=[e1], turn=0)
        await svc.resolve_chain(c1.id, 1)

        for i in range(3):
            entry = ConsequenceEntry(chain_id=uuid4(), trigger=f"t{i}", effect=f"e{i}")
            await svc.create_chain(session_id, f"active_{i}", entries=[entry], turn=0)
        # 3 active + 1 resolved. Prune to max 2 active.
        pruned = await svc.prune_chains(session_id, 10, max_chains=2)
        assert len(pruned) == 1

    @pytest.mark.asyncio
    async def test_dormant_detection(self, svc, session_id) -> None:
        entry = ConsequenceEntry(chain_id=uuid4(), trigger="old", effect="forgotten")
        chain = await svc.create_chain(session_id, "Ancient", entries=[entry], turn=0)
        chain.last_active_turn = 0
        await svc.prune_chains(session_id, 55)
        assert chain.is_dormant

    def test_prune_score_resolved_is_lowest(self) -> None:
        chain = ConsequenceChain(
            id=uuid4(),
            session_id=uuid4(),
            root_trigger="t",
            entries=[
                ConsequenceEntry(
                    chain_id=uuid4(),
                    trigger="t",
                    effect="e",
                    status=ConsequenceStatus.RESOLVED,
                )
            ],
        )
        assert _chain_prune_score(chain) == 0

    def test_prune_score_permanent_protected(self) -> None:
        chain = ConsequenceChain(
            id=uuid4(),
            session_id=uuid4(),
            root_trigger="t",
            reversibility=Reversibility.PERMANENT,
            entries=[
                ConsequenceEntry(
                    chain_id=uuid4(),
                    trigger="t",
                    effect="e",
                    status=ConsequenceStatus.PENDING,
                )
            ],
        )
        score = _chain_prune_score(chain)
        assert score >= 9  # PENDING(4) + PERMANENT(5)


# --- Foreshadowing ---


class TestForeshadowing:
    @pytest.mark.asyncio
    async def test_hidden_entries_foreshadow(self, svc, session_id) -> None:
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="curse placed",
            effect="doom",
            visibility=ConsequenceVisibility.HIDDEN,
            narrative_hook="Shadows deepen around you.",
        )
        await svc.create_chain(session_id, "Curse", entries=[entry], turn=0)
        hints = await svc.get_foreshadowing_hints(session_id)
        assert "Shadows deepen around you." in hints

    @pytest.mark.asyncio
    async def test_no_hints_for_visible(self, svc, session_id) -> None:
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="t",
            effect="e",
            visibility=ConsequenceVisibility.VISIBLE,
            narrative_hook="Not a hint",
        )
        await svc.create_chain(session_id, "Visible", entries=[entry], turn=0)
        hints = await svc.get_foreshadowing_hints(session_id)
        assert len(hints) == 0


# --- Hidden reveal ---


class TestRevealHiddenEntry:
    @pytest.mark.asyncio
    async def test_reveal_hidden(self, svc, session_id) -> None:
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="secret",
            effect="revealed",
            visibility=ConsequenceVisibility.HIDDEN,
        )
        chain = await svc.create_chain(session_id, "Secret", entries=[entry], turn=0)
        revealed = await svc.reveal_hidden_entry(chain.entries[0].id)
        assert revealed is not None
        assert revealed.visibility == ConsequenceVisibility.VISIBLE
        assert revealed.status == ConsequenceStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_reveal_nonexistent_returns_none(self, svc) -> None:
        result = await svc.reveal_hidden_entry(uuid4())
        assert result is None


# --- Anchors and divergence ---


class TestAnchorsAndDivergence:
    @pytest.mark.asyncio
    async def test_add_and_get_anchors(self, svc, session_id) -> None:
        await svc.add_anchor(session_id, "Meet the wizard", target_turn=10)
        anchors = await svc.get_active_anchors(session_id)
        assert len(anchors) == 1
        assert anchors[0].description == "Meet the wizard"

    @pytest.mark.asyncio
    async def test_divergence_no_anchors(self, svc, session_id) -> None:
        score = await svc.calculate_divergence(session_id, 5)
        assert score.score == 0.0
        assert score.factors["reason"] == "no_active_anchors"

    @pytest.mark.asyncio
    async def test_divergence_with_chains_and_anchors(self, svc, session_id) -> None:
        await svc.add_anchor(session_id, "Final battle", target_turn=20)
        for i in range(10):
            entry = ConsequenceEntry(
                chain_id=uuid4(),
                trigger=f"t{i}",
                effect=f"e{i}",
                timescale=ConsequenceTimescale.IMMEDIATE,
            )
            await svc.create_chain(
                session_id,
                f"chain_{i}",
                entries=[entry],
                impact_level=(ImpactLevel.PIVOTAL if i < 5 else ImpactLevel.COSMETIC),
                turn=0,
            )
        score = await svc.calculate_divergence(session_id, 10)
        assert 0.0 < score.score <= 1.0
        assert score.nearest_anchor_id is not None


# --- Test isolation ---


class TestClear:
    @pytest.mark.asyncio
    async def test_clear_resets_state(self, svc, session_id) -> None:
        await svc.create_chain(session_id, "Chain 1")
        await svc.add_anchor(session_id, "Anchor 1")
        svc.clear()
        assert len(await svc.get_active_chains(session_id)) == 0
        assert len(await svc.get_active_anchors(session_id)) == 0
