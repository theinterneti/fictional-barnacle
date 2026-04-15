"""S05 Choice & Consequence — Acceptance Criteria compliance tests.

Covers AC-5.1, AC-5.2, AC-5.3, AC-5.4, AC-5.6, AC-5.7, AC-5.8,
AC-5.9, AC-5.10.

v2 ACs (deferred — require live narrative generation):
  AC-5.5 — Subtle foreshadowing over 5+ turns: requires live LLM
            narrative generation across multiple turns with a hidden
            consequence chain; not unit-testable in isolation.
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest

from tta.choices.classifier import INTENT_CHOICE_MAP, classify_choice
from tta.choices.consequence_service import InMemoryConsequenceService
from tta.models.choice import ChoiceType, Reversibility
from tta.models.consequence import (
    ConsequenceChain,
    ConsequenceEntry,
    ConsequenceStatus,
    ConsequenceTimescale,
    DivergenceScore,
)

# ── AC-5.1: Delayed consequences manifest after SHORT_TERM turns ──────────────


class TestAC501DelayedConsequences:
    """AC-5.1: Consequential choice produces delayed consequence after 10+ turns.

    AC-5.1 requires that at least one delayed consequence manifests after 10+
    turns. `test_long_term_entry_manifests_after_ten_turns` directly validates
    this: a LONG_TERM entry is inactive at turn 5 and active at turn 15.

    The SHORT_TERM tests verify FR-3.1 timescale mechanics (1–10 turn window)
    and the boundary condition that no consequence fires on the creation turn.
    """

    @pytest.mark.asyncio
    async def test_short_term_entry_inactive_at_creation_turn(self) -> None:
        """SHORT_TERM entry is not active on the creation turn (turn 0)."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="player ignored the warning",
            effect="guards become hostile",
            timescale=ConsequenceTimescale.SHORT_TERM,
        )
        await svc.create_chain(
            session_id,
            "Ignored warning",
            entries=[entry],
            turn=0,
        )
        result = await svc.evaluate(session_id, 0, "look around")
        assert len(result.world_changes) == 0

    @pytest.mark.asyncio
    async def test_short_term_entry_activates_within_window(self) -> None:
        """SHORT_TERM entry activates in the 1–10 turn window (manifested delay)."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="player ignored the warning",
            effect="guards become hostile",
            timescale=ConsequenceTimescale.SHORT_TERM,
        )
        await svc.create_chain(
            session_id,
            "Ignored warning",
            entries=[entry],
            turn=0,
        )
        result = await svc.evaluate(session_id, 5, "continue exploring")
        assert len(result.world_changes) == 1
        assert result.world_changes[0].payload["effect"] == "guards become hostile"

    @pytest.mark.asyncio
    async def test_long_term_entry_manifests_after_ten_turns(self) -> None:
        """LONG_TERM entry manifests at turn > 10, satisfying 10+ turn AC."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="player made consequential choice",
            effect="kingdom remembers your actions",
            timescale=ConsequenceTimescale.LONG_TERM,
        )
        await svc.create_chain(
            session_id,
            "Consequential choice",
            entries=[entry],
            turn=0,
        )
        # Not active at turn 5
        r5 = await svc.evaluate(session_id, 5, "explore")
        assert len(r5.world_changes) == 0
        # Active at turn 15 (> 10 turns elapsed)
        r15 = await svc.evaluate(session_id, 15, "continue")
        assert len(r15.world_changes) == 1


# ── AC-5.2: At least 3 distinct choice types offered ─────────────────────────


