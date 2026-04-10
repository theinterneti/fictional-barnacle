"""Automated game-session lifecycle transitions (S11 FR-11.41–45).

Transitions enforced:
  - ``active``  + 0 turns + age > 24 h  →  ``abandoned``
  - ``paused``  + last_played > 30 days  →  ``expired``

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

# Thresholds (match spec S11 FR-11.41–45)
ABANDON_HOURS = 24
EXPIRE_DAYS = 30


async def run_lifecycle_pass(
    session_factory: Any,
    *,
    abandon_hours: int = ABANDON_HOURS,
    expire_days: int = EXPIRE_DAYS,
) -> dict[str, int]:
    """Execute a single lifecycle-transition pass.

    Returns a summary dict with counts of affected rows.
    """
    now = datetime.now(UTC)
    abandon_cutoff = now - timedelta(hours=abandon_hours)
    expire_cutoff = now - timedelta(days=expire_days)

    async with session_factory() as pg:
        # Rule 1: active + 0 turns + older than 24 h → abandoned
        abandon_result = await pg.execute(
            sa.text(
                "UPDATE game_sessions "
                "SET status = 'abandoned', updated_at = :now "
                "WHERE status = 'active' "
                "AND turn_count = 0 "
                "AND created_at < :cutoff "
                "AND deleted_at IS NULL"
            ),
            {"now": now, "cutoff": abandon_cutoff},
        )
        abandoned = abandon_result.rowcount or 0

        # Rule 2: paused + last_played > 30 days → expired
        expire_result = await pg.execute(
            sa.text(
                "UPDATE game_sessions "
                "SET status = 'expired', updated_at = :now "
                "WHERE status = 'paused' "
                "AND last_played_at < :cutoff "
                "AND deleted_at IS NULL"
            ),
            {"now": now, "cutoff": expire_cutoff},
        )
        expired = expire_result.rowcount or 0

        if abandoned or expired:
            await pg.commit()

        log.info(
            "lifecycle_pass",
            abandoned=abandoned,
            expired=expired,
        )
        return {"abandoned": abandoned, "expired": expired}


async def lifecycle_loop(
    session_factory: Any,
    *,
    interval_hours: int = 1,
) -> None:
    """Run lifecycle passes on a timer until cancelled."""
    log.info("lifecycle_loop_started", interval_hours=interval_hours)
    while True:
        try:
            await run_lifecycle_pass(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("lifecycle_pass_failed")
        await asyncio.sleep(interval_hours * 3600)
