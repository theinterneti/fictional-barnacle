"""Tests for RelationshipService protocol and InMemoryRelationshipService."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tta.models.world import (
    NPCRelationship,
    RelationshipChange,
    RelationshipDimensions,
)
from tta.world.relationship_service import (
    COMPANION_AFFINITY_THRESHOLD,
    COMPANION_TRUST_THRESHOLD,
    InMemoryRelationshipService,
    RelationshipService,
)

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def svc() -> InMemoryRelationshipService:
    return InMemoryRelationshipService()


@pytest.fixture
def session_id():
    return uuid4()


# ── Protocol conformance ─────────────────────────────────────────


class TestProtocolConformance:
    def test_in_memory_is_relationship_service(self) -> None:
        assert isinstance(InMemoryRelationshipService(), RelationshipService)


# ── CRUD ─────────────────────────────────────────────────────────


class TestGetRelationship:
    async def test_returns_none_when_absent(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        result = await svc.get_relationship(session_id, "npc-a", "npc-b")
        assert result is None

    async def test_returns_relationship_after_set(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        rel = NPCRelationship(
            source_id="npc-a",
            target_id="npc-b",
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=25, affinity=10),
        )
        await svc.set_relationship(session_id, rel)
        result = await svc.get_relationship(session_id, "npc-a", "npc-b")
        assert result is not None
        assert result.dimensions.trust == 25
        assert result.dimensions.affinity == 10

    async def test_returns_deep_copy(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        """Mutating returned object should not affect stored data."""
        rel = NPCRelationship(
            source_id="a",
            target_id="b",
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=10),
        )
        await svc.set_relationship(session_id, rel)
        fetched = await svc.get_relationship(session_id, "a", "b")
        assert fetched is not None
        fetched.dimensions.trust = 999
        refetch = await svc.get_relationship(session_id, "a", "b")
        assert refetch is not None
        assert refetch.dimensions.trust == 10


class TestGetRelationshipsFor:
    async def test_empty_when_no_relationships(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        result = await svc.get_relationships_for(session_id, "npc-a")
        assert result == []

    async def test_returns_outgoing_only(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        """Should return relationships where entity is source."""
        await svc.set_relationship(
            session_id,
            NPCRelationship(
                source_id="npc-a",
                target_id="npc-b",
                session_id=str(session_id),
            ),
        )
        await svc.set_relationship(
            session_id,
            NPCRelationship(
                source_id="npc-b",
                target_id="npc-a",
                session_id=str(session_id),
            ),
        )
        rels = await svc.get_relationships_for(session_id, "npc-a")
        assert len(rels) == 1
        assert rels[0].target_id == "npc-b"


class TestSetRelationship:
    async def test_overwrites_existing(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        rel1 = NPCRelationship(
            source_id="a",
            target_id="b",
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=10),
        )
        rel2 = NPCRelationship(
            source_id="a",
            target_id="b",
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=50),
        )
        await svc.set_relationship(session_id, rel1)
        await svc.set_relationship(session_id, rel2)
        result = await svc.get_relationship(session_id, "a", "b")
        assert result is not None
        assert result.dimensions.trust == 50


# ── Update with clamping ─────────────────────────────────────────


class TestUpdateRelationship:
    async def test_creates_when_absent(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        change = RelationshipChange(trust=10, affinity=5)
        result = await svc.update_relationship(session_id, "a", "b", change)
        assert result.dimensions.trust == 10
        assert result.dimensions.affinity == 5

    async def test_accumulates_changes(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        c1 = RelationshipChange(trust=10)
        c2 = RelationshipChange(trust=10)
        await svc.update_relationship(session_id, "a", "b", c1)
        result = await svc.update_relationship(session_id, "a", "b", c2)
        assert result.dimensions.trust == 20

    async def test_normal_clamp_positive(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        """Normal change clamped to ±15."""
        change = RelationshipChange(trust=50)  # exceeds ±15
        result = await svc.update_relationship(session_id, "a", "b", change)
        assert result.dimensions.trust == 15

    async def test_normal_clamp_negative(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        change = RelationshipChange(trust=-50)
        result = await svc.update_relationship(session_id, "a", "b", change)
        assert result.dimensions.trust == -15

    async def test_dramatic_clamp(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        """Dramatic events clamped to ±30."""
        change = RelationshipChange(trust=100, dramatic=True)
        result = await svc.update_relationship(session_id, "a", "b", change)
        assert result.dimensions.trust == 30

    async def test_dimension_range_clamp(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        """Trust clamped to [-100, +100], fear to [0, +100]."""
        # First set trust near max
        await svc.set_relationship(
            session_id,
            NPCRelationship(
                source_id="a",
                target_id="b",
                session_id=str(session_id),
                dimensions=RelationshipDimensions(trust=95),
            ),
        )
        change = RelationshipChange(trust=15)
        result = await svc.update_relationship(session_id, "a", "b", change)
        assert result.dimensions.trust <= 100

    async def test_fear_cannot_go_negative(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        """Fear range is [0, +100], not [-100, +100]."""
        change = RelationshipChange(fear=-50)
        result = await svc.update_relationship(session_id, "a", "b", change)
        assert result.dimensions.fear >= 0


# ── Companion eligibility ────────────────────────────────────────


class TestCompanionEligibility:
    async def test_eligible_when_thresholds_met(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        rel = NPCRelationship(
            source_id="player",
            target_id="npc-1",
            session_id=str(session_id),
            dimensions=RelationshipDimensions(
                trust=COMPANION_TRUST_THRESHOLD + 1,
                affinity=COMPANION_AFFINITY_THRESHOLD + 1,
            ),
        )
        await svc.set_relationship(session_id, rel)
        assert await svc.check_companion_eligible(session_id, "player", "npc-1")

    async def test_not_eligible_when_trust_low(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        rel = NPCRelationship(
            source_id="player",
            target_id="npc-1",
            session_id=str(session_id),
            dimensions=RelationshipDimensions(
                trust=COMPANION_TRUST_THRESHOLD - 1,
                affinity=COMPANION_AFFINITY_THRESHOLD + 1,
            ),
        )
        await svc.set_relationship(session_id, rel)
        assert not await svc.check_companion_eligible(session_id, "player", "npc-1")

    async def test_not_eligible_when_affinity_low(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        rel = NPCRelationship(
            source_id="player",
            target_id="npc-1",
            session_id=str(session_id),
            dimensions=RelationshipDimensions(
                trust=COMPANION_TRUST_THRESHOLD + 1,
                affinity=COMPANION_AFFINITY_THRESHOLD - 1,
            ),
        )
        await svc.set_relationship(session_id, rel)
        assert not await svc.check_companion_eligible(session_id, "player", "npc-1")

    async def test_not_eligible_at_exact_threshold(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        """Threshold is strict greater-than (>), not >=."""
        rel = NPCRelationship(
            source_id="player",
            target_id="npc-1",
            session_id=str(session_id),
            dimensions=RelationshipDimensions(
                trust=COMPANION_TRUST_THRESHOLD,
                affinity=COMPANION_AFFINITY_THRESHOLD,
            ),
        )
        await svc.set_relationship(session_id, rel)
        assert not await svc.check_companion_eligible(session_id, "player", "npc-1")

    async def test_not_eligible_when_no_relationship(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        assert not await svc.check_companion_eligible(session_id, "player", "npc-1")


# ── NPC↔NPC relationships ───────────────────────────────────────


class TestNPCToNPCRelationships:
    async def test_npc_npc_relationship(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        """Non-player relationships work the same way."""
        rel = NPCRelationship(
            source_id="npc-1",
            target_id="npc-2",
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=20, respect=30),
        )
        await svc.set_relationship(session_id, rel)
        result = await svc.get_relationship(session_id, "npc-1", "npc-2")
        assert result is not None
        assert result.dimensions.trust == 20
        assert result.dimensions.respect == 30

    async def test_directional(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        """A→B and B→A are independent relationships."""
        await svc.set_relationship(
            session_id,
            NPCRelationship(
                source_id="npc-1",
                target_id="npc-2",
                session_id=str(session_id),
                dimensions=RelationshipDimensions(trust=50),
            ),
        )
        reverse = await svc.get_relationship(session_id, "npc-2", "npc-1")
        assert reverse is None


# ── Session cleanup ──────────────────────────────────────────────


class TestSessionCleanup:
    async def test_removes_all_session_relationships(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        await svc.set_relationship(
            session_id,
            NPCRelationship(
                source_id="a",
                target_id="b",
                session_id=str(session_id),
            ),
        )
        await svc.set_relationship(
            session_id,
            NPCRelationship(
                source_id="c",
                target_id="d",
                session_id=str(session_id),
            ),
        )
        await svc.cleanup_session(session_id)
        assert await svc.get_relationship(session_id, "a", "b") is None
        assert await svc.get_relationship(session_id, "c", "d") is None

    async def test_does_not_affect_other_sessions(
        self, svc: InMemoryRelationshipService, session_id
    ) -> None:
        other_session = uuid4()
        await svc.set_relationship(
            session_id,
            NPCRelationship(
                source_id="a",
                target_id="b",
                session_id=str(session_id),
            ),
        )
        await svc.set_relationship(
            other_session,
            NPCRelationship(
                source_id="a",
                target_id="b",
                session_id=str(other_session),
            ),
        )
        await svc.cleanup_session(session_id)
        result = await svc.get_relationship(other_session, "a", "b")
        assert result is not None


# ── WorldChange handlers ─────────────────────────────────────────


class TestWorldChangeHandlers:
    """Verify RELATIONSHIP_CHANGED and NPC_TIER_CHANGED in memory service."""

    async def test_npc_tier_changed(self) -> None:
        from tta.models.world import (
            NPC,
            NPCTier,
            WorldChange,
            WorldChangeType,
        )
        from tta.world.memory_service import InMemoryWorldService

        svc = InMemoryWorldService()
        sid = uuid4()
        s = str(sid)
        # Seed an NPC
        svc._npcs[s] = {
            "npc-1": (
                NPC(
                    id="npc-1",
                    name="Test",
                    description="A test NPC",
                    disposition="neutral",
                    tier=NPCTier.BACKGROUND,
                ),
                "loc-1",
            )
        }
        change = WorldChange(
            type=WorldChangeType.NPC_TIER_CHANGED,
            entity_id="npc-1",
            payload={"tier": "key"},
        )
        await svc.apply_world_changes(sid, [change])
        npc, _ = svc._npcs[s]["npc-1"]
        assert npc.tier == "key"

    async def test_relationship_changed_is_noop(self) -> None:
        from tta.models.world import WorldChange, WorldChangeType
        from tta.world.memory_service import InMemoryWorldService

        svc = InMemoryWorldService()
        sid = uuid4()
        change = WorldChange(
            type=WorldChangeType.RELATIONSHIP_CHANGED,
            entity_id="npc-1",
            payload={"trust": 10},
        )
        # Should not raise
        await svc.apply_world_changes(sid, [change])
