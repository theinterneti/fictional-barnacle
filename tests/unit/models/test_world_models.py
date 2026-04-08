"""Tests for world domain models."""

import json
from uuid import UUID, uuid4

from tta.models.world import (
    NPC,
    RELATIONSHIP_CLAMP_DRAMATIC,
    RELATIONSHIP_CLAMP_NORMAL,
    Connection,
    GraphEvent,
    Item,
    Location,
    LocationContext,
    NPCDialogueContext,
    NPCRelationship,
    NPCTier,
    PlayerSession,
    Quest,
    Region,
    RelationshipChange,
    RelationshipDimensions,
    TemplateConnection,
    TemplateItem,
    TemplateKnowledge,
    TemplateLocation,
    TemplateMetadata,
    TemplateNPC,
    TemplateRegion,
    WorldChange,
    WorldChangeType,
    WorldContext,
    WorldEvent,
    WorldSeed,
    WorldTemplate,
    apply_relationship_change,
    trust_to_label,
)


def _location(**overrides: object) -> Location:
    defaults = {
        "id": "loc-1",
        "name": "Town Square",
        "description": "A bustling square.",
        "type": "exterior",
    }
    return Location(**{**defaults, **overrides})


def _npc(**overrides: object) -> NPC:
    defaults = {
        "id": "npc-1",
        "name": "Ada",
        "description": "A wandering scholar.",
        "disposition": "friendly",
    }
    return NPC(**{**defaults, **overrides})


def _item(**overrides: object) -> Item:
    defaults = {
        "id": "item-1",
        "name": "Old Map",
        "description": "A faded parchment.",
    }
    return Item(**{**defaults, **overrides})


def _template_metadata(**overrides: object) -> TemplateMetadata:
    defaults = {
        "template_key": "forest-001",
        "display_name": "Dark Forest",
    }
    return TemplateMetadata(**{**defaults, **overrides})


# --- Location ---


class TestLocation:
    def test_defaults(self) -> None:
        loc = _location()
        assert loc.visited is False

    def test_visited_override(self) -> None:
        loc = _location(visited=True)
        assert loc.visited is True

    def test_required_fields(self) -> None:
        loc = _location()
        assert loc.id == "loc-1"
        assert loc.name == "Town Square"
        assert loc.type == "exterior"

    def test_wave3_optional_defaults(self) -> None:
        loc = _location()
        assert loc.region_id is None
        assert loc.description_visited is None
        assert loc.is_accessible is True
        assert loc.light_level == "lit"
        assert loc.tags == []
        assert loc.template_key is None

    def test_wave3_optional_overrides(self) -> None:
        loc = _location(
            region_id="reg-1",
            description_visited="Familiar square.",
            is_accessible=False,
            light_level="dim",
            tags=["urban", "central"],
            template_key="town-square",
        )
        assert loc.region_id == "reg-1"
        assert loc.description_visited == "Familiar square."
        assert loc.is_accessible is False
        assert loc.light_level == "dim"
        assert loc.tags == ["urban", "central"]
        assert loc.template_key == "town-square"


# --- NPC ---


class TestNPC:
    def test_alive_default(self) -> None:
        npc = _npc()
        assert npc.alive is True

    def test_alive_override(self) -> None:
        npc = _npc(alive=False)
        assert npc.alive is False

    def test_fields(self) -> None:
        npc = _npc()
        assert npc.disposition == "friendly"

    def test_wave3_optional_defaults(self) -> None:
        npc = _npc()
        assert npc.role is None
        assert npc.state == "idle"
        assert npc.personality is None
        assert npc.dialogue_style is None
        assert npc.tags == []
        assert npc.template_key is None

    def test_wave3_optional_overrides(self) -> None:
        npc = _npc(
            role="merchant",
            state="active",
            personality="gruff but kind",
            dialogue_style="terse",
            tags=["shopkeeper"],
            template_key="npc-blacksmith",
        )
        assert npc.role == "merchant"
        assert npc.state == "active"
        assert npc.personality == "gruff but kind"
        assert npc.dialogue_style == "terse"
        assert npc.tags == ["shopkeeper"]
        assert npc.template_key == "npc-blacksmith"


