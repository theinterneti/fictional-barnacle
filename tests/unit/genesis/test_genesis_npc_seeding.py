"""Tests for Genesis NPC seeding — tier-aware enrichment and relationships."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from tta.genesis.genesis_lite import (
    _build_template_summary,
    _default_enrichment,
)
from tta.models.world import (
    NPC,
    NPCTier,
    TemplateLocation,
    TemplateMetadata,
    TemplateNPC,
    TemplateRegion,
    TemplateRelationship,
    WorldSeed,
    WorldTemplate,
)
from tta.world.memory_service import InMemoryWorldService

# -- Helpers ---------------------------------------------------------


def _tiered_template() -> WorldTemplate:
    """Template with key, supporting, and background NPCs."""
    return WorldTemplate(
        metadata=TemplateMetadata(
            template_key="test_tiered",
            display_name="Tiered Village",
            tags=["village"],
            compatible_tones=["mysterious"],
            location_count=1,
            npc_count=3,
        ),
        regions=[
            TemplateRegion(
                key="center",
                archetype="village center",
            ),
        ],
        locations=[
            TemplateLocation(
                key="plaza",
                region_key="center",
                type="exterior",
                archetype="cobbled plaza",
                is_starting_location=True,
            ),
        ],
        connections=[],
        npcs=[
            TemplateNPC(
                key="elder",
                location_key="plaza",
                role="quest_giver",
                archetype="wise_elder",
                tier=NPCTier.KEY,
                traits=["wise", "stern"],
                goals_hint="protect the village",
                backstory_hint="Once a great warrior",
            ),
            TemplateNPC(
                key="smith",
                location_key="plaza",
                role="merchant",
                archetype="friendly_smith",
                tier=NPCTier.SUPPORTING,
                traits=["diligent"],
                goals_hint="forge the finest blade",
            ),
            TemplateNPC(
                key="villager",
                location_key="plaza",
                role="ambient",
                archetype="passing_villager",
                tier=NPCTier.BACKGROUND,
            ),
        ],
        items=[],
        knowledge=[],
        relationships=[
            TemplateRelationship(
                source_npc_key="elder",
                target_npc_key="smith",
                trust=40,
                affinity=30,
                respect=50,
                fear=0,
                familiarity=80,
            ),
        ],
    )


def _make_world_seed(
    template: WorldTemplate | None = None,
    flavor_text: dict | None = None,
) -> WorldSeed:
    if template is None:
        template = _tiered_template()
    return WorldSeed(
        template=template,
        tone="mysterious",
        tech_level="medieval",
        magic_presence="low",
        world_scale="village",
        defining_detail="an ancient curse",
        character_name="Kael",
        character_concept="wandering healer",
        flavor_text=flavor_text or {},
    )


def _find_npc_by_template_key(
    svc: InMemoryWorldService,
    session_id: str,
    template_key: str,
) -> NPC | None:
    """Look up an NPC by template_key in the service's internal store."""
    for npc, _loc in svc._npcs.get(session_id, {}).values():
        if npc.template_key == template_key:
            return npc
    return None


# -- TemplateRelationship validation ---------------------------------


class TestTemplateRelationship:
    def test_valid_relationship(self):
        rel = TemplateRelationship(
            source_npc_key="a",
            target_npc_key="b",
            trust=50,
            affinity=-30,
            respect=80,
            fear=10,
            familiarity=60,
        )
        assert rel.trust == 50
        assert rel.fear == 10

    def test_trust_out_of_range(self):
        with pytest.raises(ValueError):
            TemplateRelationship(
                source_npc_key="a",
                target_npc_key="b",
                trust=101,
            )

    def test_fear_negative_rejected(self):
        with pytest.raises(ValueError):
            TemplateRelationship(
                source_npc_key="a",
                target_npc_key="b",
                fear=-1,
            )

    def test_familiarity_over_100_rejected(self):
        with pytest.raises(ValueError):
            TemplateRelationship(
                source_npc_key="a",
                target_npc_key="b",
                familiarity=101,
            )

    def test_defaults_are_zero(self):
        rel = TemplateRelationship(
            source_npc_key="a",
            target_npc_key="b",
        )
        assert rel.trust == 0
        assert rel.affinity == 0
        assert rel.respect == 0
        assert rel.fear == 0
        assert rel.familiarity == 0


# -- _build_template_summary includes tier/traits -------------------