class TestAC502DistinctChoiceTypes:
    """AC-5.2: Suggested actions offer at least 3 distinct approaches.

    The ChoiceType enum defines 6 distinct categories (ACTION, DIALOGUE,
    MOVEMENT, STRATEGIC, MORAL, REFUSAL). The classifier maps intents and
    pattern-matches player input to these types, ensuring varied choices.
    We validate: enum has 6 distinct values, and the classifier correctly
    maps refusal/moral/dialogue patterns to their respective types.
    """

    def test_choice_type_enum_has_six_distinct_values(self) -> None:
        """ChoiceType defines 6 distinct values — well above the AC-5.2 minimum."""
        types = list(ChoiceType)
        assert len(types) >= 3, "Need at least 3 distinct choice types"
        assert len(types) == 6
        expected = {
            ChoiceType.ACTION,
            ChoiceType.DIALOGUE,
            ChoiceType.MOVEMENT,
            ChoiceType.STRATEGIC,
            ChoiceType.MORAL,
            ChoiceType.REFUSAL,
        }
        assert set(types) == expected

    def test_refusal_pattern_classifies_as_refusal(self) -> None:
        """Refusal-phrased input produces ChoiceType.REFUSAL."""
        result = classify_choice("I refuse to cooperate", "other")
        assert ChoiceType.REFUSAL in result.types

    def test_moral_pattern_classifies_as_moral(self) -> None:
        """Moral-phrased input produces ChoiceType.MORAL."""
        result = classify_choice("I betray the merchant", "other")
        assert ChoiceType.MORAL in result.types

    def test_dialogue_intent_classifies_as_dialogue(self) -> None:
        """'talk' intent maps to ChoiceType.DIALOGUE."""
        result = classify_choice("talk to the innkeeper", "talk")
        assert ChoiceType.DIALOGUE in result.types

    def test_intent_map_covers_multiple_distinct_types(self) -> None:
        """INTENT_CHOICE_MAP produces ACTION, DIALOGUE, and MOVEMENT types."""
        produced_types = set(INTENT_CHOICE_MAP.values())
        assert produced_types == {
            ChoiceType.ACTION,
            ChoiceType.DIALOGUE,
            ChoiceType.MOVEMENT,
        }


# ── AC-5.3: Refusal is tracked as a choice ───────────────────────────────────


class TestAC503RefusalTracked:
    """AC-5.3: Ignoring an NPC request is classified and tracked as a choice.

    Two validations:
    1. Refusal-phrased inputs are classified as ChoiceType.REFUSAL.
    2. A consequence chain with trigger "NPC request ignored" can be created
       and retrieved — demonstrating the service tracks refusals as chains.

    Note: these tests validate classification and chain storage only. The NPC
    disposition consequence described in AC-5.3 is not yet implemented (v2);
    see specs/index.json AC-5.3 status.
    """

    def test_do_nothing_classifies_as_refusal(self) -> None:
        """'I do nothing' produces ChoiceType.REFUSAL classification."""
        result = classify_choice("I do nothing", "other")
        assert ChoiceType.REFUSAL in result.types

    def test_i_refuse_classifies_as_refusal(self) -> None:
        """'I refuse' produces ChoiceType.REFUSAL classification."""
        result = classify_choice("I refuse", "other")
        assert ChoiceType.REFUSAL in result.types

    def test_walk_away_classifies_as_refusal(self) -> None:
        """'I walk away' produces ChoiceType.REFUSAL classification."""
        result = classify_choice("I walk away from the guard", "other")
        assert ChoiceType.REFUSAL in result.types

    @pytest.mark.asyncio
    async def test_npc_refusal_chain_created_and_retrievable(self) -> None:
        """Consequence chain for NPC request ignored is stored and retrieved."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()
        chain = await svc.create_chain(
            session_id,
            "NPC request ignored",
        )
        assert chain.root_trigger == "NPC request ignored"
        active = await svc.get_active_chains(session_id)
        assert len(active) == 1
        assert active[0].id == chain.id


# ── AC-5.4: Permanent reversibility stored and distinguishable ────────────────


class TestAC504PermanentReversibility:
    """AC-5.4: Before a permanent choice, narrative signals weight and finality.

    Validates the data model layer: PERMANENT reversibility can be stored
    on a ConsequenceChain and is distinguishable from less severe values.
    This unit test covers the data-model aspect only; narrative signaling is
    validated separately from this compliance-focused model test.
    """

    @pytest.mark.asyncio
    async def test_permanent_reversibility_stored_correctly(self) -> None:
        """ConsequenceChain stores Reversibility.PERMANENT correctly."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()
        chain = await svc.create_chain(
            session_id,
            "Permanent decision made",
            reversibility=Reversibility.PERMANENT,
        )
        assert chain.reversibility == Reversibility.PERMANENT

    def test_permanent_is_distinct_from_trivial(self) -> None:
        """PERMANENT and TRIVIAL are distinct Reversibility values."""
        assert Reversibility.PERMANENT != Reversibility.TRIVIAL

    def test_permanent_is_distinct_from_moderate(self) -> None:
        """PERMANENT and MODERATE are distinct Reversibility values."""
        assert Reversibility.PERMANENT != Reversibility.MODERATE

    def test_permanent_is_distinct_from_significant(self) -> None:
        """PERMANENT and SIGNIFICANT are distinct Reversibility values."""
        assert Reversibility.PERMANENT != Reversibility.SIGNIFICANT

    def test_reversibility_enum_ordering(self) -> None:
        """Reversibility enum values are ordered from trivial to permanent."""
        values = list(Reversibility)
        # TRIVIAL is least restrictive, PERMANENT is most restrictive
        assert values.index(Reversibility.TRIVIAL) < values.index(
            Reversibility.PERMANENT
        )

    @pytest.mark.asyncio
    async def test_permanent_chain_distinguishable_from_trivial_chain(
        self,
    ) -> None:
        """Two chains with different reversibility are independently distinguishable."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()
        permanent = await svc.create_chain(
            session_id,
            "Sworn oath",
            reversibility=Reversibility.PERMANENT,
        )
        trivial = await svc.create_chain(
            session_id,
            "Minor action",
            reversibility=Reversibility.TRIVIAL,
        )
        assert permanent.reversibility == Reversibility.PERMANENT
        assert trivial.reversibility == Reversibility.TRIVIAL
        assert permanent.reversibility != trivial.reversibility


# ── AC-5.6: 30 chains evaluated within 300ms ─────────────────────────────────


class TestAC506PerformanceBudget:
    """AC-5.6: 30 active consequence chains evaluated within 300ms.

    Creates 30 chains each with one SHORT_TERM entry, then calls evaluate()
    at turn 5 (within the SHORT_TERM 1–10 turn window). The total time
    must be < 300ms.
    """

    @pytest.mark.asyncio
    async def test_thirty_chains_evaluated_under_300ms(self) -> None:
        """Evaluate 30 chains in < 300ms at turn 5 (SHORT_TERM window)."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()

        for i in range(30):
            entry = ConsequenceEntry(
                chain_id=uuid4(),
                trigger=f"trigger_{i}",
                effect=f"effect_{i}",
                timescale=ConsequenceTimescale.SHORT_TERM,
            )
            await svc.create_chain(
                session_id,
                f"chain_{i}",
                entries=[entry],
                turn=0,
            )

        start = time.perf_counter()
        result = await svc.evaluate(session_id, 5, "continue")
        elapsed_ms = (time.perf_counter() - start) * 1000

        # NFR-5.1: 300ms budget. In-memory evaluation of 30 chains is orders
        # of magnitude below this threshold; the assertion catches regressions
        # that add accidental O(N²) complexity or blocking I/O.
        assert elapsed_ms < 300, (
            f"evaluate() took {elapsed_ms:.1f}ms — must be < 300ms (NFR-5.1)"
        )
        assert len(result.world_changes) == 30


