"""Tests for genesis-lite world bootstrap flow."""

from __future__ import annotations

import json
from uuid import uuid4

from tta.genesis.genesis_lite import (
    GenesisResult,
    _default_enrichment,
    enrich_template,
    run_genesis_lite,
)
from tta.llm.client import (
    GenerationParams,
    LLMResponse,
    Message,
)
from tta.llm.roles import ModelRole
from tta.llm.testing import MockLLMClient
from tta.models.turn import TokenCount
from tta.models.world import (
    TemplateConnection,
    TemplateItem,
    TemplateKnowledge,
    TemplateLocation,
    TemplateMetadata,
    TemplateNPC,
    TemplateRegion,
    WorldSeed,
    WorldTemplate,
)
from tta.world.memory_service import InMemoryWorldService

# -- Test helpers ------------------------------------------------


def _make_test_template() -> WorldTemplate:
    """Build a minimal but complete WorldTemplate."""
    return WorldTemplate(
        metadata=TemplateMetadata(
            template_key="test_village",
            display_name="Test Village",
            tags=["village"],
            compatible_tones=["mysterious"],
            location_count=2,
            npc_count=1,
        ),
        regions=[
            TemplateRegion(
                key="village_center",
                archetype="village square",
            ),
        ],
        locations=[
            TemplateLocation(
                key="tavern",
                region_key="village_center",
                type="interior",
                archetype="cozy tavern",
                is_starting_location=True,
            ),
            TemplateLocation(
                key="market",
                region_key="village_center",
                type="exterior",
                archetype="bustling market",
            ),
        ],
        connections=[
            TemplateConnection(
                from_key="tavern",
                to_key="market",
                direction="n",
            ),
        ],
        npcs=[
            TemplateNPC(
                key="barkeep",
                location_key="tavern",
                role="merchant",
                archetype="friendly barkeep",
            ),
        ],
        items=[
            TemplateItem(
                key="old_map",
                location_key="tavern",
                type="quest",
                archetype="weathered map",
            ),
        ],
        knowledge=[
            TemplateKnowledge(
                npc_key="barkeep",
                about_key="old_map",
                knowledge_type="lore",
            ),
        ],
    )


def _make_enrichment_json(
    template: WorldTemplate,
) -> str:
    """Build valid EnrichedTemplate JSON for *template*."""
    data = {
        "locations": [
            {
                "key": loc.key,
                "name": f"The {loc.archetype.title()}",
                "description": (f"A {loc.archetype} full of character."),
                "description_visited": (f"The familiar {loc.archetype}."),
            }
            for loc in template.locations
        ],
        "npcs": [
            {
                "key": npc.key,
                "name": (npc.archetype.replace("_", " ").title()),
                "description": (f"A weathered {npc.role}."),
                "personality": "gruff but kind",
                "dialogue_style": "short sentences",
            }
            for npc in template.npcs
        ],
        "items": [
            {
                "key": item.key,
                "name": (item.archetype.replace("_", " ").title()),
                "description": (f"An intriguing {item.type} item."),
            }
            for item in template.items
        ],
        "knowledge_details": {
            f"{k.npc_key}:{k.about_key}": (f"Knows about the {k.about_key}")
            for k in template.knowledge
        },
    }
    return json.dumps(data)


def _make_world_seed(
    template: WorldTemplate | None = None,
) -> WorldSeed:
    """Build a WorldSeed with sensible genesis-lite fields."""
    if template is None:
        template = _make_test_template()
    return WorldSeed(
        template=template,
        tone="mysterious",
        tech_level="medieval",
        magic_presence="low",
        world_scale="village",
        defining_detail="an ancient curse",
        character_name="Kael",
        character_concept="wandering healer",
    )


