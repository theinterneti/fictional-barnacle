"""Tests for anti-abuse detection (S25 §3.5) — AC-25.6 through AC-25.8."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

if TYPE_CHECKING:
    from fastapi import FastAPI

from tta.resilience.anti_abuse import (
    AbusePattern,
    InMemoryAbuseDetector,
    PatternConfig,
    _calculate_cooldown,
)

# ---- _calculate_cooldown helper -------------------------------------------


class TestCalculateCooldown:
    """FR-25.11: Exponential escalation capped at max_cooldown."""

    def setup_method(self) -> None:
        self.config = PatternConfig(
            threshold=3,
            window_seconds=600,
            base_cooldown_seconds=120,
        )

    def test_first_cooldown_is_base(self) -> None:
        # count == threshold → excess = 0 → base × 2^0 = base
        assert _calculate_cooldown(3, self.config, 86400) == 120

    def test_second_cooldown_doubles(self) -> None:
        # count == threshold + 1 → base × 2^1 = 240
        assert _calculate_cooldown(4, self.config, 86400) == 240

    def test_third_cooldown_quadruples(self) -> None:
        # count == threshold + 2 → base × 2^2 = 480
        assert _calculate_cooldown(5, self.config, 86400) == 480

    def test_capped_at_max(self) -> None:
        # Very high violation count should not exceed max_cooldown
        result = _calculate_cooldown(100, self.config, 3600)
        assert result == 3600

    def test_below_threshold_gives_base(self) -> None:
        # count < threshold → excess negative → max(0, ...) = 0 → base
        assert _calculate_cooldown(1, self.config, 86400) == 120


# ---- InMemoryAbuseDetector ------------------------------------------------


class TestInMemoryAbuseDetector:
    """AC-25.6: Abuse pattern detection, AC-25.7/AC-25.8: Escalation."""

    @pytest.fixture
    def detector(self) -> InMemoryAbuseDetector:
        return InMemoryAbuseDetector(max_cooldown=86400)

    @pytest.mark.asyncio
    async def test_no_cooldown_initially(self, detector: InMemoryAbuseDetector) -> None:
        status = await detector.check_cooldown("ip:1.2.3.4")
        assert status.active is False
        assert status.remaining_seconds == 0

    @pytest.mark.asyncio
    async def test_violation_below_threshold_no_cooldown(
        self, detector: InMemoryAbuseDetector
    ) -> None:
        """AC-25.6: Violations below threshold don't trigger cooldown."""
        # Rapid-fire threshold is 3; 2 violations should not trigger
        for _ in range(2):
            result = await detector.record_violation(
                "ip:1.2.3.4", AbusePattern.RAPID_FIRE
            )
            assert result.cooldown_applied is False

        status = await detector.check_cooldown("ip:1.2.3.4")
        assert status.active is False

    @pytest.mark.asyncio
    async def test_rapid_fire_triggers_at_threshold(
        self, detector: InMemoryAbuseDetector
    ) -> None:
        """AC-25.8: 3 rate-limit violations in 10 min → cooldown."""
        for _ in range(2):
            await detector.record_violation("ip:1.2.3.4", AbusePattern.RAPID_FIRE)

        result = await detector.record_violation("ip:1.2.3.4", AbusePattern.RAPID_FIRE)
        assert result.cooldown_applied is True
        assert result.cooldown_seconds == 120  # base cooldown
        assert result.violation_count == 3
        assert result.escalated is False  # count == threshold, not beyond

    @pytest.mark.asyncio
    async def test_cooldown_blocks_identity(
        self, detector: InMemoryAbuseDetector
    ) -> None:
        """AC-25.6: Cooldown blocks the abusing identity."""
        for _ in range(3):
            await detector.record_violation("ip:1.2.3.4", AbusePattern.RAPID_FIRE)

        status = await detector.check_cooldown("ip:1.2.3.4")
        assert status.active is True
        assert status.remaining_seconds > 0
        assert status.pattern == AbusePattern.RAPID_FIRE

    @pytest.mark.asyncio
    async def test_escalation_doubles_cooldown(
        self, detector: InMemoryAbuseDetector
    ) -> None:
        """AC-25.7: Repeated violations escalate cooldown duration."""
        # 4th violation should get base × 2^1 = 240s
        for _ in range(4):
            result = await detector.record_violation(
                "ip:1.2.3.4", AbusePattern.RAPID_FIRE
            )

        assert result.cooldown_applied is True
        assert result.cooldown_seconds == 240
        assert result.escalated is True

    @pytest.mark.asyncio
    async def test_credential_stuffing_threshold(
        self, detector: InMemoryAbuseDetector
    ) -> None:
        """AC-25.6: Credential stuffing detected at 5 failures."""
        for _ in range(4):
            result = await detector.record_violation(
                "ip:10.0.0.1", AbusePattern.CREDENTIAL_STUFFING
            )
            assert result.cooldown_applied is False

        result = await detector.record_violation(
            "ip:10.0.0.1", AbusePattern.CREDENTIAL_STUFFING
        )
        assert result.cooldown_applied is True
        assert result.cooldown_seconds == 900  # 15 min base
        assert result.violation_count == 5

    @pytest.mark.asyncio
    async def test_different_identities_independent(
        self, detector: InMemoryAbuseDetector
    ) -> None:
        """Different IPs tracked independently."""
        for _ in range(3):
            await detector.record_violation("ip:1.1.1.1", AbusePattern.RAPID_FIRE)

        # 1.1.1.1 should be under cooldown
        s1 = await detector.check_cooldown("ip:1.1.1.1")
        assert s1.active is True

        # 2.2.2.2 should not be affected
        s2 = await detector.check_cooldown("ip:2.2.2.2")
        assert s2.active is False

    @pytest.mark.asyncio
    async def test_different_patterns_independent(
        self, detector: InMemoryAbuseDetector
    ) -> None:
        """Violations for different patterns tracked separately."""
        for _ in range(2):
            await detector.record_violation("ip:3.3.3.3", AbusePattern.RAPID_FIRE)

        # 2 rapid-fire < threshold (3), no cooldown yet
        status = await detector.check_cooldown("ip:3.3.3.3")
        assert status.active is False

        # Credential stuffing from same IP also independent
        result = await detector.record_violation(
            "ip:3.3.3.3", AbusePattern.CREDENTIAL_STUFFING
        )
        assert result.violation_count == 1
        assert result.cooldown_applied is False

    @pytest.mark.asyncio
    async def test_expired_cooldown_clears(
        self, detector: InMemoryAbuseDetector
    ) -> None:
        """Cooldown expires after its duration."""
        # Use tiny config to force fast expiry
        tiny = InMemoryAbuseDetector(
            max_cooldown=1,
            pattern_configs={
                AbusePattern.RAPID_FIRE: PatternConfig(
                    threshold=1,
                    window_seconds=600,
                    base_cooldown_seconds=1,
                ),
            },
        )
        await tiny.record_violation("ip:x", AbusePattern.RAPID_FIRE)
        status = await tiny.check_cooldown("ip:x")
        assert status.active is True

        # Manually expire the cooldown by backdating
        key = "ip:x"
        expires_at, pattern, count = tiny._cooldowns[key]
        tiny._cooldowns[key] = (time.time() - 1, pattern, count)

        status = await tiny.check_cooldown("ip:x")
        assert status.active is False

    @pytest.mark.asyncio
    async def test_max_cooldown_cap(self) -> None:
        """FR-25.11: Escalation doesn't exceed max_cooldown."""
        detector = InMemoryAbuseDetector(max_cooldown=300)
        # Record many violations to trigger high escalation
        for _ in range(10):
            result = await detector.record_violation(
                "ip:heavy", AbusePattern.RAPID_FIRE
            )

        assert result.cooldown_applied is True
        assert result.cooldown_seconds <= 300


