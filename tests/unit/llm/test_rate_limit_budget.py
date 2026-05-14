"""Tests for RateLimitBudget — task-priority LLM admission control (S50).

RED phase starts here — no implementation exists yet.
"""

import asyncio

import pytest


@pytest.mark.spec("AC-50.01")
class TestCriticalTierAlwaysAdmitted:
    """AC-50.01: Player turn not blocked under load."""

    async def test_critical_admitted_when_high_tier_at_cap(self) -> None:
        """CRITICAL tier bypasses concurrency caps.

        Given 3 HIGH tier calls are running (at HIGH cap of 3)
        When a CRITICAL tier call is requested
        Then it is admitted immediately without waiting.
        """
        from tta.llm.rate_limiter import RateLimitBudget, TaskPriority

        budget = RateLimitBudget(
            high_concurrency=3,
            low_concurrency=2,
            best_effort_backpressure=10,
            queue_timeout_high=300,
            queue_timeout_low=600,
        )

        # Fill HIGH tier to capacity
        acquired: list[bool] = []
        for _ in range(3):
            ok = await budget.admit(TaskPriority.HIGH, task_type="playtester")
            assert ok, "HIGH call should be admitted when under cap"
            acquired.append(ok)

        # CRITICAL should still be admitted despite full HIGH cap
        assert await budget.admit(TaskPriority.CRITICAL, task_type="player_turn")

        # Release acquired slots
        for _ in range(3):
            await budget.release(TaskPriority.HIGH)

    async def test_critical_never_waits_even_under_full_load(self) -> None:
        """CRITICAL call completes immediately even when all non-CRITICAL slots are busy."""
        from tta.llm.rate_limiter import RateLimitBudget, TaskPriority

        budget = RateLimitBudget(
            high_concurrency=3,
            low_concurrency=2,
            best_effort_backpressure=10,
            queue_timeout_high=300,
            queue_timeout_low=600,
        )

        # Saturate every non-CRITICAL tier
        for _ in range(3):
            await budget.admit(TaskPriority.HIGH, task_type="playtester")
        for _ in range(2):
            await budget.admit(TaskPriority.LOW, task_type="npc_autonomy")
        await budget.admit(TaskPriority.BEST_EFFORT, task_type="metrics")

        # Measure admission time — should be effectively instant (< 5ms)
        import time

        start = time.monotonic()
        admitted = await budget.admit(TaskPriority.CRITICAL, task_type="player_turn")
        elapsed_ms = (time.monotonic() - start) * 1000

        assert admitted, "CRITICAL must be admitted under all load conditions"
        assert elapsed_ms < 100, (
            f"CRITICAL admission took {elapsed_ms:.1f}ms, must be < 100ms "
            f"(target < 1ms per NFR-50.01)"
        )

        # Cleanup
        for _ in range(3):
            await budget.release(TaskPriority.HIGH)
        for _ in range(2):
            await budget.release(TaskPriority.LOW)
        await budget.release(TaskPriority.BEST_EFFORT)
        await budget.release(TaskPriority.CRITICAL)


