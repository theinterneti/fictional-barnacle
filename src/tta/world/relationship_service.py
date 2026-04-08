"""Relationship tracking service — protocol + in-memory implementation.

Manages directional relationships (PC↔NPC and NPC↔NPC) with
five-axis dimensions (S06 FR-5).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Protocol, runtime_checkable
from uuid import UUID

import structlog

from tta.models.world import (
    NPCRelationship,
    RelationshipChange,
    apply_relationship_change,
)

logger = structlog.get_logger(__name__)

# Companion-eligibility thresholds (S06 FR-5.4)
COMPANION_TRUST_THRESHOLD: int = 30
COMPANION_AFFINITY_THRESHOLD: int = 20


@runtime_checkable
class RelationshipService(Protocol):
    """Interface for relationship CRUD operations."""

    async def get_relationship(
        self,
        session_id: UUID,
        source_id: str,
        target_id: str,
    ) -> NPCRelationship | None:
        """Return the relationship from source to target, or None."""
        ...

    async def get_relationships_for(
        self,
        session_id: UUID,
        entity_id: str,
    ) -> list[NPCRelationship]:
        """Return all relationships where entity is source."""
        ...

    async def update_relationship(
        self,
        session_id: UUID,
        source_id: str,
        target_id: str,
        change: RelationshipChange,
    ) -> NPCRelationship:
        """Apply a change delta; creates the relationship if absent."""
        ...

    async def set_relationship(
        self,
        session_id: UUID,
        relationship: NPCRelationship,
    ) -> None:
        """Upsert a full relationship (used by Genesis seeding)."""
        ...

    async def check_companion_eligible(
        self,
        session_id: UUID,
        source_id: str,
        target_id: str,
    ) -> bool:
        """True if trust > 30 and affinity > 20 (S06 FR-5.4)."""
        ...

    async def cleanup_session(
        self,
        session_id: UUID,
    ) -> None:
        """Remove all relationships for a session."""
        ...


class InMemoryRelationshipService:
    """In-memory implementation for unit tests."""

    def __init__(self) -> None:
        # (session_id, source_id, target_id) → NPCRelationship
        self._rels: dict[tuple[str, str, str], NPCRelationship] = {}

    def _key(
        self, session_id: UUID, source_id: str, target_id: str
    ) -> tuple[str, str, str]:
        return (str(session_id), source_id, target_id)

    async def get_relationship(
        self,
        session_id: UUID,
        source_id: str,
        target_id: str,
    ) -> NPCRelationship | None:
        return deepcopy(self._rels.get(self._key(session_id, source_id, target_id)))

    async def get_relationships_for(
        self,
        session_id: UUID,
        entity_id: str,
    ) -> list[NPCRelationship]:
        sid = str(session_id)
        return [
            deepcopy(r)
            for (s, src, _), r in self._rels.items()
            if s == sid and src == entity_id
        ]

    async def update_relationship(
        self,
        session_id: UUID,
        source_id: str,
        target_id: str,
        change: RelationshipChange,
    ) -> NPCRelationship:
        key = self._key(session_id, source_id, target_id)
        existing = self._rels.get(key)
        if existing is None:
            existing = NPCRelationship(
                source_id=source_id,
                target_id=target_id,
                session_id=str(session_id),
            )
        new_dims = apply_relationship_change(existing.dimensions, change)
        updated = existing.model_copy(update={"dimensions": new_dims})
        self._rels[key] = updated
        return deepcopy(updated)

    async def set_relationship(
        self,
        session_id: UUID,
        relationship: NPCRelationship,
    ) -> None:
        key = self._key(session_id, relationship.source_id, relationship.target_id)
        normalized = relationship.model_copy(update={"session_id": str(session_id)})
        self._rels[key] = deepcopy(normalized)

    async def check_companion_eligible(
        self,
        session_id: UUID,
        source_id: str,
        target_id: str,
    ) -> bool:
        rel = await self.get_relationship(session_id, source_id, target_id)
        if rel is None:
            return False
        d = rel.dimensions
        return (
            d.trust > COMPANION_TRUST_THRESHOLD
            and d.affinity > COMPANION_AFFINITY_THRESHOLD
        )

    async def cleanup_session(
        self,
        session_id: UUID,
    ) -> None:
        sid = str(session_id)
        to_remove = [k for k in self._rels if k[0] == sid]
        for k in to_remove:
            del self._rels[k]
