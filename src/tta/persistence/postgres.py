"""PostgreSQL persistence — repository classes and legacy stubs.

Repository classes provide real async implementations backed by
SQLAlchemy + asyncpg.  The module-level stub functions are retained
for backward compatibility with existing tests.
"""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.models.game import GameSession, GameStatus
from tta.models.player import Player, PlayerSession
from tta.models.world import WorldEvent

# =====================================================================
# Repository classes (Wave 1 — real implementations)
# =====================================================================


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
                    "RETURNING id, handle, created_at"
                ),
                {"id": uuid4(), "handle": handle},
            )
            row = result.one()
            await session.commit()
            return Player(
                id=row.id,
                handle=row.handle,
                created_at=row.created_at,
            )

    async def get_player(self, player_id: UUID) -> Player | None:
        async with self._sf() as session:
            result = await session.execute(
                sa.text("SELECT id, handle, created_at FROM players WHERE id = :id"),
                {"id": player_id},
            )
            row = result.one_or_none()
            if row is None:
                return None
            return Player(
                id=row.id,
                handle=row.handle,
                created_at=row.created_at,
            )

    async def get_player_by_handle(self, handle: str) -> Player | None:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT id, handle, created_at FROM players WHERE handle = :handle"
                ),
                {"handle": handle},
            )
            row = result.one_or_none()
            if row is None:
                return None
            return Player(
                id=row.id,
                handle=row.handle,
                created_at=row.created_at,
            )


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
                    "status, created_at, updated_at"
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
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def get_game(self, game_id: UUID) -> GameSession | None:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT id, player_id, world_seed, "
                    "status, created_at, updated_at "
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

    async def list_player_games(self, player_id: UUID) -> list[GameSession]:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT id, player_id, world_seed, "
                    "status, created_at, updated_at "
                    "FROM game_sessions "
                    "WHERE player_id = :player_id "
                    "ORDER BY created_at DESC"
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
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
                for r in rows
            ]