class _SequenceMockLLM:
    """Mock LLM returning successive responses per call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._index = 0
        self.call_history: list[dict] = []

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        idx = min(
            self._index,
            len(self._responses) - 1,
        )
        content = self._responses[idx]
        self._index += 1
        self.call_history.append(
            {
                "method": "generate",
                "role": role,
                "messages": messages,
            }
        )
        prompt_tokens = sum(len(m.content.split()) for m in messages)
        comp_tokens = len(content.split())
        return LLMResponse(
            content=content,
            model_used="mock-seq",
            token_count=TokenCount(
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
                total_tokens=prompt_tokens + comp_tokens,
            ),
            latency_ms=0.0,
        )


# -- Tests: run_genesis_lite ------------------------------------


class TestRunGenesisLite:
    """End-to-end tests for the genesis-lite flow."""

    async def test_happy_path_completes(self) -> None:
        """Full flow returns GenesisResult with all fields."""
        # Arrange
        template = _make_test_template()
        seed = _make_world_seed(template)
        enrichment_json = _make_enrichment_json(template)
        llm = _SequenceMockLLM(
            [enrichment_json, "You arrive at the tavern."],
        )
        world_svc = InMemoryWorldService()
        session_id = uuid4()
        player_id = uuid4()

        # Act
        result = await run_genesis_lite(
            session_id=session_id,
            player_id=player_id,
            world_seed=seed,
            llm=llm,
            world_service=world_svc,
        )

        # Assert
        assert isinstance(result, GenesisResult)
        assert result.session_id == session_id
        assert result.template_key == "test_village"
        assert result.world_id.startswith(
            "world_test_village_",
        )
        assert result.player_location_id
        assert result.narrative_intro == "You arrive at the tavern."
        assert result.created_at is not None

    async def test_enrichment_fallback_on_bad_json(
        self,
    ) -> None:
        """Genesis completes even when LLM returns junk."""
        # Arrange
        template = _make_test_template()
        seed = _make_world_seed(template)
        llm = _SequenceMockLLM(
            [
                "not valid json at all",
                "still not json {{{",
                "Welcome to the world.",
            ],
        )
        world_svc = InMemoryWorldService()
        session_id = uuid4()

        # Act
        result = await run_genesis_lite(
            session_id=session_id,
            player_id=uuid4(),
            world_seed=seed,
            llm=llm,
            world_service=world_svc,
        )

        # Assert — flow completed with defaults
        assert isinstance(result, GenesisResult)
        assert result.session_id == session_id
        assert result.template_key == "test_village"
        assert result.narrative_intro == "Welcome to the world."

    async def test_starting_location_detected(
        self,
    ) -> None:
        """Player location matches is_starting_location."""
        # Arrange
        template = _make_test_template()
        seed = _make_world_seed(template)
        enrichment_json = _make_enrichment_json(template)
        llm = _SequenceMockLLM(
            [enrichment_json, "You stand in the tavern."],
        )
        world_svc = InMemoryWorldService()
        session_id = uuid4()

        # Act
        result = await run_genesis_lite(
            session_id=session_id,
            player_id=uuid4(),
            world_seed=seed,
            llm=llm,
            world_service=world_svc,
        )

        # Assert
        loc = await world_svc.get_player_location(
            session_id,
        )
        assert loc.id == result.player_location_id
        assert loc.template_key == "tavern"

    async def test_narrative_intro_uses_generation_role(
        self,
    ) -> None:
        """Intro call uses ModelRole.GENERATION."""
        # Arrange
        template = _make_test_template()
        seed = _make_world_seed(template)
        enrichment_json = _make_enrichment_json(template)
        llm = _SequenceMockLLM(
            [enrichment_json, "A warm fire crackles."],
        )
        world_svc = InMemoryWorldService()

        # Act
        await run_genesis_lite(
            session_id=uuid4(),
            player_id=uuid4(),
            world_seed=seed,
            llm=llm,
            world_service=world_svc,
        )

        # Assert — two LLM calls: extraction then generation
        assert len(llm.call_history) == 2
        assert llm.call_history[0]["role"] == ModelRole.EXTRACTION
        assert llm.call_history[1]["role"] == ModelRole.GENERATION

    async def test_world_service_called_with_session(
        self,
    ) -> None:
        """create_world_graph materialises the world."""
        # Arrange
        template = _make_test_template()
        seed = _make_world_seed(template)
        enrichment_json = _make_enrichment_json(template)
        llm = _SequenceMockLLM(
            [enrichment_json, "The adventure begins."],
        )
        world_svc = InMemoryWorldService()
        session_id = uuid4()

        # Act
        await run_genesis_lite(
            session_id=session_id,
            player_id=uuid4(),
            world_seed=seed,
            llm=llm,
            world_service=world_svc,
        )

        # Assert — world graph exists for this session
        loc = await world_svc.get_player_location(
            session_id,
        )
        assert loc is not None
        state = await world_svc.get_world_state(
            session_id,
        )
        assert state.current_location is not None


# -- Tests: enrich_template --------------------------------------


class TestEnrichTemplate:
    """Tests for the enrich_template function."""

    async def test_valid_json_parsed(self) -> None:
        """Valid enrichment JSON is parsed correctly."""
        # Arrange
        template = _make_test_template()
        seed = _make_world_seed(template)
        enrichment_json = _make_enrichment_json(template)
        llm = MockLLMClient(response=enrichment_json)

        # Act
        result = await enrich_template(
            template,
            seed,
            llm,
        )

        # Assert
        assert len(result.locations) == 2
        assert len(result.npcs) == 1
        assert len(result.items) == 1
        assert result.locations[0].key == "tavern"
        assert result.npcs[0].personality == "gruff but kind"

    async def test_fallback_on_invalid_json(self) -> None:
        """Invalid JSON triggers fallback enrichment."""
        # Arrange
        template = _make_test_template()
        seed = _make_world_seed(template)
        llm = MockLLMClient(
            response="definitely not json",
        )

        # Act
        result = await enrich_template(
            template,
            seed,
            llm,
        )

        # Assert — defaults derived from archetypes
        assert len(result.locations) == 2
        assert result.locations[0].key == "tavern"
        assert "cozy tavern" in (result.locations[0].name.lower())


# -- Tests: _default_enrichment ----------------------------------


class TestDefaultEnrichment:
    """Tests for the deterministic fallback enrichment."""

    def test_uses_archetypes_as_names(self) -> None:
        """Archetype strings become title-cased names."""
        # Arrange
        template = _make_test_template()

        # Act
        result = _default_enrichment(template)

        # Assert
        assert len(result.locations) == 2
        assert result.locations[0].key == "tavern"
        assert "Cozy Tavern" in result.locations[0].name
        assert result.npcs[0].key == "barkeep"
        assert "Friendly Barkeep" in result.npcs[0].name
        assert result.items[0].key == "old_map"
        assert "Weathered Map" in result.items[0].name
