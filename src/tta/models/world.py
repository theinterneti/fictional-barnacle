"""World domain models — locations, NPCs, items, and world state."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Location(BaseModel):
    """A discrete place in the game world."""

    id: str
    name: str
    description: str
    type: str
    visited: bool = False


class NPC(BaseModel):
    """A non-player character."""

    id: str
    name: str
    description: str
    disposition: str
    alive: bool = True


class Item(BaseModel):
    """An interactable object in the world."""

    id: str
    name: str
    description: str
    portable: bool = True
    hidden: bool = False


class WorldChangeType(StrEnum):
    """Categories of world-state mutations."""

    location_entered = "location_entered"
    npc_moved = "npc_moved"
    item_picked_up = "item_picked_up"
    item_dropped = "item_dropped"
    npc_disposition_changed = "npc_disposition_changed"
    location_modified = "location_modified"
    custom = "custom"


class WorldChange(BaseModel):
    """A single atomic change to the world state."""

    type: WorldChangeType
    entity_id: str
    payload: dict = Field(default_factory=dict)


class WorldEvent(BaseModel):
    """A persisted record of something that happened."""

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    turn_id: UUID | None = None
    event_type: str
    entity_id: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorldContext(BaseModel):
    """Snapshot of the world visible to the player right now."""

    current_location: Location
    nearby_locations: list[Location] = Field(default_factory=list)
    npcs_present: list[NPC] = Field(default_factory=list)
    items_here: list[Item] = Field(default_factory=list)
    recent_events: list[WorldEvent] = Field(default_factory=list)


class LocationContext(BaseModel):
    """Location-centric view used by the narrative engine."""

    location: Location
    adjacent_locations: list[Location] = Field(default_factory=list)
    npcs_present: list[NPC] = Field(default_factory=list)
    items_here: list[Item] = Field(default_factory=list)


class WorldTemplate(BaseModel):
    """Blueprint for generating a world."""

    name: str
    description: str
    locations: list[dict] = Field(default_factory=list)
    npcs: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    connections: list[dict] = Field(default_factory=list)


class WorldSeed(BaseModel):
    """A concrete seed ready for world instantiation."""

    template: WorldTemplate
    flavor_text: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
