"""Tests for world domain models."""

import json
from uuid import UUID, uuid4

from tta.models.world import (  # noqa: I001
    NPC,
    Item,
    Location,
    LocationContext,
    WorldChange,
    WorldChangeType,
    WorldContext,
    WorldEvent,
    WorldSeed,
    WorldTemplate,
)


def _location(**overrides: object) -> Location:
    defaults = {
        "id": "loc-1",
        "name": "Town Square",
        "description": "A bustling square.",
        "type": "outdoor",
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
        assert loc.type == "outdoor"


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


# --- WorldChange ---


class TestWorldChange:
    def test_with_enum(self) -> None:
        change = WorldChange(
            type=WorldChangeType.item_picked_up,
            entity_id="item-1",
            payload={"by": "player"},
        )
        assert change.type == WorldChangeType.item_picked_up
        assert change.entity_id == "item-1"
        assert change.payload == {"by": "player"}

    def test_enum_values(self) -> None:
        assert WorldChangeType.location_entered.value == ("location_entered")
        assert WorldChangeType.custom.value == "custom"


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


# --- WorldSeed & WorldTemplate ---


class TestWorldTemplate:
    def test_nested_data(self) -> None:
        tmpl = WorldTemplate(
            name="Forest",
            description="A dark wood.",
            locations=[{"id": "l1", "name": "Clearing"}],
            npcs=[{"id": "n1", "name": "Ranger"}],
            items=[{"id": "i1", "name": "Torch"}],
            connections=[{"from": "l1", "to": "l2"}],
        )
        assert tmpl.name == "Forest"
        assert len(tmpl.locations) == 1
        assert tmpl.connections[0]["from"] == "l1"


class TestWorldSeed:
    def test_json_round_trip(self) -> None:
        tmpl = WorldTemplate(
            name="Cave",
            description="An echoing cave.",
        )
        seed = WorldSeed(
            template=tmpl,
            flavor_text={"intro": "You step inside…"},
        )
        data = seed.model_dump_json()
        restored = WorldSeed.model_validate_json(data)
        assert restored.template.name == "Cave"
        assert restored.flavor_text["intro"] == ("You step inside…")

    def test_json_serializable(self) -> None:
        seed = WorldSeed(
            template=WorldTemplate(name="T", description="D"),
        )
        raw = json.loads(seed.model_dump_json())
        assert isinstance(raw, dict)
        assert "template" in raw