# ── AC-5.7: Session isolation (no cross-contamination) ───────────────────────


class TestAC507SessionIsolation:
    """AC-5.7: Same choice in two playthroughs produces independent chains.

    Creates chains in session A and B separately, then verifies that each
    session's chains are completely isolated from the other's.
    """

    @pytest.mark.asyncio
    async def test_session_a_chains_not_visible_in_session_b(self) -> None:
        """Chains added to session A are invisible from session B."""
        svc = InMemoryConsequenceService()
        session_a = uuid4()
        session_b = uuid4()

        await svc.create_chain(session_a, "Betrayed the king")
        await svc.create_chain(session_a, "Stole the artifact")

        chains_b = await svc.get_active_chains(session_b)
        assert len(chains_b) == 0

    @pytest.mark.asyncio
    async def test_session_b_chains_not_visible_in_session_a(self) -> None:
        """Chains added to session B are invisible from session A."""
        svc = InMemoryConsequenceService()
        session_a = uuid4()
        session_b = uuid4()

        await svc.create_chain(session_b, "Made an alliance")

        chains_a = await svc.get_active_chains(session_a)
        assert len(chains_a) == 0

    @pytest.mark.asyncio
    async def test_chains_remain_independent_after_both_populated(self) -> None:
        """Session A and B chains remain isolated after both are populated."""
        svc = InMemoryConsequenceService()
        session_a = uuid4()
        session_b = uuid4()

        await svc.create_chain(session_a, "A: saved the child")
        await svc.create_chain(session_a, "A: spared the villain")

        await svc.create_chain(session_b, "B: abandoned the quest")

        chains_a = await svc.get_active_chains(session_a)
        chains_b = await svc.get_active_chains(session_b)

        assert len(chains_a) == 2
        assert len(chains_b) == 1
        triggers_a = {c.root_trigger for c in chains_a}
        triggers_b = {c.root_trigger for c in chains_b}
        assert triggers_a.isdisjoint(triggers_b)


# ── AC-5.8: Dormant chains pruned to PRUNED/DORMANT status ───────────────────


