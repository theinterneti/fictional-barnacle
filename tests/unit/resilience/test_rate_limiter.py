"""Tests for rate limiter (S25 §3) — AC-25.1 through AC-25.5."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

if TYPE_CHECKING:
    from fastapi import FastAPI

from tta.api.middleware import (
    RateLimitMiddleware,
    _build_429_response,
    _classify_endpoint,
    _extract_session_token,
    _rate_limit_headers,
    _rate_limit_key,
)
from tta.resilience.rate_limiter import (
    EndpointGroup,
    InMemoryRateLimiter,
    RateLimitResult,
    RedisRateLimiter,
)

# ---- InMemoryRateLimiter --------------------------------------------------


class TestInMemoryRateLimiter:
    """AC-25.1: Rate limit enforcement with sliding window."""

    @pytest.fixture
    def limiter(self) -> InMemoryRateLimiter:
        return InMemoryRateLimiter()

    @pytest.mark.asyncio
    async def test_allows_under_limit(self, limiter: InMemoryRateLimiter) -> None:
        result = await limiter.check("test:key", limit=5, window_seconds=60)
        assert result.allowed is True
        assert result.remaining == 4
        assert result.limit == 5
        assert result.retry_after == 0

    @pytest.mark.asyncio
    async def test_rejects_over_limit(self, limiter: InMemoryRateLimiter) -> None:
        for _ in range(5):
            r = await limiter.check("test:key", limit=5, window_seconds=60)
            assert r.allowed is True

        result = await limiter.check("test:key", limit=5, window_seconds=60)
        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after >= 1

    @pytest.mark.asyncio
    async def test_rejected_not_counted(self, limiter: InMemoryRateLimiter) -> None:
        """FR-25.09: Rejected requests must not count against the limit."""
        for _ in range(5):
            await limiter.check("test:key", limit=5, window_seconds=60)

        # Multiple rejections shouldn't extend the window
        for _ in range(10):
            r = await limiter.check("test:key", limit=5, window_seconds=60)
            assert r.allowed is False

        # Window still has exactly 5 entries
        assert len(limiter._windows["test:key"]) == 5

    @pytest.mark.asyncio
    async def test_window_expiry(self, limiter: InMemoryRateLimiter) -> None:
        """Entries expire after the window passes."""
        with patch("tta.resilience.rate_limiter.time") as mock_time:
            mock_time.time.return_value = 1000.0
            for _ in range(5):
                await limiter.check("test:key", limit=5, window_seconds=60)

            # After window expires, should allow again
            mock_time.time.return_value = 1061.0
            result = await limiter.check("test:key", limit=5, window_seconds=60)
            assert result.allowed is True
            assert result.remaining == 4

    @pytest.mark.asyncio
    async def test_separate_keys_independent(
        self, limiter: InMemoryRateLimiter
    ) -> None:
        for _ in range(5):
            await limiter.check("key:a", limit=5, window_seconds=60)

        # Different key should still be allowed
        result = await limiter.check("key:b", limit=5, window_seconds=60)
        assert result.allowed is True


# ---- RedisRateLimiter -----------------------------------------------------


class TestRedisRateLimiter:
    """Redis backend tests with mocked pipeline."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        redis = MagicMock()
        pipe1 = MagicMock()
        pipe1.execute = AsyncMock(return_value=[0, 3])  # pruned, count
        pipe2 = MagicMock()
        pipe2.execute = AsyncMock(return_value=[True, True])
        redis.pipeline.side_effect = [pipe1, pipe2]
        return redis

    @pytest.mark.asyncio
    async def test_allows_under_limit(self, mock_redis: MagicMock) -> None:
        limiter = RedisRateLimiter(mock_redis)
        result = await limiter.check("test:key", limit=10, window_seconds=60)
        assert result.allowed is True
        assert result.remaining == 6  # 10 - 3 - 1

    @pytest.mark.asyncio
    async def test_rejects_at_limit(self) -> None:
        redis = MagicMock()
        pipe1 = MagicMock()
        pipe1.execute = AsyncMock(return_value=[0, 10])  # count = limit
        redis.pipeline.return_value = pipe1
        limiter = RedisRateLimiter(redis)

        result = await limiter.check("test:key", limit=10, window_seconds=60)
        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after >= 1

    @pytest.mark.asyncio
    async def test_redis_pipeline_calls(self, mock_redis: MagicMock) -> None:
        """Verify the correct Redis commands are issued."""
        limiter = RedisRateLimiter(mock_redis)
        await limiter.check("test:key", limit=10, window_seconds=60)

        # First pipeline: prune + count
        assert mock_redis.pipeline.call_count == 2


