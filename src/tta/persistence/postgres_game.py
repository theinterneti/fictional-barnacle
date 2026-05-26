"""PostgresGameRepository — async game session data access.

Extracted from postgres.py during code health decomposition.
"""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.models.game import GameSession, GameStatus


class PostgresGameRepository:
    """Async Postgres-backed game-session repository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create_game(self, player_id: UUID, world_seed: dict) -> GameSession:
        game_id = uuid4()
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "INSERT INTO game_sessions "
                    "(id, player_id, world_seed) "
                    "VALUES (:id, :player_id, "
                    "cast(:world_seed AS jsonb)) "
                    "RETURNING id, player_id, world_seed, "
                    "status, generation_profile, total_cost_usd, cost_warning_sent, "
                    "created_at, updated_at"
                ),
                {
                    "id": game_id,
                    "player_id": player_id,
                    "world_seed": json.dumps(world_seed),
                },
            )
            row = result.one()
            await session.commit()
            return GameSession(
                id=row.id,
                player_id=row.player_id,
                world_seed=row.world_seed,
                status=GameStatus(row.status),
                generation_profile=row.generation_profile or "balanced",
                total_cost_usd=row.total_cost_usd,
                cost_warning_sent=row.cost_warning_sent,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def get_game(self, game_id: UUID) -> GameSession | None:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT id, player_id, world_seed, status, "
                    "title, summary, turn_count, needs_recovery, "
                    "generation_profile, total_cost_usd, cost_warning_sent, "
                    "last_played_at, deleted_at, "
                    "created_at, updated_at "
                    "FROM game_sessions WHERE id = :id"
                ),
                {"id": game_id},
            )
            row = result.one_or_none()
            if row is None:
                return None
            return GameSession(
                id=row.id,
                player_id=row.player_id,
                world_seed=row.world_seed,
                status=GameStatus(row.status),
                title=row.title,
                summary=row.summary,
                turn_count=row.turn_count,
                needs_recovery=row.needs_recovery,
                generation_profile=row.generation_profile or "balanced",
                total_cost_usd=row.total_cost_usd,
                cost_warning_sent=row.cost_warning_sent,
                last_played_at=row.last_played_at,
                deleted_at=row.deleted_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def update_game_status(self, game_id: UUID, status: GameStatus) -> None:
        async with self._sf() as session:
            await session.execute(
                sa.text(
                    "UPDATE game_sessions "
                    "SET status = :status, "
                    "updated_at = :now "
                    "WHERE id = :id"
                ),
                {
                    "id": game_id,
                    "status": status.value,
                    "now": datetime.now(UTC),
                },
            )
            await session.commit()

    async def accumulate_session_cost(
        self,
        game_id: UUID,
        cost_usd: float,
    ) -> tuple[float, bool]:
        """Atomically add *cost_usd* to the session total.

        Returns ``(new_total, cost_warning_sent)`` so the caller can
        decide whether an 80 % warning or 100 % refusal is needed.
        """
        now = datetime.now(UTC)
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "UPDATE game_sessions "
                    "SET total_cost_usd = total_cost_usd + :cost, "
                    "updated_at = :now "
                    "WHERE id = :id "
                    "RETURNING total_cost_usd, cost_warning_sent"
                ),
                {"id": game_id, "cost": cost_usd, "now": now},
            )
            row = result.one()
            await session.commit()
            return float(row.total_cost_usd), bool(row.cost_warning_sent)

    async def mark_cost_warning_sent(self, game_id: UUID) -> None:
        """Set cost_warning_sent flag so the 80 % warning fires once."""
        async with self._sf() as session:
            await session.execute(
                sa.text(
                    "UPDATE game_sessions "
                    "SET cost_warning_sent = true, "
                    "updated_at = :now "
                    "WHERE id = :id"
                ),
                {"id": game_id, "now": datetime.now(UTC)},
            )
            await session.commit()

    async def list_player_games(self, player_id: UUID) -> list[GameSession]:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT id, player_id, world_seed, status, "
                    "title, summary, turn_count, needs_recovery, "
                    "generation_profile, total_cost_usd, cost_warning_sent, "
                    "last_played_at, deleted_at, "
                    "created_at, updated_at "
                    "FROM game_sessions "
                    "WHERE player_id = :player_id "
                    "AND deleted_at IS NULL "
                    "ORDER BY last_played_at DESC NULLS LAST"
                ),
                {"player_id": player_id},
            )
            rows = result.all()
            return [
                GameSession(
                    id=r.id,
                    player_id=r.player_id,
                    world_seed=r.world_seed,
                    status=GameStatus(r.status),
                    title=r.title,
                    summary=r.summary,
                    turn_count=r.turn_count,
                    needs_recovery=r.needs_recovery,
                    generation_profile=r.generation_profile or "balanced",
                    total_cost_usd=r.total_cost_usd,
                    cost_warning_sent=r.cost_warning_sent,
                    last_played_at=r.last_played_at,
                    deleted_at=r.deleted_at,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
                for r in rows
            ]

    async def soft_delete(self, game_id: UUID) -> None:
        async with self._sf() as session:
            now = datetime.now(UTC)
            await session.execute(
                sa.text(
                    "UPDATE game_sessions "
                    "SET status = 'abandoned', "
                    "deleted_at = :now, updated_at = :now "
                    "WHERE id = :id"
                ),
                {"id": game_id, "now": now},
            )
            await session.commit()

    async def count_active_games(self, player_id: UUID) -> int:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT count(*) FROM game_sessions "
                    "WHERE player_id = :pid "
                    "AND status IN ('created', 'active', 'paused') "
                    "AND deleted_at IS NULL"
                ),
                {"pid": player_id},
            )
            return result.scalar_one()
