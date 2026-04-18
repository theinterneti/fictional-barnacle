"""Tests for health-check endpoints.

Spec references:
  - FR-23.23: /health returns status, checks, version
  - FR-23.24: healthy / degraded / unhealthy status logic
  - FR-23.25: /ready returns 200 only when all services connected
  - AC-23.9: Health reports degraded when Redis down
  - AC-23.12: Health reports unhealthy when Postgres down
"""

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


def _make_stub(result: str = "ok"):
    """Create an async stub that returns *result*."""

    async def _stub(_request: object) -> str:
        return result

    return _stub


def _make_failing_stub(exc: Exception | None = None):
    """Create an async stub that raises."""

    async def _stub(_request: object) -> str:
        raise exc or ConnectionError("service down")

    return _stub


def _build_client(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    *,
    postgres: str = "ok",
    neo4j: str = "ok",
    redis: str = "ok",
    moderation: str = "disabled",
) -> TestClient:
    """Build a TestClient with per-service stubs.

    Pass "ok" for healthy, "unavailable" for a failing check,
    or "not_configured" / "disabled" for non-error states.
    """
    for svc, status in [
        ("postgres", postgres),
        ("neo4j", neo4j),
        ("redis", redis),
        ("moderation", moderation),
    ]:
        if status == "unavailable":
            monkeypatch.setattr(f"tta.api.health._check_{svc}", _make_failing_stub())
        elif status == "not_configured":
            monkeypatch.setattr(
                f"tta.api.health._check_{svc}", _make_stub("not_configured")
            )
        else:
            monkeypatch.setattr(f"tta.api.health._check_{svc}", _make_stub(status))

    app = create_app(settings=settings)
    return TestClient(app)


@pytest.fixture()
def client(_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Default client with all checks healthy."""
    return _build_client(monkeypatch, _settings)


# ------------------------------------------------------------------
# Health — GET /api/v1/health  (FR-23.23, FR-23.24)
# ------------------------------------------------------------------


class TestHealthAllUp:
    """When all services are healthy."""

    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_status_healthy(self, client: TestClient) -> None:
        data = client.get("/api/v1/health").json()
        assert data["status"] == "healthy"

    def test_checks_all_ok(self, client: TestClient) -> None:
        data = client.get("/api/v1/health").json()
        assert data["checks"]["postgres"] == "ok"
        assert data["checks"]["redis"] == "ok"

    def test_includes_version(self, client: TestClient) -> None:
        data = client.get("/api/v1/health").json()
        assert "version" in data
        assert data["version"] == "0.1.0"


class TestHealthDegraded:
    """AC-23.9: Degraded when non-critical service down."""

    def test_redis_down_returns_degraded(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-23.9: Redis unreachable → degraded."""
        c = _build_client(monkeypatch, _settings, redis="unavailable")
        resp = c.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["redis"] == "unavailable"
        assert data["checks"]["postgres"] == "ok"

    def test_neo4j_down_returns_degraded(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        c = _build_client(monkeypatch, _settings, neo4j="unavailable")
        resp = c.get("/api/v1/health")
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["neo4j"] == "unavailable"

    def test_redis_and_neo4j_down_still_degraded(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Multiple non-critical failures → still degraded, not unhealthy."""
        c = _build_client(
            monkeypatch,
            _settings,
            redis="unavailable",
            neo4j="unavailable",
        )
        data = c.get("/api/v1/health").json()
        assert data["status"] == "degraded"


class TestHealthUnhealthy:
    """AC-23.12: Unhealthy when Postgres down."""

    def test_postgres_down_returns_unhealthy(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        c = _build_client(monkeypatch, _settings, postgres="unavailable")
        resp = c.get("/api/v1/health")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unhealthy"
        assert data["checks"]["postgres"] == "unavailable"

    def test_all_down_returns_unhealthy(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Postgres down overrides everything → unhealthy."""
        c = _build_client(
            monkeypatch,
            _settings,
            postgres="unavailable",
            redis="unavailable",
            neo4j="unavailable",
        )
        data = c.get("/api/v1/health").json()
        assert data["status"] == "unhealthy"


class TestHealthNotConfigured:
    """Neo4j not configured → 'not_configured' in checks, still healthy."""

    def test_neo4j_not_configured_is_healthy(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        c = _build_client(monkeypatch, _settings, neo4j="not_configured")
        data = c.get("/api/v1/health").json()
        assert data["status"] == "healthy"
        assert data["checks"]["neo4j"] == "not_configured"


# ------------------------------------------------------------------
# Readiness — GET /api/v1/health/ready  (FR-23.25)
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
        assert set(data["checks"]) == {
            "postgres",
            "neo4j",
            "redis",
            "moderation",
            "llm_breaker",
        }

    def test_returns_503_when_postgres_fails(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        c = _build_client(monkeypatch, _settings, postgres="unavailable")
        resp = c.get("/api/v1/health/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "not_ready"
        assert data["checks"]["postgres"] == "unavailable"

    def test_returns_503_when_redis_fails(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        c = _build_client(monkeypatch, _settings, redis="unavailable")
        resp = c.get("/api/v1/health/ready")
        assert resp.status_code == 503

    def test_not_configured_is_ready(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A service that's not_configured should not block readiness."""
        c = _build_client(monkeypatch, _settings, neo4j="not_configured")
        resp = c.get("/api/v1/health/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"


# ------------------------------------------------------------------
# Moderation health check (FR-24.15)
# ------------------------------------------------------------------


class TestHealthModeration:
    """Moderation is a non-critical check — disabled/unavailable/ok."""

    def test_moderation_disabled_is_healthy(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Disabled moderation does not degrade health."""
        c = _build_client(monkeypatch, _settings, moderation="disabled")
        resp = c.get("/api/v1/health")
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["checks"]["moderation"] == "disabled"

    def test_moderation_ok_is_healthy(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Enabled and working moderation reports ok."""
        c = _build_client(monkeypatch, _settings, moderation="ok")
        resp = c.get("/api/v1/health")
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["checks"]["moderation"] == "ok"

    def test_moderation_unavailable_degrades(
        self,
        _settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unavailable moderation → degraded status."""
        c = _build_client(monkeypatch, _settings, moderation="unavailable")
        resp = c.get("/api/v1/health")
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["moderation"] == "unavailable"
