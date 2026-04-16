"""Tests for SecurityHeadersMiddleware."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.security_headers import SECURITY_HEADERS
from tta.config import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest.fixture
def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


@pytest.fixture
def app(_settings: Settings) -> FastAPI:
    return create_app(settings=_settings)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestSecurityHeaders:
    """Security headers are present on every response."""

    def test_health_endpoint_has_security_headers(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        # Headers present regardless of response status (may be 503 without Redis)
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["x-xss-protection"] == "0"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert (
            resp.headers["permissions-policy"]
            == "camera=(), microphone=(), geolocation=()"
        )

    def test_all_defined_headers_present(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        for name_bytes, value_bytes in SECURITY_HEADERS:
            name = name_bytes.decode()
            value = value_bytes.decode()
            assert resp.headers.get(name) == value, f"Missing or wrong: {name}"

    def test_404_still_has_security_headers(self, client: TestClient) -> None:
        resp = client.get("/nonexistent-route")
        assert resp.status_code == 404
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"


class TestCORSTightening:
    """CORS uses explicit method and header lists."""

    def test_cors_allows_expected_methods(self, client: TestClient) -> None:
        resp = client.options(
            "/api/v1/health",
            headers={
                "origin": "http://localhost:8080",
                "access-control-request-method": "POST",
            },
        )
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert "POST" in allowed

    def test_cors_rejects_unexpected_method(self, client: TestClient) -> None:
        resp = client.options(
            "/api/v1/health",
            headers={
                "origin": "http://localhost:8080",
                "access-control-request-method": "TRACE",
            },
        )
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert "TRACE" not in allowed

    def test_cors_allows_expected_headers(self, client: TestClient) -> None:
        resp = client.options(
            "/api/v1/health",
            headers={
                "origin": "http://localhost:8080",
                "access-control-request-method": "GET",
                "access-control-request-headers": "X-Admin-Token",
            },
        )
        allowed = resp.headers.get("access-control-allow-headers", "")
        assert "x-admin-token" in allowed.lower()
