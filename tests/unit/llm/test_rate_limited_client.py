"""Tests for RateLimitedLLMClient — admission-controlled wrapper (S50 §9.1)."""

import asyncio

import pytest

from tta.llm.client import LLMClient, Message, MessageRole
from tta.llm.roles import ModelRole
from tta.llm.testing import MockLLMClient

# RED: RateLimitedLLMClient doesn't exist yet


@pytest.mark.spec("AC-50.01")
class TestRateLimitedClientCritical:
    """CRITICAL tier calls pass through without admission check overhead."""

    async def test_critical_call_delegates_to_wrapped_client(self) -> None:
        """CRITICAL generate() delegates to the wrapped LLMClient."""
        from tta.llm.rate_limiter import RateLimitedLLMClient, TaskPriority

        mock = MockLLMClient(response="critical response")
        client: LLMClient = RateLimitedLLMClient(
            inner=mock,
        )

        result = await client.generate(
            role=ModelRole.GENERATION,
            messages=[Message(role=MessageRole.USER, content="test")],
            tier=TaskPriority.CRITICAL,
        )

        assert result.content == "critical response"
        assert len(mock.call_history) == 1
        assert mock.call_history[0]["method"] == "generate"

    async def test_multiple_critical_calls_not_blocked(self) -> None:
        """Multiple CRITICAL calls all pass through — no queuing."""
        from tta.llm.rate_limiter import RateLimitedLLMClient, TaskPriority

        mock = MockLLMClient(response="ok")
        client: LLMClient = RateLimitedLLMClient(inner=mock)

        # Fire many CRITICAL calls concurrently — none should block
        async def task() -> str:
            result = await client.generate(
                role=ModelRole.GENERATION,
                messages=[Message(role=MessageRole.USER, content="hi")],
                tier=TaskPriority.CRITICAL,
            )
            return result.content

        results = await asyncio.gather(*(task() for _ in range(10)))
        assert all(r == "ok" for r in results)
        assert len(mock.call_history) == 10


@pytest.mark.spec("AC-50.02")
class TestRateLimitedClientHigh:
    """HIGH tier calls respect concurrency cap."""

    async def test_high_tier_call_enforces_cap(self) -> None:
        """When HIGH cap is 1, concurrent calls queue."""
        from tta.llm.rate_limiter import (
            RateLimitBudget,
            RateLimitedLLMClient,
            TaskPriority,
        )

        budget = RateLimitBudget(high_concurrency=1)
        mock = MockLLMClient(response="high response")
        client: LLMClient = RateLimitedLLMClient(inner=mock, budget=budget)

        # Block the HIGH slot with a call that's deliberately slow
        hold_event = asyncio.Event()

        async def slow_call() -> str:
            # Save original generate, replace with blocking version
            orig_generate = mock.generate

            async def blocking_generate(role, messages, params=None):
                await hold_event.wait()
                return await orig_generate(role, messages, params)

            mock.generate = blocking_generate
            result = await client.generate(
                role=ModelRole.GENERATION,
                messages=[Message(role=MessageRole.USER, content="slow")],
                tier=TaskPriority.HIGH,
                task_type="playtester",
            )
            return result.content

        # First call gets admitted immediately, then blocks
        t1 = asyncio.ensure_future(slow_call())
        await asyncio.sleep(0.05)

        # Second call should queue (not rejected) — first still holds slot
        t2 = asyncio.ensure_future(
            client.generate(
                role=ModelRole.GENERATION,
                messages=[Message(role=MessageRole.USER, content="queued")],
                tier=TaskPriority.HIGH,
                task_type="playtester",
            )
        )
        await asyncio.sleep(0.05)
        assert not t2.done(), "second HIGH call should be queued"

        # Release the holder — both should complete
        hold_event.set()
        r1, r2 = await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2.0)
        assert r1 == "high response"
        assert r2.content == "high response"

    async def test_default_tier_is_critical(self) -> None:
        """Without explicit tier, default to CRITICAL (backward compat)."""
        from tta.llm.rate_limiter import RateLimitedLLMClient

        budget = __import__(
            "tta.llm.rate_limiter", fromlist=["RateLimitBudget"]
        ).RateLimitBudget(high_concurrency=1)
        mock = MockLLMClient(response="default")
        client: LLMClient = RateLimitedLLMClient(inner=mock, budget=budget)

        # No tier specified — should default to CRITICAL (always admitted)
        result = await client.generate(
            role=ModelRole.GENERATION,
            messages=[Message(role=MessageRole.USER, content="no_tier")],
        )
        assert result.content == "default"
