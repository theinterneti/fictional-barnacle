"""Value types shared across v2 simulation sub-systems (S34–S38).

WorldTime, TimeConfig, and WorldDelta are the S34 contracts.
ConsequenceRecord and MemoryRecord are forward-declared stubs for Wave E/F.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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


@dataclass(frozen=True)
class WorldDelta:
    """Result of advancing diegetic time, produced by WorldTimeService."""

    from_tick: int
    to_tick: int
    world_time: WorldTime
    was_capped: bool


# ---------------------------------------------------------------------------
# Wave E / Wave F forward stubs
# ---------------------------------------------------------------------------


@dataclass
class ConsequenceRecord:
    """Stub: consequence propagation payload (S36, implemented in Wave E)."""

    source_event_id: str = ""
    affected_entities: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class MemoryRecord:
    """Stub: world/NPC memory entry (S37–S38, implemented in Wave F)."""

    tick: int = 0
    content: str = ""
    entities: list[str] = field(default_factory=list)
