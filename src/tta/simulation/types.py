"""Value types shared across v2 simulation sub-systems (S34–S38).

WorldTime and TimeConfig are the S34 contracts.
WorldDelta, NPCStateChange, WorldEvent support S35 (NPC Autonomy).
ConsequenceRecord, PropagationSource, PropagationResult support S36.
MemoryRecord, MemoryContext, CompressionResult support S37.
NPCEpisodicMemory, NPCSocialEdge, GossipEvent, NPCSocialContext support S38.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

# ---------------------------------------------------------------------------
# S34 — Diegetic Time
# ---------------------------------------------------------------------------

EventSeverity = Literal["minor", "notable", "major", "critical"]


@dataclass(frozen=True)
class WorldTime:
    """Immutable snapshot of diegetic in-world time.

    All fields are derived deterministically from total_ticks + TimeConfig.
    """

    total_ticks: int
    day_count: int
    hour: int
    minute: int
    time_of_day_label: str


@dataclass
class TimeConfig:
    """Configuration that maps simulation ticks to diegetic time.

    All fields have defaults so callers may override selectively.
    """

    ticks_per_turn: int = 1
    minutes_per_tick: int = 60
    hours_per_day: int = 24
    day_start_hour: int = 6
    starting_hour: int = 8
    starting_day: int = 0
    max_skip_ticks: int = 48
    tod_boundaries: dict[str, float] | None = None


# ---------------------------------------------------------------------------
# S35 — NPC Autonomy types (needed before WorldDelta)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeferredNPC:
    """An NPC skipped during autonomy processing (AC-35.07/35.08)."""

    npc_id: str
    reason: str


@dataclass
class NPCStateChange:
    """A single state mutation produced by NPC autonomous action."""

    npc_id: str
    action_type: str
    before: dict
    after: dict


@dataclass(frozen=True)
class WorldEvent:
    """An event emitted by the simulation during a tick."""

    event_id: str
    universe_id: str
    event_type: str
    description: str
    severity: EventSeverity
    triggered_at_tick: int
    created_at: datetime
    source_npc_id: str | None = None
    location_id: str | None = None


# ---------------------------------------------------------------------------
# S34 — WorldDelta (extended in Wave E with optional NPC autonomy fields)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorldDelta:
    """Result of advancing diegetic time, produced by WorldTimeService.

    The four required fields (from_tick–was_capped) are the S34 contract.
    The five optional fields are populated by AutonomyProcessor (S35).
    """

    from_tick: int
    to_tick: int
    world_time: WorldTime
    was_capped: bool
    # Wave E extensions — default-valued so S34 callers are unaffected
    tick: int = 0
    changes: list[NPCStateChange] = field(default_factory=list)
    events: list[WorldEvent] = field(default_factory=list)
    deferred_npcs: list[DeferredNPC] = field(default_factory=list)
    deferred_changes: list[NPCStateChange] = field(default_factory=list)


# ---------------------------------------------------------------------------
# S35 — Autonomy action types + routine configuration
# ---------------------------------------------------------------------------

RoutineTrigger = Literal["time_of_day", "tick_elapsed", "world_event", "player_visited"]
# time_of_day and tick_elapsed are v2.0 active triggers.
# world_event and player_visited log + return "not_matched" (AC-35.10).


@dataclass(frozen=True)
class MoveAction:
    target_location_id: str


@dataclass(frozen=True)
class StateChangeAction:
    # new_state is one of NPCState literals; typed as str to avoid circular import
    new_state: str


@dataclass(frozen=True)
class DispositionShiftAction:
    npc_id: str
    delta: float


@dataclass(frozen=True)
class NarrativeEventAction:
    description: str
    severity: EventSeverity


AutonomyAction = (
    MoveAction | StateChangeAction | DispositionShiftAction | NarrativeEventAction
)


@dataclass
class RoutineCondition:
    """Condition tied to a RoutineStep trigger."""

    label: str  # time-of-day label (e.g. "morning") or stringified tick delta


@dataclass
class RoutineStep:
    """One entry in an NPC's autonomous routine."""

    trigger: RoutineTrigger
    action: AutonomyAction
    priority: int = 5
    repeating: bool = True
    condition: RoutineCondition | None = None


# ---------------------------------------------------------------------------
# S36 — Consequence Propagation types
# ---------------------------------------------------------------------------


@dataclass
class PropagationSource:
    """Input event for the consequence propagation graph walk."""

    source_event_id: str
    source_type: str  # "player_action" | "npc_autonomy" | "world_event"
    source_location_id: str
    original_severity: EventSeverity
    description: str
    faction_id: str | None = None
    affected_entity_id: str | None = None
    affected_entity_type: str | None = None