# --- Item ---


class TestItem:
    def test_portable_default(self) -> None:
        item = _item()
        assert item.portable is True

    def test_hidden_default(self) -> None:
        item = _item()
        assert item.hidden is False

    def test_overrides(self) -> None:
        item = _item(portable=False, hidden=True)
        assert item.portable is False
        assert item.hidden is True

    def test_wave3_optional_defaults(self) -> None:
        item = _item()
        assert item.item_type is None
        assert item.is_usable is False
        assert item.use_effect is None
        assert item.tags == []
        assert item.template_key is None

    def test_wave3_optional_overrides(self) -> None:
        item = _item(
            item_type="key",
            is_usable=True,
            use_effect="Opens the gate.",
            tags=["quest"],
            template_key="gate-key",
        )
        assert item.item_type == "key"
        assert item.is_usable is True
        assert item.use_effect == "Opens the gate."
        assert item.tags == ["quest"]
        assert item.template_key == "gate-key"


# --- Region ---


class TestRegion:
    def test_minimal(self) -> None:
        r = Region(
            id="reg-1",
            session_id="sess-1",
            name="Darkwood",
            description="Foreboding forest.",
        )
        assert r.id == "reg-1"
        assert r.atmosphere is None
        assert r.danger_level == 0
        assert r.template_key is None
        assert r.created_at is not None

    def test_full(self) -> None:
        r = Region(
            id="reg-2",
            session_id="sess-1",
            name="Swamp",
            description="Murky swamp.",
            atmosphere="eerie",
            danger_level=7,
            template_key="swamp-01",
        )
        assert r.danger_level == 7
        assert r.atmosphere == "eerie"


# --- Connection ---


class TestConnection:
    def test_minimal(self) -> None:
        c = Connection(from_id="loc-1", to_id="loc-2", direction="n")
        assert c.is_locked is False
        assert c.is_hidden is False
        assert c.travel_time is None

    def test_locked_connection(self) -> None:
        c = Connection(
            from_id="loc-1",
            to_id="loc-3",
            direction="e",
            is_locked=True,
            lock_description="A heavy iron gate.",
            required_item_id="item-key",
        )
        assert c.is_locked is True
        assert c.required_item_id == "item-key"


# --- PlayerSession ---


class TestPlayerSession:
    def test_creation(self) -> None:
        ps = PlayerSession(
            session_id=uuid4(),
            player_id=uuid4(),
            world_id="world-1",
        )
        assert ps.world_id == "world-1"
        assert ps.created_at is not None


# --- GraphEvent ---


class TestGraphEvent:
    def test_defaults(self) -> None:
        e = GraphEvent(
            id="evt-1",
            session_id="sess-1",
            type="narrative",
            description="A door creaks open.",
        )
        assert e.severity == "minor"
        assert e.is_public is True

    def test_full(self) -> None:
        e = GraphEvent(
            id="evt-2",
            session_id="sess-1",
            type="combat",
            description="The guard attacks!",
            severity="major",
            is_public=False,
        )
        assert e.severity == "major"
        assert e.is_public is False


# --- Quest ---


class TestQuest:
    def test_defaults(self) -> None:
        q = Quest(
            id="q-1",
            session_id="sess-1",
            name="Find the Key",
            description="Locate the old key.",
        )
        assert q.status == "available"
        assert q.difficulty is None

    def test_full(self) -> None:
        q = Quest(
            id="q-2",
            session_id="sess-1",
            name="Defeat the Dragon",
            description="Slay the beast.",
            status="active",
            difficulty="hard",
        )
        assert q.status == "active"
        assert q.difficulty == "hard"


# --- WorldChange ---


