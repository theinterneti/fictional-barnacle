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
DispositionLabel = Literal["hostile", "cold", "neutral", "warm", "loyal"]
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


class NPCTier(StrEnum):
    """NPC fidelity tier (S06 FR-3).

    key        — 3-8 per story, full state, always tracked
    supporting — 10-20 per story, tracked when active
    background — minimal state, regenerated on demand
    """

    KEY = "key"
    SUPPORTING = "supporting"
    BACKGROUND = "background"


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
    # Wave 5 — Character depth (S06 FR-3)
    tier: NPCTier = NPCTier.BACKGROUND
    traits: list[str] = Field(
        default_factory=list,
        description="2-3 personality traits (S06 FR-3.1)",
    )
    goals_short: str | None = None
    goals_long: str | None = None
    knowledge_summary: str | None = None
    schedule: str | None = None
    voice: str | None = None
    occupation: str | None = None
    mannerisms: str | None = None
    appearance: str | None = None
    backstory: str | None = None
    interaction_count: int = 0


# -- Relationship models (S06 FR-5) --

# Clamping constants
RELATIONSHIP_CLAMP_NORMAL: int = 15
RELATIONSHIP_CLAMP_DRAMATIC: int = 30

# Trust-label thresholds (S06 FR-5.2)
_TRUST_THRESHOLDS: list[tuple[int, DispositionLabel]] = [
    (-50, "hostile"),
    (-10, "cold"),
    (11, "neutral"),
    (51, "warm"),
]
_DEFAULT_TRUST_LABEL: DispositionLabel = "loyal"


def trust_to_label(trust: int) -> DispositionLabel:
    """Derive a human-readable label from a trust value."""
    for threshold, label in _TRUST_THRESHOLDS:
        if trust < threshold:
            return label
    return _DEFAULT_TRUST_LABEL


class RelationshipDimensions(BaseModel):
    """Five-axis relationship vector (S06 FR-5.1).

    trust    — belief in reliability    (-100 .. +100)
    affinity — emotional warmth          (-100 .. +100)
    respect  — regard for competence     (-100 .. +100)
    fear     — perceived threat          (   0 .. +100)
    familiarity — depth of acquaintance  (   0 .. +100)
    """

    trust: int = Field(default=0, ge=-100, le=100)
    affinity: int = Field(default=0, ge=-100, le=100)
    respect: int = Field(default=0, ge=-100, le=100)
    fear: int = Field(default=0, ge=0, le=100)
    familiarity: int = Field(default=0, ge=0, le=100)

    @property
    def label(self) -> DispositionLabel:
        """Computed relationship label from trust."""
        return trust_to_label(self.trust)


class RelationshipChange(BaseModel):
    """Delta applied to relationship dimensions.

    All deltas are clamped to ±RELATIONSHIP_CLAMP_NORMAL (15) for
    regular interactions and ±RELATIONSHIP_CLAMP_DRAMATIC (30)
    for dramatic events (S06 FR-5.3).
    """

    trust: int = 0
    affinity: int = 0
    respect: int = 0
    fear: int = 0
    familiarity: int = 0
    dramatic: bool = False

    def clamped(self) -> "RelationshipChange":
        """Return a copy with deltas clamped to spec limits."""
        limit = (
            RELATIONSHIP_CLAMP_DRAMATIC if self.dramatic else RELATIONSHIP_CLAMP_NORMAL
        )
        return RelationshipChange(
            trust=_clamp(self.trust, -limit, limit),
            affinity=_clamp(self.affinity, -limit, limit),
            respect=_clamp(self.respect, -limit, limit),
            fear=_clamp(self.fear, -limit, limit),
            familiarity=_clamp(self.familiarity, -limit, limit),
            dramatic=self.dramatic,
        )


def apply_relationship_change(
    dims: RelationshipDimensions,
    change: RelationshipChange,
) -> RelationshipDimensions:
    """Apply a clamped change to produce new dimensions."""
    c = change.clamped()
    return RelationshipDimensions(
        trust=_clamp(dims.trust + c.trust, -100, 100),
        affinity=_clamp(dims.affinity + c.affinity, -100, 100),
        respect=_clamp(dims.respect + c.respect, -100, 100),
        fear=_clamp(dims.fear + c.fear, 0, 100),
        familiarity=_clamp(dims.familiarity + c.familiarity, 0, 100),
    )


class NPCRelationship(BaseModel):
    """Tracks a directional relationship between two entities.

    Supports both player↔NPC and NPC↔NPC relationships.
    """

    source_id: str
    target_id: str
    session_id: str
    dimensions: RelationshipDimensions = Field(
        default_factory=RelationshipDimensions,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )

    @property
    def label(self) -> DispositionLabel:
        return self.dimensions.label


class NPCDialogueContext(BaseModel):
    """Assembled context for NPC dialogue generation (S06 FR-6).

    Gathered from NPC state + relationship + world context,
    then injected into the generation prompt.
    """

    npc_id: str
    npc_name: str
    personality: str | None = None
    voice: str | None = None
    disposition: str = "neutral"
    traits: list[str] = Field(default_factory=list)
    knowledge_summary: str | None = None
    goals_short: str | None = None
    relationship_label: DispositionLabel = "neutral"
    relationship_trust: int = 0
    relationship_affinity: int = 0
    emotional_state: str | None = None
    occupation: str | None = None
    mannerisms: str | None = None


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


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
    # Wave 5 — Character system
    RELATIONSHIP_CHANGED = "relationship_changed"
    NPC_TIER_CHANGED = "npc_tier_changed"


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
    # Wave 5 — character depth hints
    tier: NPCTier = NPCTier.BACKGROUND
    traits: list[str] = Field(default_factory=list)
    goals_hint: str | None = None
    backstory_hint: str | None = None


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


class TemplateRelationship(BaseModel):
    """Pre-authored NPC↔NPC relationship for Genesis seeding."""

    source_npc_key: str
    target_npc_key: str
    trust: int = Field(default=0, ge=-100, le=100)
    affinity: int = Field(default=0, ge=-100, le=100)
    respect: int = Field(default=0, ge=-100, le=100)
    fear: int = Field(default=0, ge=0, le=100)
    familiarity: int = Field(default=0, ge=0, le=100)


class WorldTemplate(BaseModel):
    """Typed blueprint for generating a world (plan §3.1)."""

    metadata: TemplateMetadata
    regions: list[TemplateRegion] = Field(default_factory=list)
    locations: list[TemplateLocation] = Field(default_factory=list)
    connections: list[TemplateConnection] = Field(default_factory=list)
    npcs: list[TemplateNPC] = Field(default_factory=list)
    items: list[TemplateItem] = Field(default_factory=list)
    knowledge: list[TemplateKnowledge] = Field(default_factory=list)
    relationships: list[TemplateRelationship] = Field(
        default_factory=list,
    )


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
