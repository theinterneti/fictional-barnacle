"""Tests for LLM concurrency semaphore.

Spec references:
  - FR-28.11: Semaphore limits concurrent LLM requests (default 10)
  - FR-28.12: Bounded queue (default 50), 503 when exceeded
  - FR-28.13: Configurable timeout (default 30s), cancel on exceed
"""

import asyncio

import pytest

from tta.llm.semaphore import LLMSemaphore


@pytest.mark.asyncio
async def test_basic_execution() -> None:
    """Normal call passes through the semaphore."""
    sem = LLMSemaphore(max_concurrent=2, queue_size=5, timeout=5)

    async def work() -> str:
        return "done"

    result = await sem.execute(work)
    assert result == "done"
    assert sem.active == 0
    assert sem.waiting == 0


@pytest.mark.asyncio
async def test_concurrency_limited() -> None:
    """Only max_concurrent calls run simultaneously."""
    sem = LLMSemaphore(max_concurrent=2, queue_size=10, timeout=5)
    running = 0
    max_running = 0
    gate = asyncio.Event()

    async def work() -> str:
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        await gate.wait()
        running -= 1
        return "ok"

    tasks = [asyncio.create_task(sem.execute(work)) for _ in range(5)]
    await asyncio.sleep(0.05)
    assert max_running <= 2
    gate.set()
    results = await asyncio.gather(*tasks)
    assert all(r == "ok" for r in results)


@pytest.mark.asyncio
async def test_queue_overflow_returns_503() -> None:
    """When queue is full, new requests get 503."""
    sem = LLMSemaphore(max_concurrent=1, queue_size=1, timeout=5)
    gate = asyncio.Event()

    async def blocking() -> str:
        await gate.wait()
        return "ok"

    # Fill the semaphore (1 running)
    t1 = asyncio.create_task(sem.execute(blocking))
    await asyncio.sleep(0.02)

    # Fill the queue (1 waiting)
    t2 = asyncio.create_task(sem.execute(blocking))
    await asyncio.sleep(0.02)

    # This should overflow
    from tta.api.errors import AppError

    with pytest.raises(AppError, match="queue is full"):
        await sem.execute(blocking)

    gate.set()
    await t1
    await t2


@pytest.mark.asyncio
async def test_timeout_cancels_request() -> None:
    """Request exceeding timeout is cancelled."""
    sem = LLMSemaphore(max_concurrent=1, queue_size=5, timeout=1)

    async def slow() -> str:
        await asyncio.sleep(10)
        return "never"

    from tta.api.errors import AppError

    with pytest.raises(AppError, match="exceeded timeout"):
        await sem.execute(slow)


@pytest.mark.asyncio
async def test_active_and_waiting_counts() -> None:
    """active and waiting properties reflect real state."""
    sem = LLMSemaphore(max_concurrent=1, queue_size=5, timeout=5)
    gate = asyncio.Event()

    async def blocking() -> str:
        await gate.wait()
        return "ok"

    assert sem.active == 0
    assert sem.waiting == 0

    t1 = asyncio.create_task(sem.execute(blocking))
    await asyncio.sleep(0.02)
    assert sem.active == 1

    t2 = asyncio.create_task(sem.execute(blocking))
    await asyncio.sleep(0.02)
    assert sem.waiting >= 1

    gate.set()
    await asyncio.gather(t1, t2)
    assert sem.active == 0
    assert sem.waiting == 0