class TestWorldChange:
    def test_with_enum(self) -> None:
        change = WorldChange(
            type=WorldChangeType.ITEM_TAKEN,
            entity_id="item-1",
            payload={"by": "player"},
        )
        assert change.type == WorldChangeType.ITEM_TAKEN
        assert change.entity_id == "item-1"
        assert change.payload == {"by": "player"}

    def test_enum_values(self) -> None:
        assert WorldChangeType.PLAYER_MOVED.value == "player_moved"
        assert WorldChangeType.NPC_STATE_CHANGED.value == ("npc_state_changed")

    def test_all_enum_members(self) -> None:
        expected = {
            "PLAYER_MOVED",
            "ITEM_TAKEN",
            "ITEM_DROPPED",
            "NPC_MOVED",
            "NPC_DISPOSITION_CHANGED",
            "LOCATION_STATE_CHANGED",
            "CONNECTION_LOCKED",
            "CONNECTION_UNLOCKED",
            "QUEST_STATUS_CHANGED",
            "ITEM_VISIBILITY_CHANGED",
            "NPC_STATE_CHANGED",
            "RELATIONSHIP_CHANGED",
            "NPC_TIER_CHANGED",
        }
        assert {m.name for m in WorldChangeType} == expected


# --- WorldEvent ---


class TestWorldEvent:
    def test_uuid_fields(self) -> None:
        sid = uuid4()
        tid = uuid4()
        event = WorldEvent(
            session_id=sid,
            turn_id=tid,
            event_type="npc_spoke",
            entity_id="npc-1",
        )
        assert isinstance(event.id, UUID)
        assert event.session_id == sid
        assert event.turn_id == tid

    def test_optional_turn_id(self) -> None:
        event = WorldEvent(
            session_id=uuid4(),
            event_type="world_init",
            entity_id="world",
        )
        assert event.turn_id is None

    def test_created_at_auto(self) -> None:
        event = WorldEvent(
            session_id=uuid4(),
            event_type="test",
            entity_id="e",
        )
        assert event.created_at is not None


# --- WorldContext ---


class TestWorldContext:
    def test_assembly(self) -> None:
        loc = _location()
        npc = _npc()
        item = _item()
        ctx = WorldContext(
            current_location=loc,
            nearby_locations=[_location(id="loc-2", name="Alley")],
            npcs_present=[npc],
            items_here=[item],
        )
        assert ctx.current_location.id == "loc-1"
        assert len(ctx.nearby_locations) == 1
        assert ctx.npcs_present[0].name == "Ada"
        assert ctx.items_here[0].name == "Old Map"
        assert ctx.recent_events == []


# --- LocationContext ---


class TestLocationContext:
    def test_assembly(self) -> None:
        loc = _location()
        adj = _location(id="loc-3", name="Market")
        ctx = LocationContext(
            location=loc,
            adjacent_locations=[adj],
            npcs_present=[_npc()],
            items_here=[_item()],
        )
        assert ctx.location.name == "Town Square"
        assert len(ctx.adjacent_locations) == 1
        assert len(ctx.npcs_present) == 1
        assert len(ctx.items_here) == 1


# --- Template models ---


class TestTemplateMetadata:
    def test_defaults(self) -> None:
        m = _template_metadata()
        assert m.template_key == "forest-001"
        assert m.tags == []
        assert m.compatible_tones == []
        assert m.location_count == 0
        assert m.npc_count == 0

    def test_full(self) -> None:
        m = _template_metadata(
            tags=["dark", "fantasy"],
            compatible_tones=["grim"],
            compatible_tech_levels=["medieval"],
            compatible_magic=["high"],
            compatible_scales=["village"],
            location_count=5,
            npc_count=3,
        )
        assert m.tags == ["dark", "fantasy"]
        assert m.location_count == 5


class TestTemplateRegion:
    def test_basic(self) -> None:
        r = TemplateRegion(key="forest", archetype="dark-forest")
        assert r.key == "forest"
        assert r.archetype == "dark-forest"


class TestTemplateLocation:
    def test_defaults(self) -> None:
        tl = TemplateLocation(
            key="clearing",
            region_key="forest",
            type="exterior",
            archetype="forest-clearing",
        )
        assert tl.is_starting_location is False
        assert tl.light_level == "lit"
        assert tl.tags == []


class TestTemplateConnection:
    def test_defaults(self) -> None:
        tc = TemplateConnection(
            from_key="clearing",
            to_key="cave-mouth",
            direction="n",
        )
        assert tc.bidirectional is True
        assert tc.is_locked is False
        assert tc.is_hidden is False


