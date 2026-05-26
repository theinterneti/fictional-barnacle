"""Shared query helpers for games route modules.

Extracted from games.py during code health decomposition (PR pattern).
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.errors import AppError
from tta.errors import ErrorCategory
from tta.models.player import Player

# --- Helper functions ---


async def _get_owned_game(pg: AsyncSession, game_id: UUID, player: Player) -> sa.Row:
    """Fetch a game row and verify ownership. Raises 404 if not found."""
    result = await pg.execute(
        sa.text(
            "SELECT id, player_id, status, world_seed, "
            "title, summary, turn_count, last_played_at, "
            "deleted_at, needs_recovery, summary_generated_at, "
            "total_cost_usd, cost_warning_sent, generation_profile, "
            "created_at, updated_at "
            "FROM game_sessions WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": game_id},
    )
    row = result.one_or_none()
    if row is None or row.player_id != player.id:
        raise AppError(ErrorCategory.NOT_FOUND, "GAME_NOT_FOUND", "Game not found.")
    return row


async def _count_active_games(pg: AsyncSession, player_id: UUID) -> int:
    """Count non-terminal games for the player."""
    result = await pg.execute(
        sa.text(
            "SELECT count(*) FROM game_sessions "
            "WHERE player_id = :pid "
            "AND status IN ('created', 'active', 'paused') "
            "AND deleted_at IS NULL"
        ),
        {"pid": player_id},
    )
    return result.scalar_one()


async def _get_turn_count(pg: AsyncSession, game_id: UUID) -> int:
    """Get the number of terminal turns (complete or moderated) for a game."""
    result = await pg.execute(
        sa.text(
            "SELECT count(*) FROM turns "
            "WHERE session_id = :sid AND status IN ('complete', 'moderated')"
        ),
        {"sid": game_id},
    )
    return result.scalar_one()


async def _get_max_turn_number(pg: AsyncSession, game_id: UUID) -> int:
    """Get the highest turn number for a game (0 if none).

    We count ALL turns regardless of status so that a failed turn still
    occupies its slot — preventing duplicate turn_number on retry
    (uq_turns_session_turn unique constraint).  Turn numbers may therefore
    skip if a turn fails, but the sequence is still monotonically increasing.
    """
    result = await pg.execute(
        sa.text(
            "SELECT coalesce(max(turn_number), 0) FROM turns WHERE session_id = :sid"
        ),
        {"sid": game_id},
    )
    return result.scalar_one()