# ---- Middleware integration (anti-abuse) -----------------------------------


class TestAntiAbuseMiddleware:
    """Integration tests for anti-abuse in RateLimitMiddleware."""

    @pytest.fixture
    def app(self) -> FastAPI:
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        from tta.api.middleware import (
            RateLimitMiddleware,
            RequestIDMiddleware,
        )
        from tta.resilience.rate_limiter import InMemoryRateLimiter

        app = FastAPI()

        settings = MagicMock()
        settings.rate_limit_enabled = True
        settings.rate_limit_turns_per_minute = 3
        settings.rate_limit_game_mgmt_per_minute = 5
        settings.rate_limit_auth_per_minute = 3
        settings.rate_limit_sse_per_minute = 2
        app.state.settings = settings
        app.state.rate_limiter = InMemoryRateLimiter()
        app.state.abuse_detector = InMemoryAbuseDetector(max_cooldown=86400)

        @app.post("/api/v1/games/{game_id}/turns")
        async def create_turn(game_id: str) -> dict:
            return {"ok": True}

        @app.get("/api/v1/games/{game_id}")
        async def get_game(game_id: str) -> dict:
            return {"game_id": game_id}

        @app.post("/api/v1/players")
        async def register() -> dict:
            return {"player_id": "p1"}

        @app.get("/api/v1/protected")
        async def protected() -> JSONResponse:
            # Simulate 401 from auth dependency
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        app.add_middleware(RateLimitMiddleware)
        app.add_middleware(RequestIDMiddleware)
        return app

    @pytest.fixture
    def client(self, app: FastAPI) -> TestClient:
        return TestClient(app)

    def test_cooldown_blocks_request(self, app: FastAPI, client: TestClient) -> None:
        """AC-25.8: IP with active cooldown gets 429 immediately."""
        detector: InMemoryAbuseDetector = app.state.abuse_detector

        # Manually set a cooldown
        detector._cooldowns["ip:testclient"] = (
            time.time() + 300,
            AbusePattern.RAPID_FIRE,
            5,
        )

        resp = client.post(
            "/api/v1/games/g1/turns",
            headers={"Authorization": "Bearer tok_abc"},
        )
        assert resp.status_code == 429
        body = resp.json()
        assert body["error"]["code"] == "RATE_LIMITED"
        assert "suspicious activity" in body["error"]["message"]
        assert body["error"]["details"]["reason"] == "rapid_fire"
        assert int(resp.headers["retry-after"]) > 0

    def test_rate_limit_records_rapid_fire(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """AC-25.8: 429 from rate limit → RAPID_FIRE violation recorded."""
        headers = {"Authorization": "Bearer tok_rf_test"}

        # Exhaust rate limit (3/min for turns with this auth)
        for _ in range(3):
            resp = client.post("/api/v1/games/g1/turns", headers=headers)
            assert resp.status_code == 200

        # 4th request → 429 → should record violation
        resp = client.post("/api/v1/games/g1/turns", headers=headers)
        assert resp.status_code == 429

        # Verify violation was recorded in detector
        detector: InMemoryAbuseDetector = app.state.abuse_detector
        vkey = f"ip:testclient:{AbusePattern.RAPID_FIRE}"
        assert vkey in detector._violations
        assert len(detector._violations[vkey]) == 1

    def test_three_rate_limits_trigger_cooldown(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """AC-25.8: 3 rate-limit hits → cooldown applied."""
        # We need 3 rate-limit 429s. Each token has 3/min limit for turns.
        # Use 3 different tokens so each gets exactly 1 violation recorded.
        # Actually, easier: use same token, exhaust, then keep hitting.
        headers = {"Authorization": "Bearer tok_cooldown_test"}

        # Exhaust: 3 allowed
        for _ in range(3):
            resp = client.post("/api/v1/games/g1/turns", headers=headers)
            assert resp.status_code == 200

        # 3 more rejections → 3 RAPID_FIRE violations → cooldown
        for _ in range(3):
            resp = client.post("/api/v1/games/g1/turns", headers=headers)
            assert resp.status_code == 429

        # Now the IP should be under cooldown
        # Next request (even to a different endpoint) should be blocked
        resp = client.get("/api/v1/games/g1")
        assert resp.status_code == 429
        body = resp.json()
        assert "suspicious activity" in body["error"]["message"]

    def test_401_records_credential_stuffing(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """AC-25.6: 401 responses trigger credential stuffing detection."""
        detector: InMemoryAbuseDetector = app.state.abuse_detector

        # Hit the endpoint that returns 401
        for _ in range(3):
            resp = client.get("/api/v1/protected")
            assert resp.status_code == 401

        # Check violations recorded
        vkey = f"ip:testclient:{AbusePattern.CREDENTIAL_STUFFING}"
        assert vkey in detector._violations
        assert len(detector._violations[vkey]) == 3

    def test_five_auth_failures_trigger_cooldown(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """AC-25.6: 5 auth failures from IP → cooldown."""
        # 5 × 401 should trigger credential stuffing cooldown
        for _ in range(5):
            resp = client.get("/api/v1/protected")
            assert resp.status_code == 401

        # Now the IP should be under cooldown; next request blocked
        resp = client.post("/api/v1/games/g1/turns")
        assert resp.status_code == 429
        body = resp.json()
        assert "suspicious activity" in body["error"]["message"]

    def test_abuse_detector_failure_is_failopen(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """Abuse detector errors don't break requests (fail-open)."""
        # Replace detector with one that always raises
        broken = AsyncMock()
        broken.check_cooldown = AsyncMock(side_effect=RuntimeError("redis down"))
        app.state.abuse_detector = broken

        resp = client.post(
            "/api/v1/games/g1/turns",
            headers={"Authorization": "Bearer tok_failopen"},
        )
        # Should still work (fail-open)
        assert resp.status_code == 200

    def test_disabled_abuse_detector(self, client: TestClient) -> None:
        """When abuse_detector is None, middleware still works."""
        client.app.state.abuse_detector = None  # type: ignore[union-attr]

        resp = client.post(
            "/api/v1/games/g1/turns",
            headers={"Authorization": "Bearer tok_no_abuse"},
        )
        assert resp.status_code == 200

    def test_cooldown_response_format(self, app: FastAPI, client: TestClient) -> None:
        """Cooldown 429 uses S23 error envelope structure."""
        detector: InMemoryAbuseDetector = app.state.abuse_detector
        detector._cooldowns["ip:testclient"] = (
            time.time() + 600,
            AbusePattern.CREDENTIAL_STUFFING,
            7,
        )

        resp = client.post("/api/v1/games/g1/turns")
        assert resp.status_code == 429

        body = resp.json()
        err = body["error"]
        assert err["code"] == "RATE_LIMITED"
        assert err["correlation_id"]  # not empty
        assert err["retry_after_seconds"] > 0
        assert err["details"]["reason"] == "credential_stuffing"
