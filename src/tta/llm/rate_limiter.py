"""Task-priority LLM admission control (S66).

RateLimitBudget enforces per-tier concurrency caps and queue-based
admission for non-CRITICAL LLM calls. CRITICAL tier always admitted.

In-process component — no Redis, no DB, no external services.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

from tta.llm.provider_utilization import ProviderUtilizationSnapshot

log = structlog.get_logger(__name__)


class TaskPriority(StrEnum):
    """LLM call priority tiers (S66 §4)."""

    CRITICAL = "critical"  # Player turns, Genesis v2 — never throttled
    HIGH = "high"  # Playtester sessions, quality evaluation
    LOW = "low"  # NPC autonomy, world-time, consequences
    BEST_EFFORT = "best_effort"  # Cost summaries, TTL monitors, purging


@dataclass
class _QueueEntry:
    """Pending admission request in a tier's queue."""

    event: asyncio.Event = field(default_factory=asyncio.Event)
    task_type: str = ""
    enqueued_at: float = field(default_factory=time.monotonic)


class RateLimitBudget:
    """In-process admission controller for LLM calls (S66).

    CRITICAL tier calls bypass all limits. HIGH, LOW, and BEST_EFFORT
    calls are admitted under their configured concurrency caps and
    queued (FIFO) when at capacity.
    """

    def __init__(
        self,
        *,
        high_concurrency: int = 3,
        low_concurrency: int = 2,
        best_effort_backpressure: int = 10,
        queue_timeout_high: float = 300.0,
        queue_timeout_low: float = 600.0,
        provider_utilization_snapshot: ProviderUtilizationSnapshot | None = None,
    ) -> None:
        self._high_concurrency = high_concurrency
        self._low_concurrency = low_concurrency
        self._best_effort_backpressure = best_effort_backpressure
        self._queue_timeout_high = queue_timeout_high
        self._queue_timeout_low = queue_timeout_low
        self._provider_utilization_snapshot = provider_utilization_snapshot

        self._high_sem = asyncio.Semaphore(high_concurrency)
        self._low_sem = asyncio.Semaphore(low_concurrency)
        self._best_effort_sem = asyncio.Semaphore(1)

        # FIFO queues per tier
        self._queues: dict[TaskPriority, deque[_QueueEntry]] = {
            TaskPriority.HIGH: deque(),
            TaskPriority.LOW: deque(),
            TaskPriority.BEST_EFFORT: deque(),
        }

        # Track active calls for observability
        self._active: dict[TaskPriority, int] = dict.fromkeys(TaskPriority, 0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def admit(
        self,
        tier: TaskPriority,
        task_type: str = "",
        *,
        provider: str | None = None,
    ) -> bool:
        """Request immediate admission. CRITICAL always true; others
        return False at cap (caller must queue or reject)."""
        if tier == TaskPriority.CRITICAL:
            self._active[TaskPriority.CRITICAL] += 1
            self._log_decision(
                "rate_limit_admitted",
                tier,
                task_type,
                decision="admitted",
                queue_depth=0,
                provider_utilization=None,
            )
            return True

        provider_utilization = self._provider_utilization_for(provider)
        sem = self._sem_for(tier)
        ok = sem.locked() is False
        if ok:
            await sem.acquire()
            self._active[tier] += 1
            self._log_decision(
                "rate_limit_admitted",
                tier,
                task_type,
                decision="admitted",
                queue_depth=len(self._queues[tier]),
                provider_utilization=provider_utilization,
            )
        return ok

    async def admit_or_queue(
        self,
        tier: TaskPriority,
        task_type: str = "",
        *,
        provider: str | None = None,
    ) -> bool:
        """Request admission, queuing if at cap (FR-66.02).

        CRITICAL: always admitted immediately.
        HIGH/LOW/BEST_EFFORT: admitted if under cap, otherwise FIFO queued.
        Returns True when admitted. Returns False when BEST_EFFORT
        backpressure exceeded.

        Raises asyncio.TimeoutError if the queue timeout expires.
        """
        provider_utilization = self._provider_utilization_for(provider)

        # Fast path: try immediate admission
        if await self.admit(tier, task_type, provider=provider):
            return True

        # BEST_EFFORT backpressure check (FR-66.06)
        if tier == TaskPriority.BEST_EFFORT:
            queue_depth = len(self._queues[TaskPriority.BEST_EFFORT])
            if queue_depth >= self._best_effort_backpressure:
                self._log_decision(
                    "rate_limit_dropped",
                    tier,
                    task_type,
                    decision="dropped",
                    queue_depth=queue_depth,
                    level="warning",
                    provider_utilization=provider_utilization,
                )
                return False

        # Slow path: queue
        entry = _QueueEntry(task_type=task_type)
        self._queues[tier].append(entry)

        self._log_decision(
            "rate_limit_queued",
            tier,
            task_type,
            decision="queued",
            queue_depth=len(self._queues[tier]),
            provider_utilization=provider_utilization,
        )

        timeout = self._timeout_for(tier)
        try:
            await asyncio.wait_for(entry.event.wait(), timeout=timeout)
        except TimeoutError:
            # Clean up stale queue entry
            self._remove_from_queue(tier, entry)
            self._log_decision(
                "rate_limit_timeout",
                tier,
                task_type,
                decision="rejected",
                queue_depth=len(self._queues[tier]),
                level="info",
                provider_utilization=provider_utilization,
            )
            raise

        # Event was set — we've been admitted (release() did it)
        self._active[tier] += 1
        return True

    async def release(
        self,
        tier: TaskPriority,
        *,
        provider: str | None = None,
    ) -> None:
        """Release a slot. If callers are queued, the next one gets admitted."""
        provider_utilization = self._provider_utilization_for(provider)
        if tier == TaskPriority.CRITICAL:
            self._active[TaskPriority.CRITICAL] -= 1
            self._log_decision(
                "rate_limit_completed",
                tier,
                "",
                decision="completed",
                queue_depth=0,
                provider_utilization=provider_utilization,
            )
            return

        self._active[tier] -= 1
        queue_depth = len(self._queues[tier])
        self._log_decision(
            "rate_limit_completed",
            tier,
            "",
            decision="completed",
            queue_depth=queue_depth,
            provider_utilization=provider_utilization,
        )

        # Try to admit the next queued caller
        if self._queues[tier]:
            next_entry = self._queues[tier].popleft()
            next_entry.event.set()
        else:
            self._sem_for(tier).release()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sem_for(self, tier: TaskPriority) -> asyncio.Semaphore:
        if tier == TaskPriority.HIGH:
            return self._high_sem
        if tier == TaskPriority.LOW:
            return self._low_sem
        return self._best_effort_sem

    def _timeout_for(self, tier: TaskPriority) -> float:
        if tier == TaskPriority.HIGH:
            return self._queue_timeout_high
        if tier == TaskPriority.LOW:
            return self._queue_timeout_low
        return 60.0  # BEST_EFFORT

    def _provider_utilization_for(self, provider: str | None) -> dict[str, Any] | None:
        """Return serialized provider-utilization state for logging.

        This is an observability seam only. It does not affect admission
        or routing behavior in this spike.
        """
        if provider is None or self._provider_utilization_snapshot is None:
            return None

        try:
            snapshot = self._provider_utilization_snapshot.snapshot()
            utilization = snapshot.get(provider)
            if utilization is None:
                return None

            return {
                "provider": utilization.provider,
                "state": str(utilization.state),
                "rpm_utilization": utilization.rpm_utilization,
                "retry_after_seconds": utilization.retry_after_seconds,
                "source": utilization.source,
            }
        except Exception:
            return None

    def _remove_from_queue(self, tier: TaskPriority, entry: _QueueEntry) -> None:
        """Remove a specific entry from the tier queue (O(n) — rare)."""
        try:
            self._queues[tier].remove(entry)
        except ValueError:
            pass  # Already removed (raced with release)

    def _log_decision(
        self,
        event: str,
        tier: TaskPriority,
        task_type: str,
        *,
        decision: str,
        queue_depth: int,
        level: str = "debug",
        provider_utilization: Any = None,
    ) -> None:
        """Emit the common S66 admission-control event shape.

        Args:
            provider_utilization: Optional ProviderUtilization record to include
                in the log. When None (default), logs provider_utilization=None
                for backward compatibility. When supplied, logs the full record
                for observability without changing routing behavior (that
                belongs to the AC-66.04 implementation slice).
        """
        logger = getattr(log, level)
        logger(
            event,
            tier=str(tier),
            task_type=task_type,
            decision=decision,
            queue_depth=queue_depth,
            provider_utilization=provider_utilization,
        )


class RateLimitedLLMClient:
    """Admission-controlled wrapper around LiteLLMClient (S66 §9.1).

    CRITICAL tier calls pass through without admission overhead.
    HIGH/LOW/BEST_EFFORT calls go through RateLimitBudget.admit_or_queue().

    Usage:
        inner = LiteLLMClient()
        budget = RateLimitBudget()
        client = RateLimitedLLMClient(inner=inner, budget=budget)
        response = await client.generate(
            role=ModelRole.GENERATION,
            messages=messages,
            tier=TaskPriority.HIGH,
            task_type="playtester",
        )
    """

    def __init__(
        self,
        inner: Any,
        budget: RateLimitBudget | None = None,
    ) -> None:
        self._inner = inner
        self._budget = budget or RateLimitBudget()

    async def generate(
        self,
        role,
        messages: list,
        params=None,
        *,
        tier: TaskPriority = TaskPriority.CRITICAL,
        task_type: str = "",
        generation_profile=None,
        traffic_class=None,
    ):
        """Generate with admission control per tier.

        CRITICAL tier bypasses the budget entirely.
        """
        await self._enforce(tier, task_type)
        try:
            if generation_profile is None and traffic_class is None:
                return await self._inner.generate(role, messages, params)
            return await self._inner.generate(
                role,
                messages,
                params,
                generation_profile=generation_profile,
                traffic_class=traffic_class,
            )
        finally:
            if tier != TaskPriority.CRITICAL:
                await self._budget.release(tier)

    async def stream(
        self,
        role,
        messages: list,
        params=None,
        *,
        tier: TaskPriority = TaskPriority.CRITICAL,
        task_type: str = "",
        generation_profile=None,
        traffic_class=None,
    ):
        """Stream with admission control per tier."""
        await self._enforce(tier, task_type)
        try:
            if generation_profile is None and traffic_class is None:
                return await self._inner.stream(role, messages, params)
            return await self._inner.stream(
                role,
                messages,
                params,
                generation_profile=generation_profile,
                traffic_class=traffic_class,
            )
        finally:
            if tier != TaskPriority.CRITICAL:
                await self._budget.release(tier)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _enforce(self, tier: TaskPriority, task_type: str) -> None:
        """Enforce admission control for non-CRITICAL tiers."""
        if tier == TaskPriority.CRITICAL:
            return  # Fast path: no overhead
        await self._budget.admit_or_queue(tier, task_type)
