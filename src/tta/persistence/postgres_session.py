"""PostgresSessionRepository — async session token management.

Extracted from postgres.py during code health decomposition.
"""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.models.player import PlayerSession


class PostgresSessionRepository:
    """Async Postgres-backed player-session repository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create_session(
        self,
        player_id: UUID,
        token: str,
        expires_at: datetime,
    ) -> PlayerSession:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "INSERT INTO player_sessions "
                    "(player_id, token, expires_at) "
                    "VALUES (:player_id, :token, :expires_at) "
                    "RETURNING player_id, token, "
                    "expires_at, created_at"
                ),
                {
                    "player_id": player_id,
                    "token": token,
                    "expires_at": expires_at,
                },
            )
            row = result.one()
            await session.commit()
            return PlayerSession(
                player_id=row.player_id,
                token=row.token,
                expires_at=row.expires_at,
                created_at=row.created_at,
            )

    async def get_session(self, token: str) -> PlayerSession | None:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT player_id, token, "
                    "expires_at, created_at "
                    "FROM player_sessions WHERE token = :token"
                ),
                {"token": token},
            )
            row = result.one_or_none()
            if row is None:
                return None
            return PlayerSession(
                player_id=row.player_id,
                token=row.token,
                expires_at=row.expires_at,
                created_at=row.created_at,
            )

    async def delete_session(self, token: str) -> None:
        async with self._sf() as session:
            await session.execute(
                sa.text("DELETE FROM player_sessions WHERE token = :token"),
                {"token": token},
            )
            await session.commit()