# ---- Endpoint group classification ----------------------------------------


class TestEndpointClassification:
    """AC-25.3: Endpoint groups with correct rate limits."""

    def test_turns_endpoint(self) -> None:
        assert (
            _classify_endpoint("/api/v1/games/123/turns", "POST") == EndpointGroup.TURNS
        )

    def test_sse_endpoint(self) -> None:
        assert (
            _classify_endpoint("/api/v1/games/123/stream", "GET") == EndpointGroup.SSE
        )

    def test_auth_endpoint(self) -> None:
        assert _classify_endpoint("/api/v1/players", "POST") == EndpointGroup.AUTH

    def test_game_management(self) -> None:
        assert _classify_endpoint("/api/v1/games", "POST") == EndpointGroup.GAME_MGMT
        assert _classify_endpoint("/api/v1/games/123", "GET") == EndpointGroup.GAME_MGMT
        assert (
            _classify_endpoint("/api/v1/players/me", "GET") == EndpointGroup.GAME_MGMT
        )

    def test_health_exempt(self) -> None:
        assert _classify_endpoint("/api/v1/health", "GET") is None
        assert _classify_endpoint("/api/v1/health/ready", "GET") is None

    def test_metrics_exempt(self) -> None:
        assert _classify_endpoint("/metrics", "GET") is None

    def test_options_exempt(self) -> None:
        """CORS preflight OPTIONS requests are always exempt."""
        assert _classify_endpoint("/api/v1/games/123/turns", "OPTIONS") is None
        assert _classify_endpoint("/api/v1/players", "OPTIONS") is None


# ---- Token extraction & key building --------------------------------------


class TestTokenExtraction:
    def test_cookie_extraction(self) -> None:
        request = MagicMock()
        request.cookies = {"tta_session": "tok_abc123"}
        request.headers = {}
        token = _extract_session_token(request)
        assert token == "tok_abc123"

    def test_bearer_extraction(self) -> None:
        request = MagicMock()
        request.cookies = {}
        request.headers = {"authorization": "Bearer tok_xyz"}
        token = _extract_session_token(request)
        assert token == "tok_xyz"

    def test_no_token(self) -> None:
        request = MagicMock()
        request.cookies = {}
        request.headers = {"authorization": ""}
        token = _extract_session_token(request)
        assert token is None


class TestRateLimitKey:
    def test_player_key_uses_hash(self) -> None:
        request = MagicMock()
        key, is_player = _rate_limit_key("tok_abc", request, EndpointGroup.TURNS)
        assert key.startswith("rl:player:")
        assert is_player is True
        assert "tok_abc" not in key  # Token not stored raw

    def test_ip_key_when_no_token(self) -> None:
        request = MagicMock()
        request.client.host = "192.168.1.1"
        key, is_player = _rate_limit_key(None, request, EndpointGroup.TURNS)
        assert key == "rl:ip:192.168.1.1:turns"
        assert is_player is False


# ---- Rate limit headers ---------------------------------------------------


class TestRateLimitHeaders:
    """AC-25.2: Response headers present on all responses."""

    def test_headers_from_result(self) -> None:
        result = RateLimitResult(
            allowed=True,
            limit=10,
            remaining=7,
            reset_at=1700000060.5,
            retry_after=0,
        )
        headers = _rate_limit_headers(result)
        assert headers["X-RateLimit-Limit"] == "10"
        assert headers["X-RateLimit-Remaining"] == "7"
        assert headers["X-RateLimit-Reset"] == "1700000061"


