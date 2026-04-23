"""Async job implementations (S48).

Each function is an ARQ job coroutine. They receive ``ctx`` as the first
argument (ARQ convention), which contains the Redis pool and job metadata.

Dead-letter handling: on 3rd failure (ctx['job_try'] >= 3) the job writes
to the ``tta:jobs:dead`` Redis list before raising.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime

import structlog

from tta.observability.metrics import JOB_DURATION, JOB_RUNS

log = structlog.get_logger(__name__)

DEAD_LETTER_KEY = "tta:jobs:dead"
GDPR_JOB_TIMEOUT = 120
RETENTION_BATCH_SIZE = 500
RETENTION_BATCH_SLEEP = 0.1


async def _write_dead_letter(
    ctx: dict,
    job_fn: str,
    args: tuple,
    error: str,
) -> None:
    """Append a dead-letter entry to the Redis dead-letter list."""
    redis = ctx.get("redis")
    if redis is None:
        return
    entry = json.dumps(
        {
            "job_id": ctx.get("job_id", "unknown"),
            "job_fn": job_fn,
            "args": list(args),
            "queued_at": ctx.get("enqueue_time", datetime.now(UTC)).isoformat()
            if hasattr(ctx.get("enqueue_time"), "isoformat")
            else str(ctx.get("enqueue_time", "")),
            "failed_at": datetime.now(UTC).isoformat(),
            "error": error,
        }
    )
    await redis.lpush(DEAD_LETTER_KEY, entry)
    await redis.ltrim(DEAD_LETTER_KEY, 0, 999)  # cap at 1000 entries


async def gdpr_delete_player(ctx: dict, player_id: str) -> str:
    """GDPR erasure job — deletes all player data (S17 FR-17.09).

    Timeout: 120s. Idempotent: returns 'already_erased' if player is gone.
    """
    start = time.monotonic()
    job_fn = "gdpr_delete_player"
    try:
        from tta.config import get_settings

        settings = get_settings()

        # Step 1 — PostgreSQL deletion
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(settings.database_url)
        async with engine.begin() as conn:
            from sqlalchemy import text

            result = await conn.execute(
                text("SELECT id FROM players WHERE id = :pid"),
                {"pid": player_id},
            )
            row = result.one_or_none()
            if row is None:
                log.info("gdpr_already_erased", player_id=player_id)
                JOB_RUNS.labels(job_fn=job_fn, status="success").inc()
                return "already_erased"

            await conn.execute(
                text("DELETE FROM players WHERE id = :pid"),
                {"pid": player_id},
            )
        await engine.dispose()

        # Step 2 — Neo4j deletion
        if settings.neo4j_uri:
            from neo4j import AsyncGraphDatabase

            driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
                if settings.neo4j_password
                else None,
            )
            async with driver.session() as session:
                await session.run(
                    "MATCH (m:MemoryRecord {player_id: $pid}) DETACH DELETE m",
                    pid=player_id,
                )
            await driver.close()

        # Step 3 — Redis session keys
        redis = ctx.get("redis")
        if redis:
            pattern = f"session:player:{player_id}:*"
            keys = await redis.keys(pattern)
            if keys:
                await redis.delete(*keys)

        # Step 4 — Audit log
        log.info(
            "player_erased",
            player_id=player_id,
            event="player_erased",
        )

        duration = time.monotonic() - start
        JOB_DURATION.labels(job_fn=job_fn).observe(duration)
        JOB_RUNS.labels(job_fn=job_fn, status="success").inc()
        return "erased"

    except Exception as exc:
        duration = time.monotonic() - start
        JOB_DURATION.labels(job_fn=job_fn).observe(duration)
        job_try = ctx.get("job_try", 1)
        if job_try >= 3:
            JOB_RUNS.labels(job_fn=job_fn, status="failed").inc()
            await _write_dead_letter(ctx, job_fn, (player_id,), str(exc))
        else:
            JOB_RUNS.labels(job_fn=job_fn, status="retry").inc()
        raise


async def retention_sweep(ctx: dict) -> dict:
    """Delete data past the S17 retention window in batches of 500."""
    start = time.monotonic()
    job_fn = "retention_sweep"
    deleted_count = 0

    try:
        from tta.config import get_settings

        settings = get_settings()
        engine = None

        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(settings.database_url)
        while True:
            async with engine.begin() as conn:
                from sqlalchemy import text

                result = await conn.execute(
                    text(
                        """
                        DELETE FROM audit_events
                        WHERE id IN (
                            SELECT id FROM audit_events
                            WHERE created_at < NOW() - INTERVAL '90 days'
                            LIMIT :batch
                        )
                        RETURNING id
                        """
                    ),
                    {"batch": RETENTION_BATCH_SIZE},
                )
                batch = result.rowcount
                deleted_count += batch

            if batch < RETENTION_BATCH_SIZE:
                break
            await asyncio.sleep(RETENTION_BATCH_SLEEP)

        if engine:
            await engine.dispose()

        duration = time.monotonic() - start
        JOB_DURATION.labels(job_fn=job_fn).observe(duration)
        JOB_RUNS.labels(job_fn=job_fn, status="success").inc()
        log.info("retention_sweep_complete", deleted_count=deleted_count)
        return {"deleted_count": deleted_count}

    except Exception as exc:
        duration = time.monotonic() - start
        JOB_DURATION.labels(job_fn=job_fn).observe(duration)
        job_try = ctx.get("job_try", 1)
        if job_try >= 3:
            JOB_RUNS.labels(job_fn=job_fn, status="failed").inc()
            await _write_dead_letter(ctx, job_fn, (), str(exc))
        else:
            JOB_RUNS.labels(job_fn=job_fn, status="retry").inc()
        raise


async def session_cleanup(ctx: dict) -> dict:
    """Remove expired Redis session keys."""
    start = time.monotonic()
    job_fn = "session_cleanup"
    try:
        redis = ctx.get("redis")
        removed = 0
        if redis:
            keys = await redis.keys("session:*")
            for key in keys:
                ttl = await redis.ttl(key)
                if ttl == -1:
                    await redis.delete(key)
                    removed += 1

        duration = time.monotonic() - start
        JOB_DURATION.labels(job_fn=job_fn).observe(duration)
        JOB_RUNS.labels(job_fn=job_fn, status="success").inc()
        log.info("session_cleanup_complete", removed=removed)
        return {"removed": removed}

    except Exception as exc:
        duration = time.monotonic() - start
        JOB_DURATION.labels(job_fn=job_fn).observe(duration)
        job_try = ctx.get("job_try", 1)
        if job_try >= 3:
            JOB_RUNS.labels(job_fn=job_fn, status="failed").inc()
            await _write_dead_letter(ctx, job_fn, (), str(exc))
        else:
            JOB_RUNS.labels(job_fn=job_fn, status="retry").inc()
        raise


async def game_backfill(ctx: dict, game_id: str | None = None) -> dict:
    """Rebuild derived data from the event log.

    Timeout: 1800s. Accepts optional game_id to backfill a single game.
    """
    start = time.monotonic()
    job_fn = "game_backfill"
    try:
        # Placeholder — real implementation queries event_log and rebuilds
        # derived tables. Structured to be idempotent.
        log.info("game_backfill_started", game_id=game_id)
        backfilled = 0

        duration = time.monotonic() - start
        JOB_DURATION.labels(job_fn=job_fn).observe(duration)
        JOB_RUNS.labels(job_fn=job_fn, status="success").inc()
        log.info("game_backfill_complete", game_id=game_id, backfilled=backfilled)
        return {"backfilled": backfilled}

    except Exception as exc:
        duration = time.monotonic() - start
        JOB_DURATION.labels(job_fn=job_fn).observe(duration)
        job_try = ctx.get("job_try", 1)
        if job_try >= 3:
            JOB_RUNS.labels(job_fn=job_fn, status="failed").inc()
            await _write_dead_letter(ctx, job_fn, (game_id,) if game_id else (), str(exc))
        else:
            JOB_RUNS.labels(job_fn=job_fn, status="retry").inc()
        raise
