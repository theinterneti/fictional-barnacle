"""Automated game-session lifecycle transitions (S11 FR-11.41–45, AC-1.7).

Transitions enforced:
  - ``created``/``active``  + 0 turns + age > 24 h  →  ``abandoned``
  - ``paused``  + paused_at older than 30 days  →  ``expired``
  - ``active``  + turn_count > 0 + idle > 30 min  →  ``paused``  (AC-1.7)
  - Anonymous players with no active games + 30 d old  →  soft-deleted
    (FR-11.12, FR-11.59)

Usage:
  - Background: started automatically by the FastAPI lifespan.
  - Manual: import ``run_lifecycle_pass`` for one-off execution.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
import structlog

log = structlog.get_logger()

# Thresholds (match spec S11 FR-11.41–45 + AC-1.7)
ABANDON_HOURS = 24
EXPIRE_DAYS = 30
IDLE_TIMEOUT_MINUTES = 30
ANON_CLEANUP_DAYS = 30


async def run_lifecycle_pass(
    session_factory: Any,
    *,
    abandon_hours: int = ABANDON_HOURS,
    expire_days: int = EXPIRE_DAYS,
    idle_timeout_minutes: int = IDLE_TIMEOUT_MINUTES,
    anon_cleanup_days: int = ANON_CLEANUP_DAYS,
) -> dict[str, int]:
    """Execute a single lifecycle-transition pass.

    Returns a summary dict with counts of affected rows.
    """
    now = datetime.now(UTC)
    abandon_cutoff = now - timedelta(hours=abandon_hours)
    expire_cutoff = now - timedelta(days=expire_days)
    idle_cutoff = now - timedelta(minutes=idle_timeout_minutes)
    anon_cutoff = now - timedelta(days=anon_cleanup_days)

    async with session_factory() as pg:
        # Rule 1: created/active + 0 turns + older than 24 h → abandoned
        abandon_result = await pg.execute(
            sa.text(
                "UPDATE game_sessions "
                "SET status = 'abandoned', updated_at = :now "
                "WHERE status IN ('created', 'active') "
                "AND turn_count = 0 "
                "AND created_at < :cutoff "
                "AND deleted_at IS NULL"
            ),
            {"now": now, "cutoff": abandon_cutoff},
        )
        abandoned = abandon_result.rowcount or 0

        # Rule 2: paused + paused_at < cutoff (older than 30 days) → expired
        # NULL fallback: pre-migration rows use last_played_at instead
        expire_result = await pg.execute(
            sa.text(
                "UPDATE game_sessions "
                "SET status = 'expired', updated_at = :now "
                "WHERE status = 'paused' "
                "AND ("
                "paused_at < :cutoff "
                "OR (paused_at IS NULL AND last_played_at < :cutoff)"
                ") "
                "AND deleted_at IS NULL"
            ),
            {"now": now, "cutoff": expire_cutoff},
        )
        expired = expire_result.rowcount or 0

        # Rule 3 (AC-1.7): active + turn_count > 0 + idle > 30 min → paused
        idle_result = await pg.execute(
            sa.text(
                "UPDATE game_sessions "
                "SET status = 'paused', paused_at = :now, updated_at = :now "
                "WHERE status = 'active' "
                "AND turn_count > 0 "
                "AND updated_at < :cutoff "
                "AND deleted_at IS NULL"
            ),
            {"now": now, "cutoff": idle_cutoff},
        )
        idle_paused = idle_result.rowcount or 0

        # Rule 4 (FR-11.12, FR-11.59): anonymous players with no active
        # games and older than 30 days → soft-delete
        anon_result = await pg.execute(
            sa.text(
                "UPDATE players "
                "SET status = 'deleted', updated_at = :now "
                "WHERE is_anonymous = true "
                "AND status != 'deleted' "
                "AND created_at < :cutoff "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM game_sessions gs "
                "  WHERE gs.player_id = players.id "
                "  AND gs.status IN ('created', 'active', 'paused') "
                "  AND gs.deleted_at IS NULL"
                ")"
            ),
            {"now": now, "cutoff": anon_cutoff},
        )
        anon_cleaned = anon_result.rowcount or 0

        if abandoned or expired or idle_paused or anon_cleaned:
            await pg.commit()

        log.info(
            "lifecycle_pass",
            abandoned=abandoned,
            expired=expired,
            idle_paused=idle_paused,
            anon_cleaned=anon_cleaned,
        )
        return {
            "abandoned": abandoned,
            "expired": expired,
            "idle_paused": idle_paused,
            "anon_cleaned": anon_cleaned,
        }


async def lifecycle_loop(
    session_factory: Any,
    *,
    interval_seconds: int = 900,
    idle_timeout_minutes: int = IDLE_TIMEOUT_MINUTES,
    anon_cleanup_days: int = ANON_CLEANUP_DAYS,
) -> None:
    """Run lifecycle passes on a timer until cancelled."""
    log.info(
        "lifecycle_loop_started",
        interval_seconds=interval_seconds,
        idle_timeout_minutes=idle_timeout_minutes,
        anon_cleanup_days=anon_cleanup_days,
    )
    while True:
        try:
            await run_lifecycle_pass(
                session_factory,
                idle_timeout_minutes=idle_timeout_minutes,
                anon_cleanup_days=anon_cleanup_days,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("lifecycle_pass_failed")
        await asyncio.sleep(interval_seconds)
