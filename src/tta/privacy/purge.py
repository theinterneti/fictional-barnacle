"""Automated data purge for S17 FR-17.15 and FR-27.17 retention enforcement.

Two purge paths:
  - Soft-deleted games (``deleted_at IS NOT NULL``): 72 hours (3 days).
  - Completed/expired sessions: 90 days.

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


def _retention_days(category: str, default: int) -> int:
    policy = get_retention_policy(category)
    if policy and policy.retention_days is not None:
        return policy.retention_days
    return default


def _soft_delete_retention_days() -> int:
    return _retention_days("soft_deleted_game_postgresql", 3)


def _completed_retention_days() -> int:
    return _retention_days("completed_session_postgresql", 90)


async def _collect_session_ids(
    pg: Any,
    cutoff_soft: datetime,
    cutoff_completed: datetime,
) -> list:
    """Find sessions eligible for purge across both retention paths."""
    # Path 1: Soft-deleted games (player-deleted via GDPR or /end)
    r1 = await pg.execute(
        sa.text(
            "SELECT id FROM game_sessions "
            "WHERE deleted_at IS NOT NULL "
            "AND deleted_at < :cutoff"
        ),
        {"cutoff": cutoff_soft},
    )
    ids_soft = [row[0] for row in r1.fetchall()]

    # Path 2: Completed/expired sessions (natural lifecycle)
    r2 = await pg.execute(
        sa.text(
            "SELECT id FROM game_sessions "
            "WHERE status IN ('ended', 'completed', 'expired') "
            "AND deleted_at IS NULL "
            "AND updated_at < :cutoff"
        ),
        {"cutoff": cutoff_completed},
    )
    ids_completed = [row[0] for row in r2.fetchall()]

    return ids_soft + ids_completed


async def _delete_sessions(
    pg: Any, session_ids: list
) -> dict[str, int]:
    """Delete sessions and dependents in FK-safe order."""
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
    return {
        "sessions": sessions_deleted,
        "turns": turns_deleted,
        "world_events": world_events_deleted,
    }


async def run_purge(
    session_factory: Any,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a single purge pass.

    Returns a summary dict with counts of affected rows.
    """
    now = datetime.now(UTC)
    cutoff_soft = now - timedelta(days=_soft_delete_retention_days())
    cutoff_completed = now - timedelta(days=_completed_retention_days())

    async with session_factory() as pg:
        session_ids = await _collect_session_ids(
            pg, cutoff_soft, cutoff_completed
        )

        if not session_ids:
            log.info("purge_pass", action="noop", sessions=0)
            return {
                "sessions_purged": 0,
                "turns_purged": 0,
                "dry_run": dry_run,
                "cutoff_soft_delete": cutoff_soft.isoformat(),
                "cutoff_completed": cutoff_completed.isoformat(),
            }

        if dry_run:
            we_result = await pg.execute(
                sa.text(
                    "SELECT count(*) FROM world_events "
                    "WHERE session_id = ANY(:ids)"
                ),
                {"ids": session_ids},
            )
            world_events_count = we_result.scalar() or 0
            turn_result = await pg.execute(
                sa.text(
                    "SELECT count(*) FROM turns "
                    "WHERE session_id = ANY(:ids)"
                ),
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
                "cutoff_soft_delete": cutoff_soft.isoformat(),
                "cutoff_completed": cutoff_completed.isoformat(),
            }

        deleted = await _delete_sessions(pg, session_ids)

        log.info(
            "purge_pass",
            action="executed",
            sessions=deleted["sessions"],
            turns=deleted["turns"],
            world_events=deleted["world_events"],
        )
        return {
            "sessions_purged": deleted["sessions"],
            "turns_purged": deleted["turns"],
            "world_events_purged": deleted["world_events"],
            "dry_run": False,
            "cutoff_soft_delete": cutoff_soft.isoformat(),
            "cutoff_completed": cutoff_completed.isoformat(),
        }


async def purge_loop(
    session_factory: Any,
    *,
    interval_seconds: int = 3600,
) -> None:
    """Run purge passes on a timer until cancelled.

    Default interval is 1 hour to meet the 72h ± 1h SLA
    for soft-deleted data (FR-27.17).
    """
    log.info(
        "purge_loop_started",
        interval_seconds=interval_seconds,
    )
    while True:
        try:
            await run_purge(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("purge_pass_failed")
        await asyncio.sleep(interval_seconds)
