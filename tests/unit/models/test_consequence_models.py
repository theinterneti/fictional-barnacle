"""Tests for consequence chain domain models."""

from uuid import uuid4

from tta.models.consequence import (
    MAX_ACTIVE_CHAINS,
    ConsequenceChain,
    ConsequenceEntry,
    ConsequenceStatus,
    ConsequenceTimescale,
    ConsequenceVisibility,
    DivergenceScore,
    NarrativeAnchor,
)


def _entry(chain_id=None, **overrides: object) -> ConsequenceEntry:
    defaults: dict = {
        "chain_id": chain_id or uuid4(),
        "trigger": "Player insulted the merchant",
        "effect": "Merchant raises prices",
    }
    return ConsequenceEntry(**{**defaults, **overrides})


def _chain(session_id=None, **overrides: object) -> ConsequenceChain:
    defaults: dict = {
        "session_id": session_id or uuid4(),
        "root_trigger": "Insulted the merchant",
    }
    return ConsequenceChain(**{**defaults, **overrides})


class TestConsequenceTimescale:
    """S05 FR-3: Three timescales."""

    def test_all_timescales(self) -> None:
        expected = {"immediate", "short_term", "long_term"}
        assert {t.value for t in ConsequenceTimescale} == expected


class TestConsequenceVisibility:
    """S05 FR-7: Visibility spectrum."""

    def test_all_visibilities(self) -> None:
        expected = {"visible", "foreshadowed", "hidden"}
        assert {v.value for v in ConsequenceVisibility} == expected


class TestConsequenceStatus:
    """S05 FR-3, FR-8: Lifecycle statuses."""

    def test_all_statuses(self) -> None:
        expected = {"pending", "active", "resolved", "dormant", "pruned"}
        assert {s.value for s in ConsequenceStatus} == expected


class TestConsequenceEntry:
    """S05 FR-3: Individual consequence node."""

    def test_defaults(self) -> None:
        entry = _entry()
        assert entry.visibility == ConsequenceVisibility.VISIBLE
        assert entry.status == ConsequenceStatus.PENDING
        assert entry.timescale == ConsequenceTimescale.SHORT_TERM
        assert entry.parent_ids == []
        assert entry.turn_resolved is None

    def test_hidden_entry(self) -> None:
        entry = _entry(visibility=ConsequenceVisibility.HIDDEN)
        assert entry.visibility == ConsequenceVisibility.HIDDEN

    def test_entry_has_unique_id(self) -> None:
        a = _entry()
        b = _entry()
        assert a.id != b.id

    def test_parent_ids_for_merging(self) -> None:
        parent1 = _entry()
        parent2 = _entry()
        merged = _entry(parent_ids=[parent1.id, parent2.id])
        assert len(merged.parent_ids) == 2


class TestConsequenceChain:
    """S05 FR-3: Linked consequence chain."""

    def test_empty_chain(self) -> None:
        chain = _chain()
        assert chain.entries == []
        assert chain.active_entries == []
        assert not chain.is_resolved

    def test_chain_with_entries(self) -> None:
        chain = _chain()
        e1 = _entry(chain_id=chain.id, status=ConsequenceStatus.ACTIVE)
        e2 = _entry(chain_id=chain.id, status=ConsequenceStatus.PENDING)
        chain.entries = [e1, e2]
        assert len(chain.active_entries) == 2

    def test_resolved_chain(self) -> None:
        chain = _chain()
        e1 = _entry(chain_id=chain.id, status=ConsequenceStatus.RESOLVED)
        e2 = _entry(chain_id=chain.id, status=ConsequenceStatus.PRUNED)
        chain.entries = [e1, e2]
        assert chain.is_resolved

    def test_partially_resolved_chain(self) -> None:
        chain = _chain()
        e1 = _entry(chain_id=chain.id, status=ConsequenceStatus.RESOLVED)
        e2 = _entry(chain_id=chain.id, status=ConsequenceStatus.PENDING)
        chain.entries = [e1, e2]
        assert not chain.is_resolved

    def test_parent_chain_for_branching(self) -> None:
        parent = _chain()
        child = _chain(parent_chain_id=parent.id)
        assert child.parent_chain_id == parent.id

    def test_dormant_flag(self) -> None:
        chain = _chain(is_dormant=True)
        assert chain.is_dormant

    def test_max_active_chains_constant(self) -> None:
        assert MAX_ACTIVE_CHAINS == 30


class TestNarrativeAnchor:
    """S05 FR-4: Key story events the narrative gravitates toward."""

    def test_defaults(self) -> None:
        anchor = NarrativeAnchor(
            session_id=uuid4(),
            description="The merchant guild confrontation",
        )
        assert anchor.is_active
        assert not anchor.is_reached
        assert anchor.replacement_id is None
        assert anchor.target_turn is None

    def test_reached_anchor(self) -> None:
        anchor = NarrativeAnchor(
            session_id=uuid4(),
            description="Final battle",
            is_reached=True,
            is_active=False,
        )
        assert anchor.is_reached
        assert not anchor.is_active

    def test_replaced_anchor(self) -> None:
        old = NarrativeAnchor(session_id=uuid4(), description="Original event")
        new = NarrativeAnchor(
            session_id=old.session_id, description="Replacement event"
        )
        old_updated = old.model_copy(
            update={"replacement_id": new.id, "is_active": False}
        )
        assert old_updated.replacement_id == new.id
        assert not old_updated.is_active


class TestDivergenceScore:
    """S05 FR-4: Divergence measurement."""

    def test_defaults(self) -> None:
        ds = DivergenceScore()
        assert ds.score == 0.0
        assert not ds.needs_steering
        assert not ds.needs_anchor_replacement

    def test_high_divergence_triggers_steering(self) -> None:
        ds = DivergenceScore(score=0.75)
        assert ds.needs_steering
        assert not ds.needs_anchor_replacement

    def test_extreme_divergence_triggers_replacement(self) -> None:
        ds = DivergenceScore(score=0.95)
        assert ds.needs_steering
        assert ds.needs_anchor_replacement

    def test_boundary_at_0_7(self) -> None:
        assert DivergenceScore(score=0.69).needs_steering is False
        assert DivergenceScore(score=0.70).needs_steering is True

    def test_boundary_at_0_9(self) -> None:
        assert DivergenceScore(score=0.89).needs_anchor_replacement is False
        assert DivergenceScore(score=0.90).needs_anchor_replacement is True

    def test_factors_stored(self) -> None:
        ds = DivergenceScore(
            score=0.5,
            factors={"chain_deviation": 0.3, "anchor_distance": 0.7},
        )
        assert ds.factors["chain_deviation"] == 0.3