@dataclass
class ConsequenceRecord:
    """A single propagated consequence reaching one entity (S36 contract)."""

    consequence_id: str
    universe_id: str
    source_event_id: str
    source_type: str
    source_location_id: str
    affected_entity_id: str
    affected_entity_type: str
    hop_distance: int
    original_severity: EventSeverity
    propagated_severity: EventSeverity
    description: str
    triggered_at_tick: int
    created_at: datetime
    faction_id: str | None = None


@dataclass
class PropagationResult:
    """Aggregate output of one propagation pass (S36 contract)."""

    source_event_id: str
    records: list[ConsequenceRecord] = field(default_factory=list)
    faction_records: list[ConsequenceRecord] = field(default_factory=list)
    total_records: int = 0
    propagation_depth_reached: int = 0
    skipped_minor: int = 0
    budget_exceeded: bool = False


# ---------------------------------------------------------------------------
# S37 — World Memory Model
# ---------------------------------------------------------------------------


@dataclass
class MemoryRecord:
    """A single world-scoped memory entry (S37 FR-37.01).

    Tier is assigned at write time and updated during compression.
    """

    memory_id: str  # ULID
    universe_id: str  # ULID
    session_id: str  # UUID
    turn_number: int
    world_time_tick: int  # WorldTime.total_ticks (S34)
    source: Literal["player", "narrator", "npc", "world"]
    attributed_to: str | None
    content: str
    summary: str | None
    importance_score: float
    tier: Literal["working", "active", "compressed", "archived"]
    is_compressed: bool
    compressed_from: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    consequence_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def current_importance(self, current_tick: int, half_life_ticks: int) -> float:
        """Decayed importance score per S37 FR-37.05 and Appendix A."""
        ticks_elapsed = max(0, current_tick - self.world_time_tick)
        if ticks_elapsed == 0 or half_life_ticks <= 0:
            return self.importance_score
        return self.importance_score * (0.5 ** (ticks_elapsed / half_life_ticks))


@dataclass
class MemoryContext:
    """Assembled context returned by MemoryWriter.get_context() (S37 FR-37.03)."""

    working: list[MemoryRecord] = field(default_factory=list)
    active: list[MemoryRecord] = field(default_factory=list)
    compressed: list[MemoryRecord] = field(default_factory=list)
    total_tokens: int = 0
    dropped_count: int = 0


@dataclass
class CompressionResult:
    """Result of one compression pass (S37 FR-37.06)."""

    compressed_count: int
    new_record: MemoryRecord | None = None
    skipped: bool = False


# ---------------------------------------------------------------------------
# S38 — NPC Memory & Social Model
# ---------------------------------------------------------------------------


@dataclass
class NPCEpisodicMemory:
    """A single episodic memory record held by one NPC (S38 FR-38.01)."""

    episode_id: str  # ULID
    npc_id: str
    universe_id: str
    session_id: str  # UUID
    turn_number: int
    world_time_tick: int
    source_memory_id: str | None
    consequence_id: str | None
    player_id: str
    content: str
    emotional_valence: float  # [-1.0, 1.0]
    relationship_delta: object | None  # RelationshipChange from models.world
    importance_score: float  # [0.0, 1.0]
    is_gossip: bool
    gossip_source_npc_id: str | None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class NPCSocialEdge:
    """A directed social relationship in the NPC graph (S38 FR-38.02)."""

    edge_id: str  # ULID
    source_npc_id: str
    target_id: str  # NPC ID or player ID
    universe_id: str
    dimensions: object  # RelationshipDimensions from models.world
    gossip_weight: float = 0.0  # familiarity / 100.0 by default
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class GossipEvent:
    """A single unit of gossip traveling through the social graph (S38 FR-38.03)."""

    gossip_id: str  # ULID
    universe_id: str
    originating_episode_id: str
    sender_npc_id: str
    receiver_npc_id: str
    content: str
    hop_count: int
    reliability: float  # [0.0, 1.0]; decrements 0.2 per hop
    session_id: str
    world_time_tick: int
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class NPCSocialContext:
    """NPC social context returned by SocialMemoryWriter.get_npc_context()."""

    relationship: NPCSocialEdge | None = None
    episodes: list[NPCEpisodicMemory] = field(default_factory=list)
    gossip_received: list[GossipEvent] = field(default_factory=list)
    npc_id: str = ""
    player_id: str = ""
    total_tokens: int = 0
    dropped_count: int = 0
