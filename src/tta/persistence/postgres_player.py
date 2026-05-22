"""PostgresPlayerRepository — async player data access.

Extracted from postgres.py during code health decomposition.
"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.models.player import Player


class PostgresPlayerRepository:
    """Async Postgres-backed player repository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create_player(self, handle: str) -> Player:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "INSERT INTO players (id, handle) "
                    "VALUES (:id, :handle) "
                    "RETURNING id, handle, status, "
                    "suspended_reason, created_at"
                ),
                {"id": uuid4(), "handle": handle},
            )
            row = result.one()
            await session.commit()
            return Player(
                id=row.id,
                handle=row.handle,
                status=row.status,
                suspended_reason=row.suspended_reason,
                created_at=row.created_at,
            )

    async def get_player(self, player_id: UUID) -> Player | None:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT id, handle, status, suspended_reason, "
                    "created_at FROM players WHERE id = :id"
                ),
                {"id": player_id},
            )
            row = result.one_or_none()
            if row is None:
                return None
            return Player(
                id=row.id,
                handle=row.handle,
                status=row.status,
                suspended_reason=row.suspended_reason,
                created_at=row.created_at,
            )

    async def get_player_by_handle(self, handle: str) -> Player | None:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT id, handle, status, suspended_reason, "
                    "created_at FROM players "
                    "WHERE handle = :handle"
                ),
                {"handle": handle},
            )
            row = result.one_or_none()
            if row is None:
                return None
            return Player(
                id=row.id,
                handle=row.handle,
                status=row.status,
                suspended_reason=row.suspended_reason,
                created_at=row.created_at,
            )
