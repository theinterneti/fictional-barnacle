"""Consequence chain domain models.

Covers consequence timescales, visibility, chain tracking,
narrative anchors, and divergence scoring defined in spec S05
(Choice & Consequence) FR-3, FR-4, FR-7, FR-8.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from tta.models.choice import ImpactLevel, Reversibility

# Cap on active consequence chains per story (S05 FR-3.6)
MAX_ACTIVE_CHAINS = 30


class ConsequenceTimescale(StrEnum):
    """When a consequence manifests (S05 FR-3).

    - IMMEDIATE: same turn
    - SHORT_TERM: 1-10 turns later
    - LONG_TERM: 10+ turns later
    """

    IMMEDIATE = "immediate"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


class ConsequenceVisibility(StrEnum):
    """Whether the player knows about this consequence (S05 FR-7).

    Hidden entries are tracked but not surfaced until they manifest.
    Foreshadowed entries have subtle narrative hints.
    """

    VISIBLE = "visible"
    FORESHADOWED = "foreshadowed"
    HIDDEN = "hidden"


class ConsequenceStatus(StrEnum):
    """Lifecycle status of a consequence entry (S05 FR-3, FR-8)."""

    PENDING = "pending"
    ACTIVE = "active"
    RESOLVED = "resolved"
    DORMANT = "dormant"
    PRUNED = "pruned"


class ConsequenceEntry(BaseModel):
    """A single cause-effect node in a consequence chain (S05 FR-3).

    Each entry represents one link in a chain of consequences.
    Entries may branch (one trigger → multiple effects) or
    merge (multiple triggers → one resolution).
    """

    id: UUID = Field(default_factory=uuid4)
    chain_id: UUID
    trigger: str
    effect: str
    visibility: ConsequenceVisibility = ConsequenceVisibility.VISIBLE
    status: ConsequenceStatus = ConsequenceStatus.PENDING
    timescale: ConsequenceTimescale = ConsequenceTimescale.SHORT_TERM
    narrative_hook: str = ""
    turn_created: int = 0
    turn_resolved: int | None = None
    parent_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConsequenceChain(BaseModel):
    """A linked sequence of consequence entries (S05 FR-3).

    Chains form a directed graph: entries can branch (1→many)
    and merge (many→1). Each chain tracks its overall metadata.
    Branching uses parent-pointer model (child stores parent_chain_id).
    """

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    root_trigger: str
    entries: list[ConsequenceEntry] = Field(default_factory=list)
    parent_chain_id: UUID | None = None
    reversibility: Reversibility = Reversibility.MODERATE
    impact_level: ImpactLevel = ImpactLevel.ATMOSPHERIC
    turn_created: int = 0
    last_active_turn: int = 0
    is_dormant: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def active_entries(self) -> list[ConsequenceEntry]:
        """Return entries that are pending or active."""
        return [
            e
            for e in self.entries
            if e.status in (ConsequenceStatus.PENDING, ConsequenceStatus.ACTIVE)
        ]

    @property
    def is_resolved(self) -> bool:
        """True when all entries are resolved or pruned."""
        return (
            all(
                e.status in (ConsequenceStatus.RESOLVED, ConsequenceStatus.PRUNED)
                for e in self.entries
            )
            and len(self.entries) > 0
        )


class NarrativeAnchor(BaseModel):
    """A key story event the narrative gravitates toward (S05 FR-4).

    The world tends toward these anchor points. High divergence
    triggers gentle steering; very high triggers anchor replacement.
    """

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    description: str
    target_turn: int | None = None
    is_active: bool = True
    is_reached: bool = False
    replacement_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DivergenceScore(BaseModel):
    """Measures how far the story has diverged from anchors (S05 FR-4).

    Score range: 0.0 (on track) to 1.0 (completely diverged).
    """

    score: float = Field(default=0.0, ge=0.0, le=1.0)
    nearest_anchor_id: UUID | None = None
    turn_number: int = 0
    factors: dict = Field(default_factory=dict)

    @property
    def needs_steering(self) -> bool:
        """True when divergence is high enough to warrant steering."""
        return self.score >= 0.7

    @property
    def needs_anchor_replacement(self) -> bool:
        """True when divergence is so high the anchor should change."""
        return self.score >= 0.9
