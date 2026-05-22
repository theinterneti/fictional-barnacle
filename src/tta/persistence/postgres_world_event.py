"""PostgresWorldEventRepository — async event persistence.

Extracted from postgres.py during code health decomposition.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.models.world import WorldEvent


class PostgresWorldEventRepository:
    """Async Postgres-backed world-event repository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create_world_event(
        self,
        session_id: UUID,
        turn_id: UUID,
        event_type: str,
        entity_id: str,
        payload: dict,
    ) -> WorldEvent:
        event_id = uuid4()
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "INSERT INTO world_events "
                    "(id, session_id, turn_id, "
                    "event_type, entity_id, "
                    "payload) "
                    "VALUES (:id, :session_id, :turn_id, "
                    ":event_type, :entity_id, "
                    "cast(:payload AS jsonb)) "
                    "RETURNING id, session_id, turn_id, "
                    "event_type, entity_id, "
                    "payload, created_at"
                ),
                {
                    "id": event_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "event_type": event_type,
                    "entity_id": entity_id,
                    "payload": json.dumps(payload),
                },
            )
            row = result.one()
            await session.commit()
            return WorldEvent(
                id=row.id,
                session_id=row.session_id,
                turn_id=row.turn_id,
                event_type=row.event_type,
                entity_id=row.entity_id,
                payload=row.payload,
                created_at=row.created_at,
            )

    async def get_recent_events(
        self, session_id: UUID, limit: int = 5
    ) -> list[WorldEvent]:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT id, session_id, turn_id, "
                    "event_type, entity_id, "
                    "payload, created_at "
                    "FROM world_events "
                    "WHERE session_id = :session_id "
                    "ORDER BY created_at DESC "
                    "LIMIT :lim"
                ),
                {"session_id": session_id, "lim": limit},
            )
            rows = result.all()
            return [
                WorldEvent(
                    id=r.id,
                    session_id=r.session_id,
                    turn_id=r.turn_id,
                    event_type=r.event_type,
                    entity_id=r.entity_id,
                    payload=r.payload,
                    created_at=r.created_at,
                )
                for r in rows
            ]


# ── Player persistence ───────────────────────────────────────────
