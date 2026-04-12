"""Redis TTL compliance monitoring (AC-12.12).

Periodically scans tta:* keys and reports any that lack a TTL.
Uses incremental SCAN with small COUNT to avoid blocking Redis.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

import structlog
from redis.asyncio import Redis

from tta.observability.metrics import REDIS_KEYS_WITHOUT_TTL

log = structlog.get_logger()

_SCAN_MATCH = "tta:*"
_SCAN_COUNT = 50
_BATCH_PAUSE_S = 0.0  # yield to event loop between batches
_DEFAULT_INTERVAL_S = 1800  # 30 minutes


async def audit_ttl_compliance(redis: Redis) -> dict[str, int]:
    """Scan tta:* keys and return counts of TTL-less keys per prefix.

    Returns only prefixes with one or more missing TTLs, for example
    ``{"tta:session": 2}``.  Updates the ``tta_redis_keys_without_ttl``
    gauge (one label per prefix).
    """
    missing: dict[str, int] = defaultdict(int)
    total_missing = 0
    cursor: int = 0

    while True:
        cursor, keys = await redis.scan(  # type: ignore[assignment]
            cursor=cursor,
            match=_SCAN_MATCH,
            count=_SCAN_COUNT,
        )

        if keys:
            async with redis.pipeline(transaction=False) as pipe:
                for key in keys:
                    pipe.ttl(key)
                ttls = await pipe.execute()

            for key, ttl_val in zip(keys, ttls, strict=True):
                if ttl_val == -1:  # no expiry set
                    key_str = key.decode() if isinstance(key, bytes) else key
                    # Group by second colon segment: tta:<prefix>:*
                    parts = key_str.split(":", 3)
                    prefix = ":".join(parts[:2]) if len(parts) >= 2 else key_str
                    missing[prefix] += 1
                    total_missing += 1

        if cursor == 0:
            break
        if _BATCH_PAUSE_S:
            await asyncio.sleep(_BATCH_PAUSE_S)
        else:
            await asyncio.sleep(0)

    for prefix, count in missing.items():
        REDIS_KEYS_WITHOUT_TTL.labels(prefix=prefix).set(count)
    if total_missing > 0:
        log.warning(
            "redis_ttl_audit_violations",
            missing_ttl_count=total_missing,
            by_prefix=dict(missing),
        )
    else:
        log.info("redis_ttl_audit_ok")
    return dict(missing)


async def ttl_monitor_loop(
    redis: Redis,
    *,
    interval_s: float = _DEFAULT_INTERVAL_S,
) -> None:
    """Background loop that runs TTL audits on an interval.

    Designed to be started via ``asyncio.create_task()`` in the
    FastAPI lifespan and cancelled on shutdown.
    """
    log.info("ttl_monitor_started", interval_s=interval_s)
    while True:
        try:
            await audit_ttl_compliance(redis)
        except Exception:
            log.exception("ttl_monitor_error")
        await asyncio.sleep(interval_s)
