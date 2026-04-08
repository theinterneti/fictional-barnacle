"""Neo4j-backed RelationshipService implementation.

Stores relationships as RELATES_TO edges between NPC/PlayerSession
nodes with dimension properties.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from neo4j import AsyncDriver

from tta.models.world import (
    NPCRelationship,
    RelationshipChange,
    RelationshipDimensions,
    apply_relationship_change,
)
from tta.world.relationship_service import (
    COMPANION_AFFINITY_THRESHOLD,
    COMPANION_TRUST_THRESHOLD,
)

logger = structlog.get_logger(__name__)


class Neo4jRelationshipService:
    """Neo4j-backed relationship tracking.

    Relationships are stored as ``RELATES_TO`` edges with properties
    for the five dimensions plus a computed label and timestamp.
    Source and target can be NPC or PlayerSession nodes.
    """

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    async def get_relationship(
        self,
        session_id: UUID,
        source_id: str,
        target_id: str,
    ) -> NPCRelationship | None:
        sid = str(session_id)
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (a {id: $src, session_id: $sid})
                      -[r:RELATES_TO]->
                      (b {id: $tgt, session_id: $sid})
                RETURN r.trust AS trust,
                       r.affinity AS affinity,
                       r.respect AS respect,
                       r.fear AS fear,
                       r.familiarity AS familiarity,
                       r.updated_at AS updated_at
                """,
                src=source_id,
                tgt=target_id,
                sid=sid,
            )
            record = await result.single()
            if record is None:
                return None
            return _record_to_relationship(record, source_id, target_id, sid)

    async def get_relationships_for(
        self,
        session_id: UUID,
        entity_id: str,
    ) -> list[NPCRelationship]:
        sid = str(session_id)
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (a {id: $eid, session_id: $sid})
                      -[r:RELATES_TO]->
                      (b {session_id: $sid})
                RETURN b.id AS target_id,
                       r.trust AS trust,
                       r.affinity AS affinity,
                       r.respect AS respect,
                       r.fear AS fear,
                       r.familiarity AS familiarity,
                       r.updated_at AS updated_at
                """,
                eid=entity_id,
                sid=sid,
            )
            rels: list[NPCRelationship] = []
            async for record in result:
                rels.append(
                    _record_to_relationship(record, entity_id, record["target_id"], sid)
                )
            return rels

    async def update_relationship(
        self,
        session_id: UUID,
        source_id: str,
        target_id: str,
        change: RelationshipChange,
    ) -> NPCRelationship:
        existing = await self.get_relationship(session_id, source_id, target_id)
        if existing is None:
            existing = NPCRelationship(
                source_id=source_id,
                target_id=target_id,
                session_id=str(session_id),
            )
        new_dims = apply_relationship_change(existing.dimensions, change)
        updated = existing.model_copy(
            update={
                "dimensions": new_dims,
                "updated_at": datetime.now(UTC),
            }
        )
        await self._write_relationship(session_id, updated)
        return updated

    async def set_relationship(
        self,
        session_id: UUID,
        relationship: NPCRelationship,
    ) -> None:
        await self._write_relationship(session_id, relationship)

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
        async with self._driver.session() as session:
            await session.run(
                """
                MATCH ()-[r:RELATES_TO {session_id: $sid}]->()
                DELETE r
                """,
                sid=sid,
            )

    # -- internal helpers --

    async def _write_relationship(
        self,
        session_id: UUID,
        rel: NPCRelationship,
    ) -> None:
        """MERGE a RELATES_TO edge with dimension properties."""
        sid = str(session_id)
        d = rel.dimensions
        async with self._driver.session() as session:
            await session.run(
                """
                MATCH (a {id: $src, session_id: $sid})
                MATCH (b {id: $tgt, session_id: $sid})
                MERGE (a)-[r:RELATES_TO]->(b)
                SET r.trust = $trust,
                    r.affinity = $affinity,
                    r.respect = $respect,
                    r.fear = $fear,
                    r.familiarity = $familiarity,
                    r.label = $label,
                    r.session_id = $sid,
                    r.updated_at = datetime()
                """,
                src=rel.source_id,
                tgt=rel.target_id,
                sid=sid,
                trust=d.trust,
                affinity=d.affinity,
                respect=d.respect,
                fear=d.fear,
                familiarity=d.familiarity,
                label=d.label,
            )


def _record_to_relationship(
    record: Any,
    source_id: str,
    target_id: str,
    session_id: str,
) -> NPCRelationship:
    """Build an NPCRelationship from a Neo4j record."""
    dims = RelationshipDimensions(
        trust=record.get("trust", 0),
        affinity=record.get("affinity", 0),
        respect=record.get("respect", 0),
        fear=record.get("fear", 0),
        familiarity=record.get("familiarity", 0),
    )
    return NPCRelationship(
        source_id=source_id,
        target_id=target_id,
        session_id=session_id,
        dimensions=dims,
    )
