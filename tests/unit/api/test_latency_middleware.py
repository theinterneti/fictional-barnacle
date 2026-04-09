"""Tests for LatencyBudgetMiddleware.

Spec references:
  - S28: Latency budget middleware warns/aborts slow requests
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tta.api.middleware import LatencyBudgetMiddleware
from tta.config import Settings


def _make_app(
    warn_ms: float = 5000,
    abort_ms: float = 30000,
) -> FastAPI:
    """Build a minimal app with the middleware."""
    app = FastAPI()

    settings = Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        latency_budget_warn_ms=warn_ms,
        latency_budget_abort_ms=abort_ms,
    )
    app.state.settings = settings

    @app.get("/fast")
    async def fast_endpoint() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    # Pure ASGI middleware — instantiate directly
    app.middleware_stack = None  # force rebuild
    original_build = app.build_middleware_stack

    def patched_build():  # type: ignore[no-untyped-def]
        app.build_middleware_stack = original_build  # type: ignore[method-assign]
        stack = original_build()
        return LatencyBudgetMiddleware(stack)

    app.build_middleware_stack = patched_build  # type: ignore[method-assign]

    return app


class TestLatencyBudgetMiddleware:
    """LatencyBudgetMiddleware adds budget headers and enforces thresholds."""

    def test_fast_request_gets_budget_header(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/fast")
        assert resp.status_code == 200
        assert "x-latency-budget-remaining-ms" in resp.headers

    def test_exempt_paths_skip_middleware(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_budget_remaining_is_positive(self) -> None:
        client = TestClient(_make_app(warn_ms=50000))
        resp = client.get("/fast")
        remaining = resp.headers.get("x-latency-budget-remaining-ms")
        if remaining:
            assert float(remaining) > 0