class TestAC508DormantPruning:
    """AC-5.8: Chains dormant for 50+ turns are pruned with narrative closure.

    prune_chains() marks a chain as dormant (is_dormant=True, entries become
    DORMANT status) when it has been inactive for >= 50 turns. This serves
    as the "archived" terminal state for the AC.
    """

    @pytest.mark.asyncio
    async def test_chain_marked_dormant_after_50_inactive_turns(self) -> None:
        """Chain inactive for 50+ turns becomes dormant on prune_chains()."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="forgotten vow",
            effect="ancient debt",
            timescale=ConsequenceTimescale.SHORT_TERM,
        )
        chain = await svc.create_chain(
            session_id,
            "Ancient obligation",
            entries=[entry],
            turn=5,
        )
        # 55 - 5 = 50 turns elapsed → hits the dormancy threshold
        await svc.prune_chains(session_id, 55)

        assert chain.is_dormant is True

    @pytest.mark.asyncio
    async def test_dormant_entries_have_dormant_status(self) -> None:
        """Entries on a dormant chain transition to DORMANT status."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="forgotten promise",
            effect="lingering regret",
            timescale=ConsequenceTimescale.LONG_TERM,
        )
        chain = await svc.create_chain(
            session_id,
            "Lost promise",
            entries=[entry],
            turn=5,
        )
        # 55 - 5 = 50 turns elapsed → hits the dormancy threshold
        await svc.prune_chains(session_id, 55)

        assert all(e.status == ConsequenceStatus.DORMANT for e in chain.entries)

    @pytest.mark.asyncio
    async def test_prune_returns_closure_description(self) -> None:
        """prune_chains() returns closure descriptions for archived chains."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="t",
            effect="e",
            timescale=ConsequenceTimescale.SHORT_TERM,
        )
        await svc.create_chain(
            session_id,
            "The lost oath",
            entries=[entry],
            turn=5,
        )
        # 60 - 5 = 55 turns elapsed → dormant, closure generated
        _, closures = await svc.prune_chains(session_id, 60)

        assert "The lost oath" in closures

    @pytest.mark.asyncio
    async def test_chain_not_dormant_before_50_turns(self) -> None:
        """Chain inactive for < 50 turns is NOT marked dormant."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()
        entry = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="recent action",
            effect="ongoing effect",
            timescale=ConsequenceTimescale.SHORT_TERM,
        )
        chain = await svc.create_chain(
            session_id,
            "Recent event",
            entries=[entry],
            turn=5,
        )
        # 30 - 5 = 25 turns elapsed → below the 50-turn dormancy threshold
        await svc.prune_chains(session_id, 30)

        assert chain.is_dormant is False


# ── AC-5.9: 3 branching chains stored and tracked independently ───────────────


class TestAC509BranchingChains:
    """AC-5.9: A choice spawning 3 chains — each independently trackable.

    Creates 3 chains sharing a root concept but with distinct IDs and
    different timescales. Verifies that:
    - All 3 are independently retrievable
    - Resolving one chain does not affect the others
    """

    @pytest.mark.asyncio
    async def test_three_branching_chains_independently_retrievable(
        self,
    ) -> None:
        """Three branching chains are each retrievable by their own IDs."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()

        e1 = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="branch 1 immediate",
            effect="immediate effect",
            timescale=ConsequenceTimescale.IMMEDIATE,
        )
        e2 = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="branch 2 short",
            effect="short-term effect",
            timescale=ConsequenceTimescale.SHORT_TERM,
        )
        e3 = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="branch 3 long",
            effect="long-term effect",
            timescale=ConsequenceTimescale.LONG_TERM,
        )

        chain_a = await svc.create_chain(
            session_id, "Branch A — immediate", entries=[e1], turn=0
        )
        chain_b = await svc.create_chain(
            session_id, "Branch B — short-term", entries=[e2], turn=0
        )
        chain_c = await svc.create_chain(
            session_id, "Branch C — long-term", entries=[e3], turn=0
        )

        active = await svc.get_active_chains(session_id)
        active_ids = {c.id for c in active}

        assert chain_a.id in active_ids
        assert chain_b.id in active_ids
        assert chain_c.id in active_ids

    @pytest.mark.asyncio
    async def test_resolving_one_chain_does_not_affect_others(self) -> None:
        """Resolving chain A leaves B and C active and independent."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()

        e1 = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="branch 1",
            effect="effect 1",
            timescale=ConsequenceTimescale.IMMEDIATE,
        )
        e2 = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="branch 2",
            effect="effect 2",
            timescale=ConsequenceTimescale.SHORT_TERM,
        )
        e3 = ConsequenceEntry(
            chain_id=uuid4(),
            trigger="branch 3",
            effect="effect 3",
            timescale=ConsequenceTimescale.LONG_TERM,
        )

        chain_a = await svc.create_chain(session_id, "Chain A", entries=[e1], turn=0)
        chain_b = await svc.create_chain(session_id, "Chain B", entries=[e2], turn=0)
        chain_c = await svc.create_chain(session_id, "Chain C", entries=[e3], turn=0)

        # Resolve chain A
        await svc.resolve_chain(chain_a.id, turn=5)

        active = await svc.get_active_chains(session_id)
        active_ids = {c.id for c in active}

        assert chain_a.id not in active_ids
        assert chain_b.id in active_ids
        assert chain_c.id in active_ids

    @pytest.mark.asyncio
    async def test_branching_chains_have_distinct_ids(self) -> None:
        """All 3 branching chains have distinct chain IDs."""
        svc = InMemoryConsequenceService()
        session_id = uuid4()

        chains = []
        for i in range(3):
            c = await svc.create_chain(session_id, f"branch_{i}")
            chains.append(c)

        chain_ids = {c.id for c in chains}
        assert len(chain_ids) == 3