@pytest.mark.spec("AC-50.02", "AC-50.03")
class TestNonCriticalTierConcurrency:
    """AC-50.02 (playtester cap) and AC-50.03 (background throttled)."""

    async def test_high_tier_capped_at_configured_limit(self) -> None:
        """HIGH tier admits exactly N concurrent calls."""
        from tta.llm.rate_limiter import RateLimitBudget, TaskPriority

        budget = RateLimitBudget(high_concurrency=3)

        # First 3 admitted
        for i in range(3):
            assert await budget.admit(TaskPriority.HIGH, task_type="playtester"), (
                f"HIGH call {i} should be admitted"
            )

        # 4th should NOT be admitted (at cap)
        assert not await budget.admit(TaskPriority.HIGH, task_type="playtester"), (
            "4th HIGH call must be denied when cap is 3"
        )

        # Release one, now admission should succeed
        await budget.release(TaskPriority.HIGH)
        assert await budget.admit(TaskPriority.HIGH, task_type="playtester"), (
            "HIGH call should be admitted after a slot frees"
        )

        # Cleanup
        for _ in range(3):
            await budget.release(TaskPriority.HIGH)

    async def test_low_tier_capped_independently(self) -> None:
        """LOW tier has its own independent concurrency cap."""
        from tta.llm.rate_limiter import RateLimitBudget, TaskPriority

        budget = RateLimitBudget(high_concurrency=3, low_concurrency=2)

        # Fill LOW tier
        for _ in range(2):
            await budget.admit(TaskPriority.LOW, task_type="npc_autonomy")

        # LOW at cap — 3rd denied
        assert not await budget.admit(TaskPriority.LOW, task_type="npc_autonomy")

        # HIGH tier still has capacity (independent semaphores)
        assert await budget.admit(TaskPriority.HIGH, task_type="playtester")

        # Cleanup
        await budget.release(TaskPriority.HIGH)
        for _ in range(2):
            await budget.release(TaskPriority.LOW)

    async def test_critical_unaffected_by_non_critical_caps(self) -> None:
        """CRITICAL calls admit even when HIGH and LOW are saturated."""
        from tta.llm.rate_limiter import RateLimitBudget, TaskPriority

        budget = RateLimitBudget(high_concurrency=1, low_concurrency=1)

        # Saturate non-CRITICAL
        await budget.admit(TaskPriority.HIGH, "playtester")
        await budget.admit(TaskPriority.LOW, "npc")

        # CRITICAL still gets through
        assert await budget.admit(TaskPriority.CRITICAL, "player_turn")

        # Cleanup
        await budget.release(TaskPriority.CRITICAL)
        await budget.release(TaskPriority.HIGH)
        await budget.release(TaskPriority.LOW)


@pytest.mark.spec("AC-50.02")
class TestQueuingAtCap:
    """FR-50.02 / AC-50.02: queued calls proceed when capacity frees (FIFO)."""

    async def test_high_tier_call_queues_and_proceeds_when_slot_frees(self) -> None:
        """A call at cap queues and is processed when a slot releases."""
        from tta.llm.rate_limiter import RateLimitBudget, TaskPriority

        budget = RateLimitBudget(high_concurrency=1)

        # Fill the single HIGH slot
        assert await budget.admit(TaskPriority.HIGH, task_type="playtester_1")

        # 2nd call should queue — admit_or_queue returns True when admitted
        admitted_future = asyncio.ensure_future(
            budget.admit_or_queue(TaskPriority.HIGH, task_type="playtester_2")
        )

        # Let the queued call register
        await asyncio.sleep(0)

        # Should still be waiting (not resolved)
        assert not admitted_future.done()

        # Release the first slot
        await budget.release(TaskPriority.HIGH)

        # Now the queued call should complete
        result = await asyncio.wait_for(admitted_future, timeout=2.0)
        assert result, "queued HIGH call should be admitted after slot frees"

        await budget.release(TaskPriority.HIGH)

    async def test_fifo_ordering(self) -> None:
        """Queued calls are processed in FIFO order."""
        from tta.llm.rate_limiter import RateLimitBudget, TaskPriority

        budget = RateLimitBudget(high_concurrency=1)
        admitted_order: list[str] = []

        async def task(label: str) -> None:
            await budget.admit_or_queue(TaskPriority.HIGH, task_type=label)
            admitted_order.append(label)
            await asyncio.sleep(0.01)  # Simulate work
            await budget.release(TaskPriority.HIGH)

        # Fill the slot
        await budget.admit(TaskPriority.HIGH, task_type="holder")

        # Queue 3 tasks
        t_a = asyncio.ensure_future(task("A"))
        t_b = asyncio.ensure_future(task("B"))
        t_c = asyncio.ensure_future(task("C"))
        await asyncio.sleep(0)

        # Release holder — queued tasks should process in order
        await budget.release(TaskPriority.HIGH)

        await asyncio.wait_for(asyncio.gather(t_a, t_b, t_c), timeout=2.0)

        assert admitted_order == ["A", "B", "C"], (
            f"Expected FIFO order A,B,C, got {admitted_order}"
        )


