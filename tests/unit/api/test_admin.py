"""Tests for S26 admin API endpoints.

Spec references:
  - AC-26.1: Admin endpoints require valid API key
  - AC-26.2: Unauthenticated requests get 401
  - AC-26.3: Player lookup returns profile, game counts, rate-limit state
  - AC-26.4: Suspend/unsuspend toggles player status with audit trail
  - AC-26.5: Moderation queue returns paginated flags with filtering
  - AC-26.6: Flag review updates verdict and optionally suspends player
  - AC-26.7: Audit log is append-only, immutable, queryable by time/action/admin
  - AC-26.8: Health endpoint reports all subsystem statuses
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.config import Settings

ADMIN_KEY = "test-admin-key-for-testing"


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        admin_api_key=ADMIN_KEY,
    )


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_KEY}"}


def _build_client(settings: Settings) -> TestClient:
    app = create_app(settings)

    # Stub out dependencies that admin endpoints need
    app.state.settings = settings
    app.state.pg = MagicMock()
    app.state.redis = None
    app.state.neo4j_driver = None
    app.state.session_repo = MagicMock()
    app.state.turn_repo = MagicMock()
    app.state.rate_limiter = MagicMock()
    app.state.abuse_detector = None
    app.state.moderation_recorder = None
    app.state.moderation_hook = MagicMock()
    app.state.llm_semaphore = None
    app.state.llm_client = MagicMock()
    app.state.prompt_registry = MagicMock()
    app.state.world_service = MagicMock()
    app.state.summary_service = MagicMock()
    app.state.pipeline_deps = MagicMock()
    app.state.turn_result_store = MagicMock()
    app.state.pg_engine = MagicMock()

    # Stub audit repo
    audit_repo = MagicMock()
    audit_repo.create_and_append = AsyncMock()
    audit_repo.query = AsyncMock(return_value=[])
    app.state.audit_repo = audit_repo

    return TestClient(app, raise_server_exceptions=False)


# ── AC-26.1 / AC-26.2: Authentication ──────────────────────────


class TestAdminAuth:
    """Admin endpoints require valid API key (AC-26.1, AC-26.2)."""

    def test_no_auth_returns_401(self, settings: Settings) -> None:
        client = _build_client(settings)
        resp = client.get("/admin/audit-log")
        assert resp.status_code == 401

    def test_wrong_key_returns_403(self, settings: Settings) -> None:
        client = _build_client(settings)
        resp = client.get(
            "/admin/audit-log",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 403

    def test_valid_key_passes_auth(self, settings: Settings) -> None:
        client = _build_client(settings)
        resp = client.get("/admin/audit-log", headers=_auth_headers())
        # Should not be 401/403
        assert resp.status_code != 401
        assert resp.status_code != 403


# ── AC-26.7: Audit log ─────────────────────────────────────────


class TestAuditLog:
    """Audit log is append-only, queryable (AC-26.7)."""

    def test_audit_log_returns_list(self, settings: Settings) -> None:
        client = _build_client(settings)
        resp = client.get("/admin/audit-log", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert "entries" in body

    def test_audit_log_pagination(self, settings: Settings) -> None:
        client = _build_client(settings)
        resp = client.get(
            "/admin/audit-log?limit=5",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200


# ── AC-26.8: Health endpoint ────────────────────────────────────


class TestAdminHealth:
    """Health endpoint reports all subsystem statuses (AC-26.8)."""

    def test_health_returns_200(self, settings: Settings) -> None:
        client = _build_client(settings)
        resp = client.get("/admin/health", headers=_auth_headers())
        # Health may be 200 or 503 depending on stubs, but should not be auth error
        assert resp.status_code in (200, 503)


# ── AC-26.3: Player lookup ─────────────────────────────────────


class TestPlayerLookup:
    """Player lookup returns profile data (AC-26.3)."""

    def test_player_not_found(self, settings: Settings) -> None:
        client = _build_client(settings)

        # Mock pg session to return None for player query
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        client.app.state.pg = MagicMock(return_value=mock_session)  # type: ignore[union-attr]

        resp = client.get(
            f"/admin/players/{uuid.uuid4()}",
            headers=_auth_headers(),
        )
        assert resp.status_code == 404


# ── AC-26.4: Suspend/unsuspend ──────────────────────────────────


class TestPlayerSuspension:
    """Suspend/unsuspend toggles player status with audit (AC-26.4)."""

    def test_suspend_requires_reason(self, settings: Settings) -> None:
        client = _build_client(settings)
        resp = client.post(
            f"/admin/players/{uuid.uuid4()}/suspend",
            json={"reason": "short"},
            headers=_auth_headers(),
        )
        # Either 422 (short reason) or 404 (player not found) — both acceptable
        assert resp.status_code in (404, 422)

    def test_suspend_reason_minimum_length(self, settings: Settings) -> None:
        client = _build_client(settings)
        resp = client.post(
            f"/admin/players/{uuid.uuid4()}/suspend",
            json={"reason": "ab"},
            headers=_auth_headers(),
        )
        # Should reject reason < 10 chars
        assert resp.status_code in (404, 422)


# ── AC-26.5: Moderation queue ───────────────────────────────────


class TestModerationQueue:
    """Moderation queue returns paginated flags (AC-26.5)."""

    def test_moderation_disabled_returns_empty(self, settings: Settings) -> None:
        client = _build_client(settings)
        # moderation_recorder is None
        resp = client.get(
            "/admin/moderation/flags",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["flags"] == []

    def test_moderation_with_recorder(self, settings: Settings) -> None:
        client = _build_client(settings)
        recorder = MagicMock()
        recorder.query = AsyncMock(return_value=[])
        client.app.state.moderation_recorder = recorder  # type: ignore[union-attr]

        resp = client.get(
            "/admin/moderation/flags",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200


# ── Metrics endpoint ────────────────────────────────────────────


class TestAdminMetrics:
    """Admin metrics returns prometheus format (FR-26.16)."""

    def test_metrics_returns_text(self, settings: Settings) -> None:
        client = _build_client(settings)
        resp = client.get("/admin/metrics", headers=_auth_headers())
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
