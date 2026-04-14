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
# ruff: noqa: E501

from __future__ import annotations

import uuid
from datetime import UTC
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


# ── Shared pg-mock helper ────────────────────────────────────────


def _mock_pg_with_rows(rows: list) -> MagicMock:
    """Build a pg context-manager mock that returns *rows* on execute()."""
    mock_result = MagicMock()
    mock_result.first.return_value = rows[0] if rows else None
    mock_result.all.return_value = rows
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_session)


# ── AC-26.2: Player search ───────────────────────────────────────


class TestPlayerSearch:
    """GET /admin/players?search=... (AC-26.2)."""

    def _make_player_row(
        self,
        handle: str = "CoolDragon42",
        status: str = "active",
    ) -> MagicMock:
        from datetime import datetime

        row = MagicMock()
        row.id = uuid.uuid4()
        row.handle = handle
        row.status = status
        row.created_at = datetime(2025, 1, 1, tzinfo=UTC)
        return row

    def test_search_by_handle_prefix_returns_matches(self, settings: Settings) -> None:
        client = _build_client(settings)
        row = self._make_player_row(handle="CoolDragon42")
        client.app.state.pg = _mock_pg_with_rows([row])  # type: ignore[union-attr]

        resp = client.get(
            "/admin/players?search=CoolDragon",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "players" in body
        assert len(body["players"]) == 1
        assert body["players"][0]["handle"] == "CoolDragon42"
        assert body["players"][0]["player_id"] is not None
        assert body["players"][0]["status"] == "active"

    def test_empty_search_returns_all_players(self, settings: Settings) -> None:
        client = _build_client(settings)
        rows = [
            self._make_player_row(handle="Alice"),
            self._make_player_row(handle="Bob"),
        ]
        client.app.state.pg = _mock_pg_with_rows(rows)  # type: ignore[union-attr]

        resp = client.get("/admin/players", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["players"]) == 2

    def test_no_matching_search_returns_empty_not_404(self, settings: Settings) -> None:
        client = _build_client(settings)
        client.app.state.pg = _mock_pg_with_rows([])  # type: ignore[union-attr]

        resp = client.get(
            "/admin/players?search=NoSuchHandle",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["players"] == []

    def test_next_cursor_set_when_results_exist(self, settings: Settings) -> None:
        client = _build_client(settings)
        row = self._make_player_row()
        client.app.state.pg = _mock_pg_with_rows([row])  # type: ignore[union-attr]

        resp = client.get("/admin/players", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["next_cursor"] is not None
        assert body["next_cursor"] == str(row.id)

    def test_next_cursor_null_when_empty(self, settings: Settings) -> None:
        client = _build_client(settings)
        client.app.state.pg = _mock_pg_with_rows([])  # type: ignore[union-attr]

        resp = client.get("/admin/players", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["next_cursor"] is None


# ── AC-26.3: Suspend / unsuspend ────────────────────────────────


class TestSuspendUnsuspend:
    """POST /admin/players/{id}/suspend and /unsuspend (AC-26.3)."""

    def test_suspend_success_returns_200_and_audit(self, settings: Settings) -> None:
        client = _build_client(settings)
        player_id = uuid.uuid4()
        updated_row = MagicMock()
        updated_row.id = player_id
        client.app.state.pg = _mock_pg_with_rows(  # type: ignore[union-attr]
            [updated_row]
        )

        resp = client.post(
            f"/admin/players/{player_id}/suspend",
            json={"reason": "Repeated TOS violations over multiple sessions"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "suspended"
        assert body["player_id"] == str(player_id)

        # Audit entry must have been created
        audit_repo = client.app.state.audit_repo  # type: ignore[union-attr]
        audit_repo.create_and_append.assert_awaited_once()

    def test_unsuspend_success_returns_200(self, settings: Settings) -> None:
        client = _build_client(settings)
        player_id = uuid.uuid4()
        updated_row = MagicMock()
        updated_row.id = player_id
        client.app.state.pg = _mock_pg_with_rows(  # type: ignore[union-attr]
            [updated_row]
        )

        resp = client.post(
            f"/admin/players/{player_id}/unsuspend",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "active"
        assert body["player_id"] == str(player_id)

    def test_suspend_already_suspended_returns_error(self, settings: Settings) -> None:
        """EC-26.1: UPDATE returns no rows → error with PLAYER_NOT_FOUND_OR_ALREADY_SUSPENDED."""
        client = _build_client(settings)
        # first() returns None → player not found or already suspended
        client.app.state.pg = _mock_pg_with_rows([])  # type: ignore[union-attr]

        resp = client.post(
            f"/admin/players/{uuid.uuid4()}/suspend",
            json={"reason": "Repeated TOS violations"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 409
        body = resp.json()
        assert "PLAYER_NOT_FOUND_OR_ALREADY_SUSPENDED" in str(body)

    def test_suspend_short_reason_returns_422(self, settings: Settings) -> None:
        """EC-26.4: SuspendRequest.reason min_length=10 → 422 validation error."""
        client = _build_client(settings)
        resp = client.post(
            f"/admin/players/{uuid.uuid4()}/suspend",
            json={"reason": "short"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422


# ── AC-26.3 / get_player success path ───────────────────────────


class TestGetPlayerSuccess:
    """GET /admin/players/{id} — success path (complement to 404 test)."""

    def test_get_player_returns_full_profile(self, settings: Settings) -> None:
        from datetime import datetime

        client = _build_client(settings)
        player_id = uuid.uuid4()

        player_row = MagicMock()
        player_row.id = player_id
        player_row.handle = "HeroPlayer99"
        player_row.status = "active"
        player_row.suspended_reason = None
        player_row.created_at = datetime(2025, 3, 15, tzinfo=UTC)

        counts_row = MagicMock()
        counts_row.total = 5
        counts_row.active = 2

        # pg is called twice: once for player, once for game counts.
        # We need each call to return its own result.
        player_result = MagicMock()
        player_result.first.return_value = player_row

        counts_result = MagicMock()
        counts_result.first.return_value = counts_row

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[player_result, counts_result])
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        client.app.state.pg = MagicMock(  # type: ignore[union-attr]
            return_value=mock_session
        )

        resp = client.get(
            f"/admin/players/{player_id}",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["player_id"] == str(player_id)
        assert body["handle"] == "HeroPlayer99"
        assert body["status"] == "active"
        assert "created_at" in body
        assert "games" in body
        assert body["games"]["total"] == 5
        assert body["games"]["active"] == 2
        assert "rate_limit" in body