# ── AC-5.10: DivergenceScore steering threshold ───────────────────────────────


class TestAC510DivergenceSteering:
    """AC-5.10: When divergence exceeds threshold, narrative references thread.

    The DivergenceScore model provides needs_steering (>= 0.7) and
    needs_anchor_replacement (>= 0.9) properties that drive narrative
    steering logic.
    """

    def test_score_below_threshold_no_steering(self) -> None:
        """DivergenceScore(0.69) → needs_steering is False."""
        ds = DivergenceScore(score=0.69)
        assert ds.needs_steering is False

    def test_score_at_threshold_triggers_steering(self) -> None:
        """DivergenceScore(0.70) → needs_steering is True."""
        ds = DivergenceScore(score=0.70)
        assert ds.needs_steering is True

    def test_score_above_threshold_triggers_steering(self) -> None:
        """DivergenceScore(0.85) → needs_steering is True."""
        ds = DivergenceScore(score=0.85)
        assert ds.needs_steering is True

    def test_score_below_replacement_threshold_no_anchor_replacement(
        self,
    ) -> None:
        """DivergenceScore(0.89) → needs_anchor_replacement is False."""
        ds = DivergenceScore(score=0.89)
        assert ds.needs_anchor_replacement is False

    def test_score_at_replacement_threshold_triggers_replacement(self) -> None:
        """DivergenceScore(0.90) → needs_anchor_replacement is True."""
        ds = DivergenceScore(score=0.90)
        assert ds.needs_anchor_replacement is True

    def test_score_above_replacement_threshold_triggers_replacement(
        self,
    ) -> None:
        """DivergenceScore(1.0) → needs_anchor_replacement is True."""
        ds = DivergenceScore(score=1.0)
        assert ds.needs_anchor_replacement is True

    def test_zero_score_no_steering_or_replacement(self) -> None:
        """DivergenceScore(0.0) → neither steering nor replacement needed."""
        ds = DivergenceScore(score=0.0)
        assert ds.needs_steering is False
        assert ds.needs_anchor_replacement is False

    def test_model_validates_score_bounds(self) -> None:
        """DivergenceScore enforces score in [0.0, 1.0]."""
        import pydantic

        with pytest.raises((pydantic.ValidationError, ValueError)):
            DivergenceScore(score=1.1)

        with pytest.raises((pydantic.ValidationError, ValueError)):
            DivergenceScore(score=-0.1)


# ── Shared: ConsequenceStatus includes PRUNED terminal state ──────────────────


class TestConsequenceStatusTerminalStates:
    """Supporting validation: ConsequenceStatus has required terminal states.

    PRUNED is the terminal state referenced in AC-5.8. DORMANT is the
    intermediate state set by prune_chains() when a chain goes inactive.
    """

    def test_pruned_status_exists(self) -> None:
        """ConsequenceStatus.PRUNED is defined."""
        assert ConsequenceStatus.PRUNED == "pruned"

    def test_dormant_status_exists(self) -> None:
        """ConsequenceStatus.DORMANT is defined."""
        assert ConsequenceStatus.DORMANT == "dormant"

    def test_chain_with_pruned_entries_is_resolved(self) -> None:
        """A chain whose all entries are PRUNED is considered resolved."""
        chain = ConsequenceChain(
            id=uuid4(),
            session_id=uuid4(),
            root_trigger="pruned chain",
            entries=[
                ConsequenceEntry(
                    chain_id=uuid4(),
                    trigger="t",
                    effect="e",
                    status=ConsequenceStatus.PRUNED,
                )
            ],
        )
        assert chain.is_resolved is True
