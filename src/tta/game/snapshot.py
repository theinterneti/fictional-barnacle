"""Periodic game-state snapshots to PostgreSQL (AC-12.04).

Snapshots are fire-and-forget safe — callers catch and log all errors
so that a snapshot failure never blocks gameplay.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import sqlalchemy as sa
import structlog

from tta.models.game import GameState

log = structlog.get_logger()

# Shared async-session-factory type (same as used by TurnRepository)
SessionFactory = Callable[..., Any]


class GameSnapshotService:
    """Persist and retrieve periodic GameState snapshots."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._sf = session_factory

    async def save_snapshot(
        self,
        game_session_id: UUID,
        state: GameState,
    ) -> None:
        """Persist a snapshot of *state* for *game_session_id*."""
        payload = json.loads(state.model_dump_json())
        async with self._sf() as sess:
            await sess.execute(
                sa.text(
                    "INSERT INTO game_snapshots"
                    " (game_session_id, turn_number, world_state)"
                    " VALUES (:gid, :turn, CAST(:payload AS jsonb))"
                ),
                {
                    "gid": game_session_id,
                    "turn": state.turn_number,
                    "payload": json.dumps(payload),
                },
            )
            await sess.commit()
        log.info(
            "snapshot_saved",
            game_session_id=str(game_session_id),
            turn_number=state.turn_number,
        )

    async def get_latest_snapshot(
        self,
        game_session_id: UUID,
    ) -> tuple[int, GameState] | None:
        """Return ``(turn_number, GameState)`` for the most recent snapshot,
        or *None* if no snapshot exists."""
        async with self._sf() as sess:
            row = (
                await sess.execute(
                    sa.text(
                        "SELECT turn_number, world_state"
                        " FROM game_snapshots"
                        " WHERE game_session_id = :gid"
                        " ORDER BY turn_number DESC"
                        " LIMIT 1"
                    ),
                    {"gid": game_session_id},
                )
            ).one_or_none()
        if row is None:
            return None
        turn_number: int = row.turn_number
        world_state: Any = row.world_state
        # world_state may come back as dict (asyncpg jsonb) or str
        if isinstance(world_state, str):
            world_state = json.loads(world_state)
        return turn_number, GameState.model_validate(world_state)