# ---- 429 response envelope ------------------------------------------------


class TestBuild429Response:
    """AC-25.4: 429 uses S23 error envelope with retry_after_seconds."""

    def test_envelope_format(self) -> None:
        result = RateLimitResult(
            allowed=False,
            limit=10,
            remaining=0,
            reset_at=1700000060.0,
            retry_after=42,
        )
        resp = _build_429_response(result, "corr-123")
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "42"
        assert resp.headers["x-ratelimit-limit"] == "10"

        body = resp.body.decode()
        import json

        envelope = json.loads(body)
        err = envelope["error"]
        assert err["code"] == "RATE_LIMITED"
        assert err["correlation_id"] == "corr-123"
        assert err["retry_after_seconds"] == 42


# ---- Middleware integration (TestClient) -----------------------------------


class TestRateLimitMiddleware:
    """End-to-end middleware tests via TestClient (AC-25.1, AC-25.2)."""

    @pytest.fixture
    def app(self) -> FastAPI:
        from fastapi import FastAPI

        from tta.api.middleware import (
            RequestIDMiddleware,
        )
        from tta.resilience.rate_limiter import InMemoryRateLimiter

        app = FastAPI()

        # Minimal settings mock
        settings = MagicMock()
        settings.rate_limit_enabled = True
        settings.rate_limit_turns_per_minute = 3
        settings.rate_limit_game_mgmt_per_minute = 5
        settings.rate_limit_auth_per_minute = 3
        settings.rate_limit_sse_per_minute = 2
        app.state.settings = settings
        app.state.rate_limiter = InMemoryRateLimiter()

        @app.post("/api/v1/games/{game_id}/turns")
        async def create_turn(game_id: str) -> dict:
            return {"ok": True}

        @app.get("/api/v1/health")
        async def health() -> dict:
            return {"status": "healthy"}

        @app.post("/api/v1/players")
        async def register() -> dict:
            return {"player_id": "p1"}

        app.add_middleware(RateLimitMiddleware)
        app.add_middleware(RequestIDMiddleware)
        return app

    @pytest.fixture
    def client(self, app: FastAPI) -> TestClient:
        return TestClient(app)

    def test_headers_on_successful_response(self, client: TestClient) -> None:
        """AC-25.2: X-RateLimit-* headers on every response."""
        resp = client.post("/api/v1/games/g1/turns")
        assert resp.status_code == 200
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers
        assert "x-ratelimit-reset" in resp.headers

    def test_returns_429_when_exceeded(self, client: TestClient) -> None:
        """AC-25.1: Returns 429 after limit exceeded."""
        # Authenticated requests get per-player limit (3/min for turns)
        headers = {"Authorization": "Bearer tok_ratelimit"}
        for _ in range(3):
            resp = client.post("/api/v1/games/g1/turns", headers=headers)
            assert resp.status_code == 200

        resp = client.post("/api/v1/games/g1/turns", headers=headers)
        assert resp.status_code == 429
        body = resp.json()
        assert body["error"]["code"] == "RATE_LIMITED"
        assert "retry_after_seconds" in body["error"]
        assert "retry-after" in resp.headers

    def test_health_exempt_from_rate_limit(self, client: TestClient) -> None:
        """Health endpoints should never be rate-limited."""
        for _ in range(20):
            resp = client.get("/api/v1/health")
            assert resp.status_code == 200
            assert "x-ratelimit-limit" not in resp.headers

    def test_per_ip_gets_double_limit(self, client: TestClient) -> None:
        """Per-IP limit is 2× per-player limit (no auth token)."""
        # Turns limit is 3/min per-player = 6/min per-IP
        for i in range(6):
            resp = client.post("/api/v1/games/g1/turns")
            assert resp.status_code == 200, f"Request {i + 1} should pass"

        resp = client.post("/api/v1/games/g1/turns")
        assert resp.status_code == 429

    def test_authenticated_uses_player_limit(self, client: TestClient) -> None:
        """AC-25.3: Per-player limit when authenticated."""
        headers = {"Authorization": "Bearer tok_test123"}
        for _ in range(3):
            resp = client.post("/api/v1/games/g1/turns", headers=headers)
            assert resp.status_code == 200

        resp = client.post("/api/v1/games/g1/turns", headers=headers)
        assert resp.status_code == 429

    def test_disabled_rate_limiting(self, app: FastAPI) -> None:
        """Rate limiting can be disabled via config."""
        app.state.settings.rate_limit_enabled = False
        client = TestClient(app)
        for _ in range(20):
            resp = client.post("/api/v1/games/g1/turns")
            assert resp.status_code == 200
            assert "x-ratelimit-limit" not in resp.headers

    def test_options_exempt_from_rate_limit(self, client: TestClient) -> None:
        """CORS preflight OPTIONS requests should never be rate-limited."""
        for _ in range(20):
            resp = client.options("/api/v1/games/g1/turns")
            assert resp.status_code != 429