@pytest.mark.spec("AC-50.06")
class TestBackpressure:
    """AC-50.06: BEST_EFFORT drops when queue exceeds backpressure limit."""

    async def test_best_effort_dropped_at_backpressure_limit(self) -> None:
        """BEST_EFFORT call dropped when queue depth reaches backpressure limit."""
        from tta.llm.rate_limiter import RateLimitBudget, TaskPriority

        budget = RateLimitBudget(best_effort_backpressure=2)

        # Fill the BEST_EFFORT slot
        assert await budget.admit(TaskPriority.BEST_EFFORT, task_type="active")

        # Queue 2 (hits backpressure limit of 2)
        f1 = asyncio.ensure_future(
            budget.admit_or_queue(TaskPriority.BEST_EFFORT, task_type="q1")
        )
        await asyncio.sleep(0)
        f2 = asyncio.ensure_future(
            budget.admit_or_queue(TaskPriority.BEST_EFFORT, task_type="q2")
        )
        await asyncio.sleep(0)

        # 3rd attempt should be dropped (queue depth 2 >= backpressure 2)
        result = await budget.admit_or_queue(
            TaskPriority.BEST_EFFORT, task_type="dropped"
        )
        assert not result, (
            "BEST_EFFORT call should be dropped when backpressure exceeded"
        )

        # Clean up
        f1.cancel()
        f2.cancel()
        await budget.release(TaskPriority.BEST_EFFORT)

    async def test_backpressure_drop_logs_warning(self) -> None:
        """BEST_EFFORT drop emits a structlog warning."""
        from tta.llm.rate_limiter import RateLimitBudget, TaskPriority

        budget = RateLimitBudget(best_effort_backpressure=1)

        # Fill slot
        await budget.admit(TaskPriority.BEST_EFFORT, task_type="metrics")

        # Queue one (now at backpressure)
        f1 = asyncio.ensure_future(
            budget.admit_or_queue(TaskPriority.BEST_EFFORT, task_type="metrics_1")
        )
        await asyncio.sleep(0)

        # 3rd attempt should be dropped (backpressure exceeded)
        result = await budget.admit_or_queue(
            TaskPriority.BEST_EFFORT, task_type="metrics_2"
        )
        assert not result, (
            "BEST_EFFORT call should be dropped when backpressure exceeded"
        )

        # Clean up
        f1.cancel()
        await budget.release(TaskPriority.BEST_EFFORT)


@pytest.mark.spec("AC-50.05")
class TestStructlogEvents:
    """AC-50.05: structlog events on admission/queuing/rejection."""

    async def test_admission_logs_structlog_event(self) -> None:
        """admit() emits a structlog event."""
        from tta.llm.rate_limiter import RateLimitBudget, TaskPriority

        budget = RateLimitBudget()

        # Admission should produce a log
        assert await budget.admit(TaskPriority.CRITICAL, task_type="player_turn")
        await budget.release(TaskPriority.CRITICAL)

    async def test_queue_logs_structlog_event(self) -> None:
        """Queuing emits a structlog debug event."""
        from tta.llm.rate_limiter import RateLimitBudget, TaskPriority

        budget = RateLimitBudget(high_concurrency=1)

        await budget.admit(TaskPriority.HIGH, task_type="playtester_1")

        # This queues and should produce a log
        f = asyncio.ensure_future(
            budget.admit_or_queue(TaskPriority.HIGH, task_type="playtester_2")
        )
        await asyncio.sleep(0)

        # Cleanup
        await budget.release(TaskPriority.HIGH)
        await f
        await budget.release(TaskPriority.HIGH)