class TestTemplateNPC:
    def test_defaults(self) -> None:
        tn = TemplateNPC(
            key="ranger",
            location_key="clearing",
            role="quest_giver",
            archetype="forest-ranger",
        )
        assert tn.disposition == "neutral"


class TestTemplateItem:
    def test_defaults(self) -> None:
        ti = TemplateItem(
            key="torch",
            location_key="clearing",
            type="tool",
            archetype="basic-torch",
        )
        assert ti.portable is True
        assert ti.hidden is False
        assert ti.npc_key is None


class TestTemplateKnowledge:
    def test_basic(self) -> None:
        tk = TemplateKnowledge(
            npc_key="ranger",
            about_key="cave-mouth",
            knowledge_type="location",
        )
        assert tk.is_secret is False


# --- WorldTemplate (typed) ---


class TestWorldTemplate:
    def test_typed_template(self) -> None:
        meta = _template_metadata()
        tmpl = WorldTemplate(
            metadata=meta,
            regions=[TemplateRegion(key="forest", archetype="dark")],
            locations=[
                TemplateLocation(
                    key="clearing",
                    region_key="forest",
                    type="exterior",
                    archetype="forest-clearing",
                )
            ],
            connections=[
                TemplateConnection(
                    from_key="clearing",
                    to_key="cave",
                    direction="n",
                )
            ],
            npcs=[
                TemplateNPC(
                    key="ranger",
                    location_key="clearing",
                    role="quest_giver",
                    archetype="forest-ranger",
                )
            ],
            items=[
                TemplateItem(
                    key="torch",
                    location_key="clearing",
                    type="tool",
                    archetype="basic-torch",
                )
            ],
            knowledge=[
                TemplateKnowledge(
                    npc_key="ranger",
                    about_key="cave",
                    knowledge_type="location",
                )
            ],
        )
        assert tmpl.metadata.template_key == "forest-001"
        assert len(tmpl.regions) == 1
        assert len(tmpl.locations) == 1
        assert len(tmpl.connections) == 1
        assert len(tmpl.npcs) == 1
        assert len(tmpl.items) == 1
        assert len(tmpl.knowledge) == 1

    def test_empty_lists_default(self) -> None:
        tmpl = WorldTemplate(metadata=_template_metadata())
        assert tmpl.regions == []
        assert tmpl.locations == []
        assert tmpl.connections == []
        assert tmpl.npcs == []
        assert tmpl.items == []
        assert tmpl.knowledge == []


# --- WorldSeed ---


class TestWorldSeed:
    def test_json_round_trip(self) -> None:
        meta = _template_metadata(template_key="cave-01", display_name="Cave")
        tmpl = WorldTemplate(metadata=meta)
        seed = WorldSeed(
            template=tmpl,
            flavor_text={"intro": "You step inside…"},
        )
        data = seed.model_dump_json()
        restored = WorldSeed.model_validate_json(data)
        assert restored.template.metadata.template_key == "cave-01"
        assert restored.flavor_text["intro"] == ("You step inside…")

    def test_json_serializable(self) -> None:
        seed = WorldSeed(
            template=WorldTemplate(metadata=_template_metadata()),
        )
        raw = json.loads(seed.model_dump_json())
        assert isinstance(raw, dict)
        assert "template" in raw

    def test_genesis_optional_fields(self) -> None:
        seed = WorldSeed(
            template=WorldTemplate(metadata=_template_metadata()),
            tone="dark",
            tech_level="medieval",
            magic_presence="high",
            world_scale="village",
            player_position="outsider",
            power_source="arcane",
            defining_detail="cursed forest",
            character_name="Elara",
            character_concept="wandering healer",
        )
        assert seed.tone == "dark"
        assert seed.tech_level == "medieval"
        assert seed.magic_presence == "high"
        assert seed.world_scale == "village"
        assert seed.player_position == "outsider"
        assert seed.power_source == "arcane"
        assert seed.defining_detail == "cursed forest"
        assert seed.character_name == "Elara"
        assert seed.character_concept == "wandering healer"

    def test_genesis_fields_default_none(self) -> None:
        seed = WorldSeed(
            template=WorldTemplate(metadata=_template_metadata()),
        )
        assert seed.tone is None
        assert seed.tech_level is None
        assert seed.character_name is None


