"""PostgresTurnRepository — async turn data access.

Extracted from postgres.py during code health decomposition.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession


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

    async def fail_turn(
        self,
        turn_id: UUID,
        narrative_output: str | None = None,
    ) -> None:
        async with self._sf() as session:
            if narrative_output is not None:
                await session.execute(
                    sa.text(
                        "UPDATE turns SET status = 'failed', "
                        "narrative_output = :narrative_output "
                        "WHERE id = :id"
                    ),
                    {"id": turn_id, "narrative_output": narrative_output},
                )
            else:
                await session.execute(
                    sa.text("UPDATE turns SET status = 'failed' WHERE id = :id"),
                    {"id": turn_id},
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

    async def get_recent_turns(self, session_id: UUID, limit: int = 10) -> list[dict]:
        """Return the *limit* most recent completed turns, oldest-first."""
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
                    "AND status IN ('complete', 'moderated') "
                    "ORDER BY turn_number DESC "
                    "LIMIT :lim"
                ),
                {"session_id": session_id, "lim": limit},
            )
            rows = result.all()
            # Return oldest-first
            return [self._row_to_dict(r) for r in reversed(rows)]

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