class TestBuildTemplateSummary:
    def test_key_npc_has_tier_and_traits(self):
        tmpl = _tiered_template()
        raw = _build_template_summary(tmpl)
        data = json.loads(raw)
        elder = next(n for n in data["npcs"] if n["key"] == "elder")
        assert elder["tier"] == "key"
        assert elder["traits"] == ["wise", "stern"]
        assert elder["goals_hint"] == "protect the village"
        assert elder["backstory_hint"] == "Once a great warrior"

    def test_background_npc_omits_empty_fields(self):
        tmpl = _tiered_template()
        raw = _build_template_summary(tmpl)
        data = json.loads(raw)
        villager = next(n for n in data["npcs"] if n["key"] == "villager")
        assert "traits" not in villager
        assert "goals_hint" not in villager
        assert "backstory_hint" not in villager

    def test_supporting_npc_includes_goals(self):
        tmpl = _tiered_template()
        raw = _build_template_summary(tmpl)
        data = json.loads(raw)
        smith = next(n for n in data["npcs"] if n["key"] == "smith")
        assert smith["tier"] == "supporting"
        assert smith["goals_hint"] == "forge the finest blade"


# -- _default_enrichment tier-appropriate fallbacks ------------------


class TestDefaultEnrichmentTiers:
    def test_key_npc_gets_rich_defaults(self):
        tmpl = _tiered_template()
        enriched = _default_enrichment(tmpl)
        elder = next(e for e in enriched.npcs if e.key == "elder")
        assert elder.voice is not None
        assert elder.occupation is not None
        assert elder.goals_short is not None
        assert elder.backstory_summary is not None
        assert elder.personality == "complex and driven"
        assert elder.dialogue_style == "distinctive and memorable"

    def test_supporting_npc_gets_moderate_defaults(self):
        tmpl = _tiered_template()
        enriched = _default_enrichment(tmpl)
        smith = next(e for e in enriched.npcs if e.key == "smith")
        assert smith.voice is not None
        assert smith.goals_short is not None
        assert smith.backstory_summary is None
        assert smith.personality == "helpful and grounded"

    def test_background_npc_gets_minimal_defaults(self):
        tmpl = _tiered_template()
        enriched = _default_enrichment(tmpl)
        villager = next(e for e in enriched.npcs if e.key == "villager")
        assert villager.voice is None
        assert villager.occupation is None
        assert villager.goals_short is None
        assert villager.backstory_summary is None
        assert villager.personality == "reserved"
        assert villager.dialogue_style == "plain spoken"


# -- Memory service enrichment application --------------------------


class TestMemoryServiceNPCEnrichment:
    async def test_enrichment_applied_from_flavor_text(self):
        svc = InMemoryWorldService()
        tmpl = _tiered_template()
        flavor = {
            "npcs": [
                {
                    "key": "elder",
                    "name": "Elder Theron",
                    "description": "A weathered leader",
                    "personality": "stoic and wise",
                    "dialogue_style": "formal",
                    "voice": "deep baritone",
                    "occupation": "village chief",
                    "goals_short": "defend the keep",
                    "backstory_summary": "War veteran",
                },
            ],
        }
        seed = _make_world_seed(tmpl, flavor_text=flavor)
        session_id = uuid4()
        await svc.create_world_graph(session_id, seed)

        elder = _find_npc_by_template_key(svc, str(session_id), "elder")
        assert elder is not None
        assert elder.name == "Elder Theron"
        assert elder.personality == "stoic and wise"
        assert elder.voice == "deep baritone"
        assert elder.occupation == "village chief"
        assert elder.goals_short == "defend the keep"
        assert elder.backstory == "War veteran"

    async def test_no_flavor_text_uses_template_defaults(self):
        svc = InMemoryWorldService()
        seed = _make_world_seed(flavor_text=None)
        session_id = uuid4()
        await svc.create_world_graph(session_id, seed)

        elder = _find_npc_by_template_key(svc, str(session_id), "elder")
        assert elder is not None
        assert elder.name == "elder"
        assert elder.personality is None

    async def test_partial_flavor_text_applies(self):
        svc = InMemoryWorldService()
        tmpl = _tiered_template()
        flavor = {
            "npcs": [
                {
                    "key": "smith",
                    "name": "Iron Mira",
                    "description": "A skilled artisan",
                    "personality": "cheerful",
                },
            ],
        }
        seed = _make_world_seed(tmpl, flavor_text=flavor)
        session_id = uuid4()
        await svc.create_world_graph(session_id, seed)

        smith = _find_npc_by_template_key(svc, str(session_id), "smith")
        assert smith is not None
        assert smith.name == "Iron Mira"
        assert smith.personality == "cheerful"
        assert smith.voice is None

    async def test_template_relationships_field(self):
        tmpl = _tiered_template()
        assert len(tmpl.relationships) == 1
        rel = tmpl.relationships[0]
        assert rel.source_npc_key == "elder"
        assert rel.target_npc_key == "smith"
        assert rel.trust == 40


class TestWorldTemplateRelationshipsField:
    def test_empty_by_default(self):
        tmpl = WorldTemplate(
            metadata=TemplateMetadata(
                template_key="bare",
                display_name="Bare",
                tags=[],
                compatible_tones=[],
                location_count=0,
                npc_count=0,
            ),
        )
        assert tmpl.relationships == []
