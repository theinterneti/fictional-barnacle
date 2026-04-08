"""World domain models — locations, NPCs, items, and world state."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# -- Controlled vocabularies as type aliases --

LocationType = Literal["interior", "exterior", "underground", "water"]
LightLevel = Literal["dark", "dim", "lit", "bright"]
NPCRole = Literal["merchant", "quest_giver", "companion", "ambient"]
NPCState = Literal["idle", "active", "busy", "sleeping", "traveling"]
ItemType = Literal["weapon", "tool", "key", "consumable", "quest", "ambient"]
ConnectionDirection = Literal[
    "n",
    "s",
    "e",
    "w",
    "ne",
    "nw",
    "se",
    "sw",
    "up",
    "down",
    "in",
    "out",
    "north",
    "south",
    "east",
    "west",
    "northeast",
    "northwest",
    "southeast",
    "southwest",
]
EventType = Literal["narrative", "combat", "trade", "discovery", "quest"]
EventSeverity = Literal["minor", "notable", "major", "critical"]
QuestStatus = Literal["available", "active", "completed", "failed"]
QuestDifficulty = Literal["easy", "medium", "hard"]
WorldStatus = Literal["active", "paused", "completed", "archived"]

# -- Core domain models --


class Location(BaseModel):
    """A discrete place in the game world."""

    id: str
    name: str
    description: str
    type: LocationType
    visited: bool = False
    # Wave 3 optional extensions
    region_id: str | None = None
    description_visited: str | None = None
    is_accessible: bool = True
    light_level: LightLevel = "lit"
    tags: list[str] = Field(default_factory=list)
    template_key: str | None = None
    session_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NPC(BaseModel):
    """A non-player character."""

    id: str
    name: str
    description: str
    disposition: str
    alive: bool = True
    # Wave 3 optional extensions
    role: NPCRole | None = None
    state: NPCState = "idle"
    personality: str | None = None
    dialogue_style: str | None = None
    tags: list[str] = Field(default_factory=list)
    template_key: str | None = None
    session_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Item(BaseModel):
    """An interactable object in the world."""

    id: str
    name: str
    description: str
    portable: bool = True
    hidden: bool = False
    # Wave 3 optional extensions
    item_type: ItemType | None = None
    is_usable: bool = False
    use_effect: str | None = None
    tags: list[str] = Field(default_factory=list)
    template_key: str | None = None
    session_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Region(BaseModel):
    """A grouping of locations within the world."""

    id: str
    session_id: str
    name: str
    description: str
    atmosphere: str | None = None
    danger_level: int = 0
    template_key: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Connection(BaseModel):
    """A directional link between two locations."""

    from_id: str
    to_id: str
    direction: ConnectionDirection
    description: str | None = None
    is_locked: bool = False
    lock_description: str | None = None
    required_item_id: str | None = None
    is_hidden: bool = False
    travel_time: int | None = None


class PlayerSession(BaseModel):
    """Lightweight graph pointer — detailed data in Postgres."""

    session_id: UUID
    player_id: UUID
    world_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GraphEvent(BaseModel):
    """Neo4j narrative event — things NPCs remember.

    Distinct from WorldEvent (Postgres mechanical changelog).
    """

    id: str
    session_id: str
    type: str
    description: str
    severity: EventSeverity = "minor"
    is_public: bool = True
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Quest(BaseModel):
    """A quest tracked in the world graph."""

    id: str
    session_id: str
    name: str
    description: str
    status: QuestStatus = "available"
    difficulty: QuestDifficulty | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorldChangeType(StrEnum):
    """Categories of world-state mutations (plan §2.3)."""

    PLAYER_MOVED = "player_moved"
    ITEM_TAKEN = "item_taken"
    ITEM_DROPPED = "item_dropped"
    NPC_MOVED = "npc_moved"
    NPC_DISPOSITION_CHANGED = "npc_disposition_changed"
    LOCATION_STATE_CHANGED = "location_state_changed"
    CONNECTION_LOCKED = "connection_locked"
    CONNECTION_UNLOCKED = "connection_unlocked"
    QUEST_STATUS_CHANGED = "quest_status_changed"
    ITEM_VISIBILITY_CHANGED = "item_visibility_changed"
    NPC_STATE_CHANGED = "npc_state_changed"


class WorldChange(BaseModel):
    """A single atomic change to the world state."""

    type: WorldChangeType
    entity_id: str
    payload: dict = Field(default_factory=dict)


class WorldEvent(BaseModel):
    """A persisted record of something that happened (Postgres)."""

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


# -- Template models (plan §3.1) --


class TemplateMetadata(BaseModel):
    """Template-level metadata for selection and filtering."""

    template_key: str
    display_name: str
    tags: list[str] = Field(default_factory=list)
    compatible_tones: list[str] = Field(default_factory=list)
    compatible_tech_levels: list[str] = Field(default_factory=list)
    compatible_magic: list[str] = Field(default_factory=list)
    compatible_scales: list[str] = Field(default_factory=list)
    location_count: int = 0
    npc_count: int = 0


class TemplateRegion(BaseModel):
    """A region within a world template."""

    key: str
    archetype: str


class TemplateLocation(BaseModel):
    """A location definition within a world template."""

    key: str
    region_key: str
    type: LocationType
    archetype: str
    is_starting_location: bool = False
    light_level: LightLevel = "lit"
    tags: list[str] = Field(default_factory=list)


class TemplateConnection(BaseModel):
    """A connection between locations in a template."""

    from_key: str
    to_key: str
    direction: ConnectionDirection
    bidirectional: bool = True
    is_locked: bool = False
    is_hidden: bool = False


class TemplateNPC(BaseModel):
    """An NPC definition within a world template."""

    key: str
    location_key: str
    role: NPCRole
    archetype: str
    disposition: str = "neutral"


class TemplateItem(BaseModel):
    """An item definition within a world template."""

    key: str
    location_key: str | None = None
    npc_key: str | None = None
    type: ItemType
    archetype: str
    portable: bool = True
    hidden: bool = False


class TemplateKnowledge(BaseModel):
    """Knowledge an NPC has about something in the template."""

    npc_key: str
    about_key: str
    knowledge_type: str
    is_secret: bool = False


class WorldTemplate(BaseModel):
    """Typed blueprint for generating a world (plan §3.1)."""

    metadata: TemplateMetadata
    regions: list[TemplateRegion] = Field(default_factory=list)
    locations: list[TemplateLocation] = Field(default_factory=list)
    connections: list[TemplateConnection] = Field(default_factory=list)
    npcs: list[TemplateNPC] = Field(default_factory=list)
    items: list[TemplateItem] = Field(default_factory=list)
    knowledge: list[TemplateKnowledge] = Field(default_factory=list)


class WorldSeed(BaseModel):
    """A concrete seed ready for world instantiation."""

    template: WorldTemplate
    flavor_text: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Genesis-lite fields (plan §4.2)
    tone: str | None = None
    tech_level: str | None = None
    magic_presence: str | None = None
    world_scale: str | None = None
    player_position: str | None = None
    power_source: str | None = None
    defining_detail: str | None = None
    character_name: str | None = None
    character_concept: str | None = None
