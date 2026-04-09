"""Anti-abuse detection with escalating cooldowns (S25 §3.5).

Detects abuse patterns and applies escalating cooldowns:

* **Rapid-fire** — repeated rate-limit violations from the same IP.
* **Credential stuffing** — repeated auth failures from one IP.
* **Connection flood** — excessive SSE connections from one IP
  (concurrent tracking requires SSE endpoint changes; deferred to #67).

Each pattern has its own detection threshold, window, and base cooldown
(FR-25.10).  Cooldowns escalate exponentially on repeated violations
within a configurable window (FR-25.11), capped at a configurable
maximum (default 24 hours).

Two backends implement the ``AbuseDetector`` protocol:

* **InMemoryAbuseDetector** — single-process fallback.
* **RedisAbuseDetector** — production backend using sorted sets + TTL keys.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import structlog

log = structlog.get_logger()

__all__ = [
    "AbuseDetector",
    "AbusePattern",
    "CooldownStatus",
    "InMemoryAbuseDetector",
    "RedisAbuseDetector",
    "ViolationResult",
]


class AbusePattern(StrEnum):
    """Abuse patterns detected by the system (FR-25.10)."""

    RAPID_FIRE = "rapid_fire"
    CREDENTIAL_STUFFING = "credential_stuffing"
    CONNECTION_FLOOD = "connection_flood"


@dataclass(frozen=True, slots=True)
class PatternConfig:
    """Detection parameters for a single abuse pattern."""

    threshold: int  # Violations before cooldown activates
    window_seconds: int  # Detection window duration
    base_cooldown_seconds: int  # Initial cooldown when threshold exceeded


# Thresholds from spec FR-25.10 / AC-25.8:
#   rapid-fire:  >3 rate-limit hits in 10 min → 120 s cooldown (2× normal window)
#                TODO: derive rapid-fire threshold from rate_limiter.max_requests
#                rather than hard-coding 3 — couples less tightly to config.
#   cred stuff:  >5 failed auth in 5 min → 900 s (15 min) block
#   conn flood:  >3 violations in 10 min → 120 s (placeholder; real concurrent
#                tracking requires SSE endpoint changes — see #67)
#
# TODO: escalation_window_seconds (separate from detection window) for
# controlling how quickly the cooldown multiplier resets after good behavior.
DEFAULT_PATTERN_CONFIGS: dict[AbusePattern, PatternConfig] = {
    AbusePattern.RAPID_FIRE: PatternConfig(
        threshold=3,
        window_seconds=600,
        base_cooldown_seconds=120,
    ),
    AbusePattern.CREDENTIAL_STUFFING: PatternConfig(
        threshold=5,
        window_seconds=300,
        base_cooldown_seconds=900,
    ),
    AbusePattern.CONNECTION_FLOOD: PatternConfig(
        threshold=3,
        window_seconds=600,
        base_cooldown_seconds=120,
    ),
}


@dataclass(frozen=True, slots=True)
class CooldownStatus:
    """Result of checking whether an identity is under cooldown."""

    active: bool
    remaining_seconds: int
    pattern: AbusePattern | None = None
    violation_count: int = 0


@dataclass(frozen=True, slots=True)
class ViolationResult:
    """Result of recording a violation."""

    cooldown_applied: bool
    cooldown_seconds: int
    violation_count: int
    escalated: bool  # True when beyond the first cooldown threshold


class AbuseDetector(Protocol):
    """Anti-abuse detection contract used by middleware."""

    async def check_cooldown(self, identity: str) -> CooldownStatus: ...

    async def record_violation(
        self, identity: str, pattern: AbusePattern
    ) -> ViolationResult: ...

    async def clear_cooldown(self, identity: str) -> None:
        """Remove cooldown for *identity* (admin unblock)."""
        ...


def _calculate_cooldown(
    violation_count: int,
    config: PatternConfig,
    max_cooldown: int,
) -> int:
    """Escalating cooldown: ``base × 2^(count − threshold)``, capped.

    AC-25.8: "cooldown period is doubled on each subsequent violation."
    FR-25.11: exponential up to configurable max (default 24 h).
    """
    # With `>` threshold semantics, the first trigger is at threshold + 1,
    # so subtract an extra 1 so the first offense gets base cooldown (excess=0).
    excess = max(0, violation_count - config.threshold - 1)
    # Cap exponent to prevent DoS via unbounded integer growth (2^10 = 1024×)
    raw = config.base_cooldown_seconds * (2 ** min(excess, 10))
    return min(int(raw), max_cooldown)


# ---------------------------------------------------------------------------
# In-memory backend (fallback)
# ---------------------------------------------------------------------------


class InMemoryAbuseDetector:
    """Dict-based abuse detection — single process only."""

    def __init__(
        self,
        *,
        max_cooldown: int = 86400,
        pattern_configs: dict[AbusePattern, PatternConfig] | None = None,
    ) -> None:
        self._max_cooldown = max_cooldown
        self._configs = pattern_configs or dict(DEFAULT_PATTERN_CONFIGS)
        # {f"{identity}:{pattern}": [timestamps]}
        self._violations: dict[str, list[float]] = {}
        # {identity: (expires_at, pattern, violation_count)}
        self._cooldowns: dict[str, tuple[float, AbusePattern, int]] = {}

    async def check_cooldown(self, identity: str) -> CooldownStatus:
        entry = self._cooldowns.get(identity)
        if entry is None:
            return CooldownStatus(active=False, remaining_seconds=0)

        expires_at, pattern, count = entry
        now = time.time()
        if now >= expires_at:
            del self._cooldowns[identity]
            return CooldownStatus(active=False, remaining_seconds=0)

        remaining = math.ceil(expires_at - now)
        return CooldownStatus(
            active=True,
            remaining_seconds=remaining,
            pattern=pattern,
            violation_count=count,
        )

    async def record_violation(
        self, identity: str, pattern: AbusePattern
    ) -> ViolationResult:
        now = time.time()
        config = self._configs.get(
            pattern, DEFAULT_PATTERN_CONFIGS[AbusePattern.RAPID_FIRE]
        )
        vkey = f"{identity}:{pattern}"
        window_start = now - config.window_seconds

        # Prune expired entries + append new violation
        timestamps = self._violations.get(vkey, [])
        timestamps = [t for t in timestamps if t > window_start]
        timestamps.append(now)
        self._violations[vkey] = timestamps

        count = len(timestamps)
        if count > config.threshold:
            cooldown = _calculate_cooldown(count, config, self._max_cooldown)
            self._cooldowns[identity] = (now + cooldown, pattern, count)
            return ViolationResult(
                cooldown_applied=True,
                cooldown_seconds=cooldown,
                violation_count=count,
                escalated=count > config.threshold + 1,
            )

        return ViolationResult(
            cooldown_applied=False,
            cooldown_seconds=0,
            violation_count=count,
            escalated=False,
        )

    async def clear_cooldown(self, identity: str) -> None:
        """Remove cooldown and violation history for *identity*."""
        self._cooldowns.pop(identity, None)
        to_remove = [k for k in self._violations if k.startswith(f"{identity}:")]
        for k in to_remove:
            del self._violations[k]


# ---------------------------------------------------------------------------
# Redis backend (production)
# ---------------------------------------------------------------------------


class RedisAbuseDetector:
    """Redis-backed abuse detection using sorted sets + TTL keys.

    Violation tracking: sorted set ``abuse:v:{identity}:{pattern}``
    with timestamps as scores.

    Cooldown state: key ``abuse:cd:{identity}`` with TTL = cooldown
    seconds, value = ``{pattern}|{violation_count}``.
    """

    def __init__(
        self,
        redis: object,  # redis.asyncio.Redis
        *,
        max_cooldown: int = 86400,
        pattern_configs: dict[AbusePattern, PatternConfig] | None = None,
    ) -> None:
        self._redis = redis
        self._max_cooldown = max_cooldown
        self._configs = pattern_configs or dict(DEFAULT_PATTERN_CONFIGS)

    async def check_cooldown(self, identity: str) -> CooldownStatus:
        cd_key = f"abuse:cd:{identity}"
        pipe = self._redis.pipeline(transaction=False)  # type: ignore[union-attr]
        pipe.ttl(cd_key)
        pipe.get(cd_key)
        results = await pipe.execute()  # type: ignore[union-attr]

        ttl: int = results[0]
        value: str | None = results[1]

        if ttl <= 0 or value is None:
            return CooldownStatus(active=False, remaining_seconds=0)

        parts = value.split("|")
        pattern = AbusePattern(parts[0])
        count = int(parts[1]) if len(parts) > 1 else 0

        return CooldownStatus(
            active=True,
            remaining_seconds=ttl,
            pattern=pattern,
            violation_count=count,
        )

    async def record_violation(
        self, identity: str, pattern: AbusePattern
    ) -> ViolationResult:
        config = self._configs.get(
            pattern, DEFAULT_PATTERN_CONFIGS[AbusePattern.RAPID_FIRE]
        )
        now = time.time()
        window_start = now - config.window_seconds
        vkey = f"abuse:v:{identity}:{pattern}"
        member = str(uuid.uuid4())

        # NOTE: transaction=False means pipelined (not truly atomic).
        # Acceptable for abuse detection where slight over/under-counting
        # is tolerable; a Lua script would be needed for strict atomicity.
        pipe = self._redis.pipeline(transaction=False)  # type: ignore[union-attr]
        pipe.zremrangebyscore(vkey, 0, window_start)
        pipe.zadd(vkey, {member: now})
        pipe.zcard(vkey)
        pipe.expire(vkey, config.window_seconds + 1)
        results = await pipe.execute()  # type: ignore[union-attr]
        count: int = results[2]

        if count > config.threshold:
            cooldown = _calculate_cooldown(count, config, self._max_cooldown)
            cd_key = f"abuse:cd:{identity}"
            await self._redis.setex(  # type: ignore[union-attr]
                cd_key, int(cooldown), f"{pattern}|{count}"
            )
            return ViolationResult(
                cooldown_applied=True,
                cooldown_seconds=cooldown,
                violation_count=count,
                escalated=count > config.threshold + 1,
            )

        return ViolationResult(
            cooldown_applied=False,
            cooldown_seconds=0,
            violation_count=count,
            escalated=False,
        )

    async def clear_cooldown(self, identity: str) -> None:
        """Remove cooldown key and violation sorted sets in Redis."""
        cd_key = f"abuse:cd:{identity}"
        await self._redis.delete(cd_key)  # type: ignore[union-attr]
        pattern = f"abuse:v:{identity}:*"
        cursor: int | bytes = 0
        while True:
            cursor, keys = await self._redis.scan(  # type: ignore[union-attr]
                cursor=cursor, match=pattern, count=100
            )
            if keys:
                await self._redis.delete(*keys)  # type: ignore[union-attr]
            if not cursor:
                break