# -- Wave 5: Character depth --


class TestNPCTier:
    def test_values(self) -> None:
        assert NPCTier.KEY == "key"
        assert NPCTier.SUPPORTING == "supporting"
        assert NPCTier.BACKGROUND == "background"

    def test_is_str(self) -> None:
        assert isinstance(NPCTier.KEY, str)


class TestNPCWave5Fields:
    """NPC model extensions from S06 FR-3."""

    def test_defaults(self) -> None:
        npc = _npc()
        assert npc.tier == NPCTier.BACKGROUND
        assert npc.traits == []
        assert npc.goals_short is None
        assert npc.goals_long is None
        assert npc.knowledge_summary is None
        assert npc.schedule is None
        assert npc.voice is None
        assert npc.occupation is None
        assert npc.mannerisms is None
        assert npc.appearance is None
        assert npc.backstory is None
        assert npc.interaction_count == 0

    def test_overrides(self) -> None:
        npc = _npc(
            tier=NPCTier.KEY,
            traits=["cunning", "loyal"],
            goals_short="find the artifact",
            goals_long="restore the kingdom",
            knowledge_summary="knows the location of the ruin",
            schedule="patrols the wall at dawn",
            voice="gravelly whisper",
            occupation="guard captain",
            mannerisms="taps sword hilt when nervous",
            appearance="scarred, tall",
            backstory="veteran of the border wars",
            interaction_count=5,
        )
        assert npc.tier == NPCTier.KEY
        assert npc.traits == ["cunning", "loyal"]
        assert npc.goals_short == "find the artifact"
        assert npc.goals_long == "restore the kingdom"
        assert npc.knowledge_summary == "knows the location of the ruin"
        assert npc.schedule == "patrols the wall at dawn"
        assert npc.voice == "gravelly whisper"
        assert npc.occupation == "guard captain"
        assert npc.mannerisms == "taps sword hilt when nervous"
        assert npc.appearance == "scarred, tall"
        assert npc.backstory == "veteran of the border wars"
        assert npc.interaction_count == 5

    def test_backward_compat_minimal_npc(self) -> None:
        """Existing code creating NPCs with only required fields still works."""
        npc = NPC(
            id="npc-old",
            name="Old NPC",
            description="Test",
            disposition="neutral",
        )
        assert npc.tier == NPCTier.BACKGROUND
        assert npc.traits == []
        assert npc.interaction_count == 0


class TestTrustToLabel:
    def test_hostile(self) -> None:
        assert trust_to_label(-100) == "hostile"
        assert trust_to_label(-51) == "hostile"

    def test_cold(self) -> None:
        assert trust_to_label(-50) == "cold"
        assert trust_to_label(-11) == "cold"

    def test_neutral(self) -> None:
        assert trust_to_label(-10) == "neutral"
        assert trust_to_label(0) == "neutral"
        assert trust_to_label(9) == "neutral"

    def test_warm(self) -> None:
        assert trust_to_label(10) == "neutral"
        assert trust_to_label(11) == "warm"
        assert trust_to_label(50) == "warm"

    def test_loyal(self) -> None:
        assert trust_to_label(51) == "loyal"
        assert trust_to_label(100) == "loyal"


