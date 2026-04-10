"""Automated data purge for S17 FR-17.15 retention enforcement.

Deletes completed/abandoned game sessions (and their turns) that
exceed the 90-day retention window defined in ``retention.py``.

Usage:
  - Background: started automatically by the FastAPI lifespan.
  - Manual: ``POST /admin/purge?dry_run=true`` for a one-off pass.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
import structlog

from tta.privacy.retention import get_retention_policy

log = structlog.get_logger()

_TERMINAL_STATUSES = ("ended", "abandoned", "completed", "expired")


def _retention_days() -> int:
    policy = get_retention_policy("completed_session_postgresql")
    if policy and policy.retention_days is not None:
        return policy.retention_days
    return 90


async def run_purge(
    session_factory: Any,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a single purge pass.

    Returns a summary dict with counts of affected rows.
    """
    retention = _retention_days()
    cutoff = datetime.now(UTC) - timedelta(days=retention)

    async with session_factory() as pg:
        # Find sessions to purge
        result = await pg.execute(
            sa.text(
                "SELECT id FROM game_sessions "
                "WHERE status = ANY(:statuses) "
                "AND updated_at < :cutoff"
            ),
            {"statuses": list(_TERMINAL_STATUSES), "cutoff": cutoff},
        )
        session_ids = [row[0] for row in result.fetchall()]

        if not session_ids:
            log.info("purge_pass", action="noop", sessions=0)
            return {
                "sessions_purged": 0,
                "turns_purged": 0,
                "dry_run": dry_run,
                "cutoff": cutoff.isoformat(),
            }

        if dry_run:
            # Count dependent rows without deleting
            we_result = await pg.execute(
                sa.text(
                    "SELECT count(*) FROM world_events WHERE session_id = ANY(:ids)"
                ),
                {"ids": session_ids},
            )
            world_events_count = we_result.scalar() or 0
            turn_result = await pg.execute(
                sa.text("SELECT count(*) FROM turns WHERE session_id = ANY(:ids)"),
                {"ids": session_ids},
            )
            turn_count = turn_result.scalar() or 0
            log.info(
                "purge_pass",
                action="dry_run",
                sessions=len(session_ids),
                turns=turn_count,
                world_events=world_events_count,
            )
            return {
                "sessions_purged": len(session_ids),
                "turns_purged": turn_count,
                "world_events_purged": world_events_count,
                "dry_run": True,
                "cutoff": cutoff.isoformat(),
            }

        # Delete in FK-safe order: world_events → turns → sessions.
        # world_events.turn_id → turns.id has no ON DELETE CASCADE,
        # so we must delete world_events before turns.
        we_result = await pg.execute(
            sa.text("DELETE FROM world_events WHERE session_id = ANY(:ids)"),
            {"ids": session_ids},
        )
        world_events_deleted = we_result.rowcount or 0

        turn_result = await pg.execute(
            sa.text("DELETE FROM turns WHERE session_id = ANY(:ids)"),
            {"ids": session_ids},
        )
        turns_deleted = turn_result.rowcount or 0

        session_result = await pg.execute(
            sa.text("DELETE FROM game_sessions WHERE id = ANY(:ids)"),
            {"ids": session_ids},
        )
        sessions_deleted = session_result.rowcount or 0

        await pg.commit()

        log.info(
            "purge_pass",
            action="executed",
            sessions=sessions_deleted,
            turns=turns_deleted,
            world_events=world_events_deleted,
            cutoff=cutoff.isoformat(),
        )
        return {
            "sessions_purged": sessions_deleted,
            "turns_purged": turns_deleted,
            "world_events_purged": world_events_deleted,
            "dry_run": False,
            "cutoff": cutoff.isoformat(),
        }


async def purge_loop(
    session_factory: Any,
    *,
    interval_hours: int = 24,
) -> None:
    """Run purge passes on a timer until cancelled."""
    log.info(
        "purge_loop_started",
        interval_hours=interval_hours,
    )
    while True:
        try:
            await run_purge(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("purge_pass_failed")
        await asyncio.sleep(interval_hours * 3600)
