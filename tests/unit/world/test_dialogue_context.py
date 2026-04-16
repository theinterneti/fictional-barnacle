"""Tests for NPC dialogue context assembly (S06 FR-6)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tta.models.world import (
    NPC,
    NPCDialogueContext,
    NPCRelationship,
    NPCTier,
    RelationshipDimensions,
)
from tta.world.dialogue import (
    GOALS_TRUST_THRESHOLD,
    KNOWLEDGE_TRUST_THRESHOLD,
    build_dialogue_context,
    build_dialogue_contexts_for_location,
)
from tta.world.relationship_service import InMemoryRelationshipService

# -- Fixtures --


@pytest.fixture
def session_id():
    return uuid4()


@pytest.fixture
def player_id():
    return "player"


def _make_npc(
    *,
    npc_id: str = "npc-1",
    name: str = "Ada",
    tier: NPCTier = NPCTier.KEY,
    personality: str | None = "curious",
    voice: str | None = "soft-spoken",
    knowledge: str | None = "knows the forest secrets",
    goals: str | None = "find the lost gem",
    occupation: str | None = "herbalist",
    mannerisms: str | None = "fidgets with rings",
) -> NPC:
    return NPC(
        id=npc_id,
        name=name,
        description=f"{name} the character",
        disposition="neutral",
        tier=tier,
        traits=["brave", "kind"],
        personality=personality,
        voice=voice,
        knowledge_summary=knowledge,
        goals_short=goals,
        occupation=occupation,
        mannerisms=mannerisms,
    )


# -- build_dialogue_context tests --


class TestBuildDialogueContextNoRelationship:
    """Context with no relationship service."""

    @pytest.mark.asyncio
    async def test_returns_context_with_defaults(self, session_id, player_id):
        npc = _make_npc()
        ctx = await build_dialogue_context(npc, session_id, player_id)

        assert isinstance(ctx, NPCDialogueContext)
        assert ctx.npc_id == "npc-1"
        assert ctx.npc_name == "Ada"
        assert ctx.personality == "curious"
        assert ctx.voice == "soft-spoken"
        assert ctx.relationship_label == "neutral"
        assert ctx.relationship_trust == 0
        assert ctx.relationship_affinity == 0

    @pytest.mark.asyncio
    async def test_knowledge_hidden_at_zero_trust(self, session_id, player_id):
        """Trust 0 < KNOWLEDGE_TRUST_THRESHOLD → knowledge hidden."""
        npc = _make_npc()
        ctx = await build_dialogue_context(npc, session_id, player_id)
        assert ctx.knowledge_summary is None

    @pytest.mark.asyncio
    async def test_goals_hidden_at_zero_trust(self, session_id, player_id):
        """Trust 0 < GOALS_TRUST_THRESHOLD → goals hidden."""
        npc = _make_npc()
        ctx = await build_dialogue_context(npc, session_id, player_id)
        assert ctx.goals_short is None


class TestBuildDialogueContextWithRelationship:
    """Context with relationship data."""

    @pytest.mark.asyncio
    async def test_relationship_values_populated(self, session_id, player_id):
        npc = _make_npc()
        svc = InMemoryRelationshipService()
        rel = NPCRelationship(
            source_id=player_id,
            target_id=npc.id,
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=40, affinity=25),
        )
        await svc.set_relationship(session_id, rel)

        ctx = await build_dialogue_context(npc, session_id, player_id, svc)
        assert ctx.relationship_trust == 40
        assert ctx.relationship_affinity == 25
        assert ctx.relationship_label == "warm"

    @pytest.mark.asyncio
    async def test_knowledge_revealed_above_threshold(self, session_id, player_id):
        npc = _make_npc()
        svc = InMemoryRelationshipService()
        rel = NPCRelationship(
            source_id=player_id,
            target_id=npc.id,
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=KNOWLEDGE_TRUST_THRESHOLD),
        )
        await svc.set_relationship(session_id, rel)

        ctx = await build_dialogue_context(npc, session_id, player_id, svc)
        assert ctx.knowledge_summary == "knows the forest secrets"

    @pytest.mark.asyncio
    async def test_knowledge_hidden_below_threshold(self, session_id, player_id):
        npc = _make_npc()
        svc = InMemoryRelationshipService()
        rel = NPCRelationship(
            source_id=player_id,
            target_id=npc.id,
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=KNOWLEDGE_TRUST_THRESHOLD - 1),
        )
        await svc.set_relationship(session_id, rel)

        ctx = await build_dialogue_context(npc, session_id, player_id, svc)
        assert ctx.knowledge_summary is None

    @pytest.mark.asyncio
    async def test_goals_revealed_above_threshold(self, session_id, player_id):
        npc = _make_npc()
        svc = InMemoryRelationshipService()
        rel = NPCRelationship(
            source_id=player_id,
            target_id=npc.id,
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=GOALS_TRUST_THRESHOLD),
        )
        await svc.set_relationship(session_id, rel)

        ctx = await build_dialogue_context(npc, session_id, player_id, svc)
        assert ctx.goals_short == "find the lost gem"

    @pytest.mark.asyncio
    async def test_goals_hidden_below_threshold(self, session_id, player_id):
        npc = _make_npc()
        svc = InMemoryRelationshipService()
        rel = NPCRelationship(
            source_id=player_id,
            target_id=npc.id,
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=GOALS_TRUST_THRESHOLD - 1),
        )
        await svc.set_relationship(session_id, rel)

        ctx = await build_dialogue_context(npc, session_id, player_id, svc)
        assert ctx.goals_short is None

    @pytest.mark.asyncio
    async def test_hostile_label_with_negative_trust(self, session_id, player_id):
        npc = _make_npc()
        svc = InMemoryRelationshipService()
        rel = NPCRelationship(
            source_id=player_id,
            target_id=npc.id,
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=-80),
        )
        await svc.set_relationship(session_id, rel)

        ctx = await build_dialogue_context(npc, session_id, player_id, svc)
        assert ctx.relationship_label == "hostile"

    @pytest.mark.asyncio
    async def test_no_relationship_record_returns_defaults(self, session_id, player_id):
        """Service exists but no relationship for this pair."""
        npc = _make_npc()
        svc = InMemoryRelationshipService()

        ctx = await build_dialogue_context(npc, session_id, player_id, svc)
        assert ctx.relationship_trust == 0
        assert ctx.knowledge_summary is None


# -- build_dialogue_contexts_for_location tests --


class TestLocationDialogueContexts:
    """Test batch context building for location NPCs."""

    @pytest.mark.asyncio
    async def test_background_npc_gets_minimal_context(self, session_id, player_id):
        bg = _make_npc(
            npc_id="bg-1",
            name="Crowd Member",
            tier=NPCTier.BACKGROUND,
        )
        results = await build_dialogue_contexts_for_location(
            [bg], session_id, player_id
        )
        assert len(results) == 1
        ctx = results[0]
        assert ctx["npc_id"] == "bg-1"
        assert ctx["npc_name"] == "Crowd Member"
        # Background NPCs should NOT have personality/voice
        assert "personality" not in ctx
        assert "voice" not in ctx

    @pytest.mark.asyncio
    async def test_key_npc_gets_full_context(self, session_id, player_id):
        key = _make_npc(tier=NPCTier.KEY)
        results = await build_dialogue_contexts_for_location(
            [key], session_id, player_id
        )
        assert len(results) == 1
        ctx = results[0]
        assert ctx["personality"] == "curious"
        assert ctx["voice"] == "soft-spoken"

    @pytest.mark.asyncio
    async def test_mixed_tiers_returns_all(self, session_id, player_id):
        key = _make_npc(npc_id="k1", tier=NPCTier.KEY)
        supporting = _make_npc(npc_id="s1", name="Guard", tier=NPCTier.SUPPORTING)
        bg = _make_npc(npc_id="bg1", name="Bystander", tier=NPCTier.BACKGROUND)

        results = await build_dialogue_contexts_for_location(
            [key, supporting, bg], session_id, player_id
        )
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_empty_npc_list(self, session_id, player_id):
        results = await build_dialogue_contexts_for_location([], session_id, player_id)
        assert results == []

    @pytest.mark.asyncio
    async def test_with_relationship_service(self, session_id, player_id):
        npc = _make_npc()
        svc = InMemoryRelationshipService()
        rel = NPCRelationship(
            source_id=player_id,
            target_id=npc.id,
            session_id=str(session_id),
            dimensions=RelationshipDimensions(trust=60, affinity=40),
        )
        await svc.set_relationship(session_id, rel)

        results = await build_dialogue_contexts_for_location(
            [npc], session_id, player_id, svc
        )
        ctx = results[0]
        assert ctx["relationship_trust"] == 60
        assert ctx["relationship_label"] == "loyal"


# -- Context stage integration tests --


class TestContextStageDialogueEnrichment:
    """Test that context_stage enriches with dialogue contexts."""

    @pytest.mark.asyncio
    async def test_enrichment_adds_key_to_context(self):
        """Verify _enrich_npc_dialogue adds npc_dialogue_contexts."""
        from unittest.mock import MagicMock

        from tta.pipeline.stages.context import _enrich_npc_dialogue

        npc = _make_npc()
        world_context = {
            "npcs_present": [npc.model_dump()],
            "location": {},
        }

        state = MagicMock()
        state.session_id = uuid4()
        deps = MagicMock()
        deps.relationship_service = None

        result = await _enrich_npc_dialogue(world_context, state, deps)
        assert "npc_dialogue_contexts" in result
        assert len(result["npc_dialogue_contexts"]) == 1

    @pytest.mark.asyncio
    async def test_enrichment_skips_empty_npcs(self):
        from unittest.mock import MagicMock

        from tta.pipeline.stages.context import _enrich_npc_dialogue

        world_context = {"npcs_present": [], "location": {}}
        state = MagicMock()
        state.session_id = uuid4()
        deps = MagicMock()

        result = await _enrich_npc_dialogue(world_context, state, deps)
        assert "npc_dialogue_contexts" not in result

    @pytest.mark.asyncio
    async def test_enrichment_skips_when_no_npcs_key(self):
        from unittest.mock import MagicMock

        from tta.pipeline.stages.context import _enrich_npc_dialogue

        world_context = {"location": {}}
        state = MagicMock()
        state.session_id = uuid4()
        deps = MagicMock()

        result = await _enrich_npc_dialogue(world_context, state, deps)
        assert "npc_dialogue_contexts" not in result