class TestRelationshipDimensions:
    def test_defaults(self) -> None:
        dims = RelationshipDimensions()
        assert dims.trust == 0
        assert dims.affinity == 0
        assert dims.respect == 0
        assert dims.fear == 0
        assert dims.familiarity == 0
        assert dims.label == "neutral"

    def test_label_from_trust(self) -> None:
        d = RelationshipDimensions(trust=60)
        assert d.label == "loyal"

    def test_validation_bounds(self) -> None:
        d = RelationshipDimensions(trust=100, affinity=-100, fear=100, familiarity=0)
        assert d.trust == 100
        assert d.affinity == -100

    def test_rejects_out_of_range(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RelationshipDimensions(trust=101)
        with pytest.raises(ValidationError):
            RelationshipDimensions(fear=-1)


class TestRelationshipChange:
    def test_clamped_normal(self) -> None:
        change = RelationshipChange(trust=50, affinity=-50)
        clamped = change.clamped()
        assert clamped.trust == RELATIONSHIP_CLAMP_NORMAL
        assert clamped.affinity == -RELATIONSHIP_CLAMP_NORMAL

    def test_clamped_dramatic(self) -> None:
        change = RelationshipChange(trust=50, dramatic=True)
        clamped = change.clamped()
        assert clamped.trust == RELATIONSHIP_CLAMP_DRAMATIC

    def test_within_limit_unchanged(self) -> None:
        change = RelationshipChange(trust=5, affinity=-3)
        clamped = change.clamped()
        assert clamped.trust == 5
        assert clamped.affinity == -3


class TestApplyRelationshipChange:
    def test_basic_apply(self) -> None:
        dims = RelationshipDimensions(trust=0, familiarity=0)
        result = apply_relationship_change(
            dims, RelationshipChange(trust=10, familiarity=10)
        )
        assert result.trust == 10
        assert result.familiarity == 10

    def test_clamped_at_bounds(self) -> None:
        dims = RelationshipDimensions(trust=95)
        result = apply_relationship_change(dims, RelationshipChange(trust=15))
        assert result.trust == 100  # capped at 100

    def test_fear_stays_non_negative(self) -> None:
        dims = RelationshipDimensions(fear=5)
        result = apply_relationship_change(dims, RelationshipChange(fear=-15))
        assert result.fear == 0


class TestNPCRelationship:
    def test_label_delegation(self) -> None:
        rel = NPCRelationship(
            source_id="player-1",
            target_id="npc-1",
            session_id="sess-1",
            dimensions=RelationshipDimensions(trust=-60),
        )
        assert rel.label == "hostile"

    def test_default_dimensions(self) -> None:
        rel = NPCRelationship(
            source_id="a",
            target_id="b",
            session_id="s",
        )
        assert rel.dimensions.trust == 0
        assert rel.label == "neutral"


class TestNPCDialogueContext:
    def test_defaults(self) -> None:
        ctx = NPCDialogueContext(npc_id="npc-1", npc_name="Ada")
        assert ctx.disposition == "neutral"
        assert ctx.traits == []
        assert ctx.relationship_label == "neutral"
        assert ctx.relationship_trust == 0

    def test_full_context(self) -> None:
        ctx = NPCDialogueContext(
            npc_id="npc-1",
            npc_name="Ada",
            personality="gruff but kind",
            voice="gravelly whisper",
            traits=["cunning"],
            knowledge_summary="knows the secret",
            goals_short="guard the gate",
            relationship_label="warm",
            relationship_trust=35,
            relationship_affinity=20,
            emotional_state="wary",
            occupation="guard",
            mannerisms="taps sword",
        )
        assert ctx.voice == "gravelly whisper"
        assert ctx.relationship_label == "warm"


class TestWorldChangeTypeWave5:
    def test_relationship_changed(self) -> None:
        assert WorldChangeType.RELATIONSHIP_CHANGED == "relationship_changed"

    def test_npc_tier_changed(self) -> None:
        assert WorldChangeType.NPC_TIER_CHANGED == "npc_tier_changed"


class TestTemplateNPCWave5:
    def test_defaults(self) -> None:
        tnpc = TemplateNPC(
            key="guard",
            location_key="gate",
            role="ambient",
            archetype="silent watcher",
        )
        assert tnpc.tier == NPCTier.BACKGROUND
        assert tnpc.traits == []
        assert tnpc.goals_hint is None
        assert tnpc.backstory_hint is None

    def test_key_npc_template(self) -> None:
        tnpc = TemplateNPC(
            key="mentor",
            location_key="tower",
            role="quest_giver",
            archetype="wise sage",
            tier=NPCTier.KEY,
            traits=["wise", "patient"],
            goals_hint="guide the hero",
            backstory_hint="former court wizard",
        )
        assert tnpc.tier == NPCTier.KEY
        assert tnpc.traits == ["wise", "patient"]
        assert tnpc.goals_hint == "guide the hero"
