"""Tests for health-check endpoints."""

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.config import Settings


@pytest.fixture()
def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


@pytest.fixture()
def client(_settings: Settings) -> TestClient:
    app = create_app(settings=_settings)
    return TestClient(app)


# ------------------------------------------------------------------
# Liveness — GET /api/v1/health
# ------------------------------------------------------------------


class TestLiveness:
    """GET /api/v1/health returns status and version."""

    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_body_contains_status_ok(self, client: TestClient) -> None:
        data = client.get("/api/v1/health").json()
        assert data["status"] == "ok"

    def test_body_contains_version(self, client: TestClient) -> None:
        data = client.get("/api/v1/health").json()
        assert data["version"] == "0.1.0"


# ------------------------------------------------------------------
# Readiness — GET /api/v1/health/ready
# ------------------------------------------------------------------


class TestReadiness:
    """GET /api/v1/health/ready checks downstream services."""

    def test_returns_200_when_all_ok(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health/ready")
        assert resp.status_code == 200

    def test_body_status_ready(self, client: TestClient) -> None:
        data = client.get("/api/v1/health/ready").json()
        assert data["status"] == "ready"

    def test_body_includes_all_checks(self, client: TestClient) -> None:
        data = client.get("/api/v1/health/ready").json()
        assert set(data["checks"]) == {"postgres", "neo4j", "redis"}
        for value in data["checks"].values():
            assert value == "ok"

    def test_returns_503_when_check_fails(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _fail() -> str:
            raise ConnectionError("database is down")

        monkeypatch.setattr("tta.api.health._check_postgres", _fail)

        resp = client.get("/api/v1/health/ready")
        assert resp.status_code == 503

        data = resp.json()
        assert data["status"] == "not_ready"
        assert data["checks"]["postgres"] == "unavailable"
        # Other checks should still pass
        assert data["checks"]["neo4j"] == "ok"
        assert data["checks"]["redis"] == "ok"
