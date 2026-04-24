"""Tests for S28 Performance & Scaling acceptance criteria.

Covers the remaining ACs not handled by existing unit tests:
  - AC-28.1: Turn submission latency budget
  - AC-28.3: Game listing latency budget (structure)
  - AC-28.5 ext: Semaphore metric integration
  - AC-28.6: Graceful degradation under load
  - AC-28.7: Graceful shutdown sequence

Existing coverage (separate files):
  - AC-28.4: tests/unit/observability/test_pool_metrics.py
  - AC-28.5: tests/unit/llm/test_semaphore.py
  - AC-28.8: Multi-instance (v2 scope, deferred)
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from tta.api.errors import AppError
from tta.api.middleware import LatencyBudgetMiddleware
from tta.config import Settings
from tta.llm.semaphore import LLMSemaphore

# ── Helpers ──────────────────────────────────────────────────────


def _settings(**overrides: object) -> Settings:
    defaults = {
        "database_url": "postgresql://test@localhost/test",
        "neo4j_password": "test",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _app_with_middleware(
    warn_ms: float = 5000,
    abort_ms: float = 30000,
) -> FastAPI:
    """Build a minimal app with latency budget middleware."""
    app = FastAPI()
    app.state.settings = _settings(
        latency_budget_warn_ms=warn_ms,
        latency_budget_abort_ms=abort_ms,
    )

    @app.get("/fast")
    async def fast() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/games")
    async def list_games() -> list[dict[str, str]]:
        return [{"id": f"game-{i}"} for i in range(10)]

    @app.post("/turns")
    async def submit_turn() -> dict[str, str]:
        return {"status": "accepted"}

    app.add_middleware(LatencyBudgetMiddleware)
    return app


# ── AC-28.1: Turn submission latency budget ──────────────────────


class TestTurnSubmissionBudget:
    """AC-28.1: Turn submission responds within latency budget."""

    pytestmark = [pytest.mark.spec("AC-28.01")]

    def test_turn_endpoint_returns_budget_header(self) -> None:
        """POST /turns includes latency budget remaining header."""
        client = TestClient(_app_with_middleware())
        resp = client.post("/turns")
        assert resp.status_code == 200
        assert "x-latency-budget-remaining-ms" in resp.headers

    def test_turn_budget_remaining_is_positive(self) -> None:
        """Fast turn submission has positive budget remaining."""
        client = TestClient(_app_with_middleware(warn_ms=50000))
        resp = client.post("/turns")
        remaining = resp.headers.get("x-latency-budget-remaining-ms")
        assert remaining is not None
        assert float(remaining) > 0

    def test_turn_response_is_fast(self) -> None:
        """Turn handler (without LLM) responds quickly."""
        client = TestClient(_app_with_middleware())
        start = time.monotonic()
        resp = client.post("/turns")
        elapsed_ms = (time.monotonic() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 500


# ── AC-28.3: Game listing latency budget ─────────────────────────


class TestGameListingBudget:
    """AC-28.3: Game listing responds within latency budget."""

    pytestmark = [pytest.mark.spec("AC-28.03")]

    def test_games_endpoint_returns_budget_header(self) -> None:
        """GET /games includes latency budget header."""
        client = TestClient(_app_with_middleware())
        resp = client.get("/games")
        assert resp.status_code == 200
        assert "x-latency-budget-remaining-ms" in resp.headers

    def test_games_response_is_fast(self) -> None:
        """Game listing (mock) responds quickly."""
        client = TestClient(_app_with_middleware())
        start = time.monotonic()
        resp = client.get("/games")
        elapsed_ms = (time.monotonic() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 500


# ── AC-28.5 extensions: Semaphore metric integration ────────────


class TestSemaphoreMetrics:
    """AC-28.5: LLM concurrency bounded with metrics integration."""

    pytestmark = [pytest.mark.spec("AC-28.05")]

    @pytest.mark.asyncio
    async def test_metrics_update_on_execute(self) -> None:
        """Active count tracks during semaphore execute."""
        sem = LLMSemaphore(max_concurrent=2, queue_size=5, timeout=5)
        observed_active: list[int] = []

        async def work() -> str:
            observed_active.append(sem.active)
            return "done"

        await sem.execute(work)
        assert observed_active == [1]
        assert sem.active == 0

    @pytest.mark.asyncio
    async def test_semaphore_properties_match_config(self) -> None:
        """Semaphore exposes configured limits as properties."""
        sem = LLMSemaphore(max_concurrent=10, queue_size=50, timeout=30)
        assert sem.max_concurrent == 10
        assert sem.queue_size == 50

    @pytest.mark.asyncio
    async def test_error_in_function_still_decrements(self) -> None:
        """Active count decrements even when the function raises."""
        sem = LLMSemaphore(max_concurrent=2, queue_size=5, timeout=5)

        async def failing() -> str:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await sem.execute(failing)

        assert sem.active == 0
        assert sem.waiting == 0


# ── AC-28.6: Graceful degradation ───────────────────────────────


class TestGracefulDegradation:
    """AC-28.6: System degrades gracefully under load."""

    pytestmark = [pytest.mark.spec("AC-28.06")]

    @pytest.mark.asyncio
    async def test_semaphore_queues_under_load(self) -> None:
        """When at capacity, requests queue rather than fail."""
        sem = LLMSemaphore(max_concurrent=1, queue_size=10, timeout=5)
        gate = asyncio.Event()
        completed: list[str] = []

        async def work(label: str) -> str:
            await gate.wait()
            completed.append(label)
            return label

        t1 = asyncio.create_task(sem.execute(work, "first"))
        await asyncio.sleep(0.02)
        assert sem.active == 1

        t2 = asyncio.create_task(sem.execute(work, "second"))
        await asyncio.sleep(0.02)
        assert sem.waiting >= 1

        gate.set()
        await asyncio.gather(t1, t2)
        assert set(completed) == {"first", "second"}

    @pytest.mark.asyncio
    async def test_queue_overflow_returns_service_unavailable(self) -> None:
        """When queue is full, returns structured error (not crash)."""
        sem = LLMSemaphore(max_concurrent=1, queue_size=1, timeout=5)
        gate = asyncio.Event()

        async def blocking() -> str:
            await gate.wait()
            return "ok"

        t1 = asyncio.create_task(sem.execute(blocking))
        await asyncio.sleep(0.02)
        t2 = asyncio.create_task(sem.execute(blocking))
        await asyncio.sleep(0.02)

        with pytest.raises(AppError) as exc_info:
            await sem.execute(blocking)
        assert exc_info.value.code == "LLM_QUEUE_FULL"

        gate.set()
        await asyncio.gather(t1, t2)

    def test_latency_budget_header_on_all_routes(self) -> None:
        """Middleware adds budget headers to all routes for monitoring."""
        client = TestClient(_app_with_middleware())
        for path in ["/fast", "/games", "/turns"]:
            method = "post" if path == "/turns" else "get"
            resp = getattr(client, method)(path)
            assert "x-latency-budget-remaining-ms" in resp.headers, (
                f"Missing budget header on {path}"
            )


# ── AC-28.7: Graceful shutdown ──────────────────────────────────


class TestGracefulShutdown:
    """AC-28.7: Application shuts down gracefully."""

    pytestmark = [pytest.mark.spec("AC-28.07")]

    @pytest.mark.asyncio
    async def test_pool_metrics_task_cancels_cleanly(self) -> None:
        """Pool metrics sampler cancels without error on shutdown."""
        from tta.observability.pool_metrics import start_pool_metrics_sampler

        app = MagicMock()
        app.state.pg_engine = None
        app.state.redis = None
        app.state.neo4j_driver = None

        task = start_pool_metrics_sampler(app, interval=0.05)
        await asyncio.sleep(0.1)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_semaphore_in_flight_completes(self) -> None:
        """In-flight semaphore work runs to completion."""
        sem = LLMSemaphore(max_concurrent=2, queue_size=5, timeout=5)
        completed = False

        async def work() -> str:
            nonlocal completed
            await asyncio.sleep(0.05)
            completed = True
            return "done"

        result = await sem.execute(work)
        assert result == "done"
        assert completed

    @pytest.mark.asyncio
    async def test_observability_shutdown_functions_are_safe(self) -> None:
        """Shutdown functions don't raise when called without init."""
        from tta.observability.langfuse import shutdown_langfuse
        from tta.observability.tracing import shutdown_tracing

        shutdown_langfuse()
        shutdown_tracing()


# ── DB pool configuration ────────────────────────────────────────


class TestPoolConfiguration:
    """Verify pool config settings match S28 requirements."""

    def test_default_pg_pool_settings(self) -> None:
        """Default PG pool settings are within S28 spec ranges."""
        s = _settings()
        assert s.pg_pool_min >= 1
        assert s.pg_pool_max >= s.pg_pool_min
        assert s.pg_pool_timeout > 0
        assert s.pg_pool_idle_timeout > 0

    def test_redis_pool_max_configured(self) -> None:
        s = _settings()
        assert s.redis_pool_max >= 1

    def test_neo4j_pool_max_configured(self) -> None:
        s = _settings()
        assert s.neo4j_pool_max >= 1

    def test_pool_settings_are_overridable(self) -> None:
        s = _settings(pg_pool_max=50, redis_pool_max=30)
        assert s.pg_pool_max == 50
        assert s.redis_pool_max == 30

    def test_latency_budget_defaults(self) -> None:
        s = _settings()
        assert s.latency_budget_warn_ms > 0
        assert s.latency_budget_abort_ms > s.latency_budget_warn_ms
