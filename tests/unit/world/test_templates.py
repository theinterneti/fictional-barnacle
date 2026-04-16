"""Tests for template_validator — covers all 10 validation rules."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tta.models.world import WorldTemplate
from tta.world.template_validator import (
    DanglingReferenceError,
    DirectionConflictError,
    DisconnectedGraphError,
    DuplicateKeyError,
    EmptyTemplateError,
    ItemPlacementError,
    NoStartingLocationError,
    TemplateValidationError,
    validate_template,
)

# ── Fixture: load bundled templates ──────────────────────────────

TEMPLATES_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "tta" / "world" / "templates"
)


def _load_template(name: str) -> WorldTemplate:
    path = TEMPLATES_DIR / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return WorldTemplate.model_validate(raw)


@pytest.fixture
def quiet_village() -> WorldTemplate:
    return _load_template("quiet_village")


@pytest.fixture
def haunted_manor() -> WorldTemplate:
    return _load_template("haunted_manor")


# ── Bundled template smoke tests ─────────────────────────────────


class TestBundledTemplates:
    """Verify that shipped JSON files pass all rules."""

    def test_quiet_village_valid(self, quiet_village: WorldTemplate) -> None:
        # Act / Assert — no exception means pass
        validate_template(quiet_village)

    def test_haunted_manor_valid(self, haunted_manor: WorldTemplate) -> None:
        validate_template(haunted_manor)

    def test_quiet_village_metadata(self, quiet_village: WorldTemplate) -> None:
        meta = quiet_village.metadata
        assert meta.template_key == "quiet_village"
        assert meta.location_count == 3
        assert meta.npc_count == 2

    def test_haunted_manor_metadata(self, haunted_manor: WorldTemplate) -> None:
        meta = haunted_manor.metadata
        assert meta.template_key == "haunted_manor"
        assert meta.location_count == 4
        assert meta.npc_count == 2


# ── Rule 1: unique keys ─────────────────────────────────────────


class TestRule1UniqueKeys:
    def test_duplicate_location_keys(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        t.locations[1].key = t.locations[0].key

        # Act / Assert
        with pytest.raises(DuplicateKeyError, match="Duplicate key"):
            validate_template(t)

    def test_duplicate_across_types(self, quiet_village: WorldTemplate) -> None:
        # Arrange — NPC key collides with a region key
        t = copy.deepcopy(quiet_village)
        t.npcs[0].key = t.regions[0].key

        # Act / Assert
        with pytest.raises(DuplicateKeyError):
            validate_template(t)


# ── Rule 2: region_key refs ─────────────────────────────────────


class TestRule2RegionRefs:
    def test_bad_region_ref(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        t.locations[0].region_key = "nonexistent_region"

        # Act / Assert
        with pytest.raises(DanglingReferenceError, match="unknown region"):
            validate_template(t)


# ── Rule 3: location_key refs (NPCs + items) ────────────────────


class TestRule3LocationRefs:
    def test_npc_bad_location(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        t.npcs[0].location_key = "loc_does_not_exist"

        # Act / Assert
        with pytest.raises(DanglingReferenceError, match="unknown location"):
            validate_template(t)

    def test_item_bad_location(self, quiet_village: WorldTemplate) -> None:
        # Arrange — item_key is at loc_tavern; break it
        t = copy.deepcopy(quiet_village)
        for item in t.items:
            if item.location_key is not None:
                item.location_key = "loc_nowhere"
                break

        # Act / Assert
        with pytest.raises(DanglingReferenceError):
            validate_template(t)


# ── Rule 4: knowledge npc_key / about_key refs ──────────────────


class TestRule4KnowledgeRefs:
    def test_bad_npc_key_in_knowledge(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        t.knowledge[0].npc_key = "npc_ghost"

        # Act / Assert
        with pytest.raises(DanglingReferenceError, match="unknown npc_key"):
            validate_template(t)

    def test_bad_about_key_in_knowledge(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        t.knowledge[0].about_key = "item_does_not_exist"

        # Act / Assert
        with pytest.raises(DanglingReferenceError, match="unknown about_key"):
            validate_template(t)


# ── Rule 5: exactly one starting location ────────────────────────


class TestRule5StartingLocation:
    def test_no_starting_location(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        for loc in t.locations:
            loc.is_starting_location = False

        # Act / Assert
        with pytest.raises(NoStartingLocationError):
            validate_template(t)

    def test_two_starting_locations(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        for loc in t.locations:
            loc.is_starting_location = True

        # Act / Assert
        with pytest.raises(NoStartingLocationError):
            validate_template(t)


# ── Rule 6: connection refs ─────────────────────────────────────


class TestRule6ConnectionRefs:
    def test_bad_from_key(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        t.connections[0].from_key = "loc_phantom"

        # Act / Assert
        with pytest.raises(DanglingReferenceError, match="unknown from_key"):
            validate_template(t)

    def test_bad_to_key(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        t.connections[0].to_key = "loc_phantom"

        # Act / Assert
        with pytest.raises(DanglingReferenceError, match="unknown to_key"):
            validate_template(t)


# ── Rule 7: direction conflicts ──────────────────────────────────


class TestRule7DirectionConflicts:
    def test_same_direction_twice(self, quiet_village: WorldTemplate) -> None:
        # Arrange — both connections leave loc_square east
        t = copy.deepcopy(quiet_village)
        t.connections[1].direction = "east"

        # Act / Assert
        with pytest.raises(DirectionConflictError):
            validate_template(t)

    def test_bidirectional_reverse_conflict(self, quiet_village: WorldTemplate) -> None:
        # Arrange — add a bidirectional connection whose
        # reverse direction conflicts with an existing exit.
        # loc_square→loc_tavern east (bidir) gives loc_tavern
        # a "west" exit.  A new bidir connection from loc_edge
        # to loc_tavern with direction "east" creates reverse
        # "west" on loc_tavern → conflict.
        t = copy.deepcopy(quiet_village)
        from tta.models.world import TemplateConnection

        t.connections.append(
            TemplateConnection(
                from_key="loc_edge",
                to_key="loc_tavern",
                direction="east",
                bidirectional=True,
            )
        )

        with pytest.raises(DirectionConflictError):
            validate_template(t)


# ── Rule 8: item placement ──────────────────────────────────────


class TestRule8ItemPlacement:
    def test_item_with_both_placements(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        t.items[0].location_key = "loc_tavern"
        t.items[0].npc_key = "npc_keeper"

        # Act / Assert
        with pytest.raises(ItemPlacementError):
            validate_template(t)

    def test_item_with_neither_placement(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        t.items[0].location_key = None
        t.items[0].npc_key = None

        # Act / Assert
        with pytest.raises(ItemPlacementError):
            validate_template(t)


# ── Rule 9: at least one location ────────────────────────────────


class TestRule9NonEmpty:
    def test_empty_locations(self, quiet_village: WorldTemplate) -> None:
        # Arrange
        t = copy.deepcopy(quiet_village)
        t.locations = []
        t.connections = []
        t.npcs = []
        t.items = []
        t.knowledge = []

        # Act / Assert
        with pytest.raises(EmptyTemplateError):
            validate_template(t)


# ── Rule 10: connected graph ────────────────────────────────────


class TestRule10ConnectedGraph:
    def test_disconnected_location(self, quiet_village: WorldTemplate) -> None:
        # Arrange — remove all connections → only start is
        # reachable
        t = copy.deepcopy(quiet_village)
        t.connections = []

        # Act / Assert
        with pytest.raises(DisconnectedGraphError):
            validate_template(t)

    def test_single_location_connected(self) -> None:
        """A template with exactly one location is trivially
        connected."""
        from tta.models.world import (
            TemplateLocation,
            TemplateMetadata,
            TemplateRegion,
        )

        t = WorldTemplate(
            metadata=TemplateMetadata(
                template_key="single",
                display_name="Single",
                location_count=1,
                npc_count=0,
            ),
            regions=[TemplateRegion(key="r1", archetype="test")],
            locations=[
                TemplateLocation(
                    key="loc1",
                    region_key="r1",
                    type="interior",
                    archetype="test",
                    is_starting_location=True,
                )
            ],
        )
        # Act / Assert — no exception
        validate_template(t)


# ── Meta: exception hierarchy ────────────────────────────────────


class TestExceptionHierarchy:
    def test_all_errors_are_subclasses(self) -> None:
        errors = [
            DuplicateKeyError,
            DanglingReferenceError,
            NoStartingLocationError,
            DirectionConflictError,
            ItemPlacementError,
            EmptyTemplateError,
            DisconnectedGraphError,
        ]
        for err_cls in errors:
            assert issubclass(err_cls, TemplateValidationError)