class PostgresTurnRepository:
    """Async Postgres-backed turn repository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create_turn(
        self,
        session_id: UUID,
        turn_number: int,
        player_input: str,
        idempotency_key: UUID | None = None,
    ) -> dict:
        turn_id = uuid4()
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "INSERT INTO turns "
                    "(id, session_id, turn_number, "
                    "player_input, idempotency_key) "
                    "VALUES (:id, :session_id, :turn_number, "
                    ":player_input, :idempotency_key) "
                    "RETURNING id, session_id, turn_number, "
                    "player_input, idempotency_key, status, "
                    "created_at"
                ),
                {
                    "id": turn_id,
                    "session_id": session_id,
                    "turn_number": turn_number,
                    "player_input": player_input,
                    "idempotency_key": idempotency_key,
                },
            )
            row = result.one()
            await session.commit()
            return {
                "id": row.id,
                "session_id": row.session_id,
                "turn_number": row.turn_number,
                "player_input": row.player_input,
                "idempotency_key": row.idempotency_key,
                "status": row.status,
                "narrative_output": None,
                "model_used": None,
                "latency_ms": None,
                "token_count": None,
                "created_at": row.created_at,
                "completed_at": None,
            }

    async def get_turn(self, turn_id: UUID) -> dict | None:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT id, session_id, turn_number, "
                    "player_input, idempotency_key, status, "
                    "narrative_output, model_used, "
                    "latency_ms, token_count, "
                    "created_at, completed_at "
                    "FROM turns WHERE id = :id"
                ),
                {"id": turn_id},
            )
            row = result.one_or_none()
            if row is None:
                return None
            return self._row_to_dict(row)

    async def complete_turn(
        self,
        turn_id: UUID,
        narrative_output: str,
        model_used: str,
        latency_ms: float,
        token_count: dict,
    ) -> None:
        now = datetime.now(UTC)
        async with self._sf() as session:
            await session.execute(
                sa.text(
                    "UPDATE turns SET "
                    "narrative_output = :narrative_output, "
                    "model_used = :model_used, "
                    "latency_ms = :latency_ms, "
                    "token_count = "
                    "cast(:token_count AS jsonb), "
                    "status = 'complete', "
                    "completed_at = :now "
                    "WHERE id = :id"
                ),
                {
                    "id": turn_id,
                    "narrative_output": narrative_output,
                    "model_used": model_used,
                    "latency_ms": latency_ms,
                    "token_count": json.dumps(token_count),
                    "now": now,
                },
            )
            await session.commit()

    async def update_status(self, turn_id: UUID, status: str) -> None:
        async with self._sf() as session:
            await session.execute(
                sa.text("UPDATE turns SET status = :status WHERE id = :id"),
                {"id": turn_id, "status": status},
            )
            await session.commit()

    async def get_processing_turn(self, session_id: UUID) -> dict | None:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT id, session_id, turn_number, "
                    "player_input, idempotency_key, status, "
                    "narrative_output, model_used, "
                    "latency_ms, token_count, "
                    "created_at, completed_at "
                    "FROM turns "
                    "WHERE session_id = :session_id "
                    "AND status = 'processing' "
                    "LIMIT 1"
                ),
                {"session_id": session_id},
            )
            row = result.one_or_none()
            if row is None:
                return None
            return self._row_to_dict(row)

    async def get_turn_by_idempotency_key(
        self, session_id: UUID, key: UUID
    ) -> dict | None:
        async with self._sf() as session:
            result = await session.execute(
                sa.text(
                    "SELECT id, session_id, turn_number, "
                    "player_input, idempotency_key, status, "
                    "narrative_output, model_used, "
                    "latency_ms, token_count, "
                    "created_at, completed_at "
                    "FROM turns "
                    "WHERE session_id = :session_id "
                    "AND idempotency_key = :key"
                ),
                {"session_id": session_id, "key": key},
            )
            row = result.one_or_none()
            if row is None:
                return None
            return self._row_to_dict(row)

    @staticmethod
    def _row_to_dict(row: sa.Row[tuple]) -> dict:
        return {
            "id": row.id,
            "session_id": row.session_id,
            "turn_number": row.turn_number,
            "player_input": row.player_input,
            "idempotency_key": row.idempotency_key,
            "status": row.status,
            "narrative_output": row.narrative_output,
            "model_used": row.model_used,
            "latency_ms": row.latency_ms,
            "token_count": row.token_count,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
        }


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


async def create_player(handle: str) -> Player:
    """Register a new player by handle."""
    raise NotImplementedError


async def get_player(player_id: UUID) -> Player | None:
    """Look up a player by primary key."""
    raise NotImplementedError


async def get_player_by_handle(handle: str) -> Player | None:
    """Look up a player by unique handle."""
    raise NotImplementedError


# ── Session persistence ──────────────────────────────────────────


async def create_session(
    player_id: UUID,
    token: str,
    expires_at: datetime,
) -> PlayerSession:
    """Create an authenticated player session."""
    raise NotImplementedError


async def get_session(token: str) -> PlayerSession | None:
    """Retrieve a session by its bearer token."""
    raise NotImplementedError


async def delete_session(token: str) -> None:
    """Revoke / delete a session token."""
    raise NotImplementedError


# ── Game persistence ─────────────────────────────────────────────


async def create_game(
    player_id: UUID,
    world_seed: dict,
) -> GameSession:
    """Start a new game for a player."""
    raise NotImplementedError


async def get_game(game_id: UUID) -> GameSession | None:
    """Fetch a game session by ID."""
    raise NotImplementedError


async def update_game_status(
    game_id: UUID,
    status: GameStatus,
) -> None:
    """Transition a game to a new lifecycle status."""
    raise NotImplementedError


async def list_player_games(
    player_id: UUID,
) -> list[GameSession]:
    """Return all game sessions belonging to a player."""
    raise NotImplementedError


# ── Turn persistence ─────────────────────────────────────────────


async def create_turn(
    session_id: UUID,
    turn_number: int,
    player_input: str,
    idempotency_key: UUID | None = None,
) -> dict:
    """Record the start of a new turn."""
    raise NotImplementedError


async def get_turn(turn_id: UUID) -> dict | None:
    """Fetch a turn record by ID."""
    raise NotImplementedError


async def complete_turn(
    turn_id: UUID,
    narrative_output: str,
    model_used: str,
    latency_ms: float,
    token_count: dict,
) -> None:
    """Mark a turn as complete with its results."""
    raise NotImplementedError


async def get_processing_turn(
    session_id: UUID,
) -> dict | None:
    """Find the currently-processing turn for a session."""
    raise NotImplementedError


async def update_status(
    turn_id: UUID,
    status: str,
) -> None:
    """Update a turn's status (processing/complete/failed)."""
    raise NotImplementedError


async def get_turn_by_idempotency_key(
    session_id: UUID,
    key: UUID,
) -> dict | None:
    """Look up a turn by its idempotency key."""
    raise NotImplementedError


# ── World-event persistence ──────────────────────────────────────


async def create_world_event(
    session_id: UUID,
    turn_id: UUID,
    event_type: str,
    entity_id: str,
    payload: dict,
) -> WorldEvent:
    """Persist a world-state mutation event."""
    raise NotImplementedError


async def get_recent_events(
    session_id: UUID,
    limit: int = 5,
) -> list[WorldEvent]:
    """Return the most recent world events for a session."""
    raise NotImplementedError