# ---- Fallback when Redis unavailable (AC-25.5) ----------------------------


class TestRateLimiterFallback:
    """AC-25.5: Falls back to in-memory when Redis is unavailable."""

    @pytest.fixture
    def app_no_limiter(self) -> FastAPI:
        """App without a rate_limiter on state (simulates Redis failure)."""
        from fastapi import FastAPI

        from tta.api.middleware import (
            RequestIDMiddleware,
        )

        app = FastAPI()
        settings = MagicMock()
        settings.rate_limit_enabled = True
        settings.rate_limit_turns_per_minute = 3
        settings.rate_limit_game_mgmt_per_minute = 5
        settings.rate_limit_auth_per_minute = 3
        settings.rate_limit_sse_per_minute = 2
        app.state.settings = settings
        # No app.state.rate_limiter — middleware falls back to InMemory

        @app.post("/api/v1/games/{game_id}/turns")
        async def create_turn(game_id: str) -> dict:
            return {"ok": True}

        app.add_middleware(RateLimitMiddleware)
        app.add_middleware(RequestIDMiddleware)
        return app

    def test_fallback_still_limits(self, app_no_limiter: FastAPI) -> None:
        client = TestClient(app_no_limiter)
        # Should still enforce limits using in-memory fallback
        for _ in range(6):  # 3 × 2 for IP
            resp = client.post("/api/v1/games/g1/turns")
            assert resp.status_code == 200

        resp = client.post("/api/v1/games/g1/turns")
        assert resp.status_code == 429


class TestRateLimiterFailOpen:
    """Runtime Redis failures should fail-open (allow the request)."""

    @pytest.fixture
    def app_broken_limiter(self) -> FastAPI:
        from fastapi import FastAPI

        from tta.api.middleware import (
            RequestIDMiddleware,
        )

        app = FastAPI()
        settings = MagicMock()
        settings.rate_limit_enabled = True
        settings.rate_limit_turns_per_minute = 3
        settings.rate_limit_game_mgmt_per_minute = 5
        settings.rate_limit_auth_per_minute = 3
        settings.rate_limit_sse_per_minute = 2
        app.state.settings = settings

        # Limiter that always raises (simulates Redis dying mid-flight)
        broken = AsyncMock()
        broken.check = AsyncMock(side_effect=ConnectionError("Redis gone"))
        app.state.rate_limiter = broken

        @app.post("/api/v1/games/{game_id}/turns")
        async def create_turn(game_id: str) -> dict:
            return {"ok": True}

        app.add_middleware(RateLimitMiddleware)
        app.add_middleware(RequestIDMiddleware)
        return app

    def test_fail_open_on_limiter_error(self, app_broken_limiter: FastAPI) -> None:
        """Requests should be allowed when the limiter backend fails."""
        client = TestClient(app_broken_limiter)
        resp = client.post("/api/v1/games/g1/turns")
        assert resp.status_code == 200
