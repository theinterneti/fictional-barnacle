"""Neo4j-backed RelationshipService implementation.

Stores relationships as RELATES_TO edges between NPC/PlayerSession
nodes with dimension properties.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, LiteralString, cast

import structlog
from neo4j import AsyncDriver, Query

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

if TYPE_CHECKING:
    from uuid import UUID

logger = structlog.get_logger(__name__)

# PlayerSession nodes use session_id (not id) as their key.
_PLAYER_ENTITY = "player"


def _node_pattern(
    entity_id: str, var: str, id_param: str
) -> tuple[str, dict[str, str]]:
    """Build Cypher match pattern, special-casing PlayerSession nodes."""
    if entity_id == _PLAYER_ENTITY:
        return f"({var}:PlayerSession {{session_id: $sid}})", {}
    return f"({var} {{id: ${id_param}, session_id: $sid}})", {id_param: entity_id}


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
        a_pat, a_params = _node_pattern(source_id, "a", "src")
        b_pat, b_params = _node_pattern(target_id, "b", "tgt")
        params: dict[str, Any] = {"sid": sid, **a_params, **b_params}
        async with self._driver.session() as session:
            result = await session.run(
                Query(
                    cast(
                        "LiteralString",
                        f"MATCH {a_pat}-[r:RELATES_TO]->{b_pat} "
                        "RETURN r.trust AS trust, r.affinity AS affinity, "
                        "r.respect AS respect, r.fear AS fear, "
                        "r.familiarity AS familiarity, r.updated_at AS updated_at",
                    )
                ),
                params,
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
        a_pat, a_params = _node_pattern(entity_id, "a", "eid")
        params: dict[str, Any] = {"sid": sid, **a_params}
        async with self._driver.session() as session:
            result = await session.run(
                Query(
                    cast(
                        "LiteralString",
                        f"MATCH {a_pat}-[r:RELATES_TO]->(b {{session_id: $sid}}) "
                        "RETURN CASE WHEN b:PlayerSession THEN 'player' "
                        "ELSE b.id END AS target_id, "
                        "r.trust AS trust, r.affinity AS affinity, "
                        "r.respect AS respect, r.fear AS fear, "
                        "r.familiarity AS familiarity, r.updated_at AS updated_at",
                    )
                ),
                params,
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
        a_pat, a_params = _node_pattern(rel.source_id, "a", "src")
        b_pat, b_params = _node_pattern(rel.target_id, "b", "tgt")
        params: dict[str, Any] = {
            "sid": sid,
            **a_params,
            **b_params,
            "trust": d.trust,
            "affinity": d.affinity,
            "respect": d.respect,
            "fear": d.fear,
            "familiarity": d.familiarity,
            "label": d.label,
        }
        async with self._driver.session() as session:
            await session.run(
                Query(
                    cast(
                        "LiteralString",
                        f"MATCH {a_pat} MATCH {b_pat} "
                        "MERGE (a)-[r:RELATES_TO]->(b) "
                        "SET r.trust = $trust, r.affinity = $affinity, "
                        "r.respect = $respect, r.fear = $fear, "
                        "r.familiarity = $familiarity, r.label = $label, "
                        "r.session_id = $sid, r.updated_at = datetime()",
                    )
                ),
                params,
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
