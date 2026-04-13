"""Redis/SQL consistency checks (EC-12.01, AC-12.04).

Detects state drift between the Redis cache and the Postgres
source-of-truth.  When inconsistency is found, logs an error
and evicts the stale cache entry so the next read triggers a
safe SQL reconstruction (get_or_reconstruct_session).
"""

from __future__ import annotations

import hashlib
from uuid import UUID

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tta.observability.metrics import (
    STATE_DRIFT_CHECKS,
    STATE_DRIFT_DETECTED,
)
from tta.persistence.redis_session import (
    _KEY_PREFIX,
    _key,
    delete_active_session,
)

log = structlog.get_logger()


def _content_hash(data: bytes | str) -> str:
    """SHA-256 digest of serialised state for drift comparison."""
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


async def check_session_consistency(
    redis: Redis,
    pg: AsyncSession,
    session_id: UUID,
) -> bool:
    """Compare Redis-cached state against Postgres for one session.

    Returns True if consistent (or if the cache is empty — a miss
    is not a drift). Returns False if a mismatch is detected, in
    which case the stale Redis key is evicted.

    Spec reference: EC-12.01 — "Redis/SQL inconsistency detection."
    """
    STATE_DRIFT_CHECKS.inc()

    cached_raw: bytes | None = await redis.get(_key(session_id))
    if cached_raw is None:
        return True  # no cached state → nothing to drift

    # Fetch the authoritative SQL row
    import sqlalchemy as sa

    row = await pg.execute(
        sa.text("SELECT world_seed FROM game_sessions WHERE id = :sid"),
        {"sid": session_id},
    )
    sql_row = row.one_or_none()
    if sql_row is None:
        # Session exists in cache but not in SQL — stale phantom
        log.error(
            "state_drift_phantom_session",
            session_id=str(session_id),
            detail="Session found in Redis but missing from Postgres",
        )
        STATE_DRIFT_DETECTED.labels(kind="phantom").inc()
        await delete_active_session(redis, session_id)
        return False

    # Compare content hashes of the world_seed field
    sql_data = sql_row.world_seed or ""
    if isinstance(sql_data, dict):
        import json

        sql_data = json.dumps(sql_data, sort_keys=True)

    sql_hash = _content_hash(str(sql_data))
    cached_hash = _content_hash(cached_raw)

    if sql_hash != cached_hash:
        log.error(
            "state_drift_detected",
            session_id=str(session_id),
            sql_hash=sql_hash[:12],
            cache_hash=cached_hash[:12],
            detail="Redis cache diverged from Postgres source of truth",
        )
        STATE_DRIFT_DETECTED.labels(kind="content_mismatch").inc()
        await delete_active_session(redis, session_id)
        return False

    return True


async def audit_cache_consistency(
    redis: Redis,
    pg: AsyncSession,
    *,
    sample_limit: int = 100,
) -> dict:
    """Scan Redis session keys and check consistency against Postgres.

    Returns a summary dict with counts.  Intended for the background
    health monitor or admin API.

    Spec reference: AC-12.04 — "No state drift over 100 turns."
    """
    cursor: int | bytes = 0
    checked = 0
    drifted = 0
    errors = 0

    while checked < sample_limit:
        cursor, keys = await redis.scan(
            cursor=cursor,
            match=f"{_KEY_PREFIX}*",
            count=20,
        )
        for key in keys:
            if checked >= sample_limit:
                break
            # Extract session_id from key
            key_str = key.decode() if isinstance(key, bytes) else key
            sid_str = key_str.removeprefix(_KEY_PREFIX)
            try:
                sid = UUID(sid_str)
            except ValueError:
                continue
            try:
                ok = await check_session_consistency(redis, pg, sid)
                if not ok:
                    drifted += 1
            except Exception:
                log.warning(
                    "consistency_check_error",
                    session_id=sid_str,
                    exc_info=True,
                )
                errors += 1
            checked += 1

        if cursor == 0:
            break

    return {
        "checked": checked,
        "drifted": drifted,
        "errors": errors,
        "consistent": checked - drifted - errors,
    }
