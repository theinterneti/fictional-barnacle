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
  - AC-26.4 (game): GET /admin/games/{game_id} returns full game state
  - AC-26.5 (game): POST /admin/games/{game_id}/terminate force-ends a game
"""
# ruff: noqa: E501

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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


# ── AC-26.4 (game): Game inspection ─────────────────────────────


class TestGameInspection:
    """GET /admin/games/{game_id} returns full game state (AC-26.4)."""

    def _make_game_row(self, game_id: uuid.UUID, player_id: uuid.UUID) -> MagicMock:
        row = MagicMock()
        row.id = game_id
        row.player_id = player_id
        row.status = "active"
        row.world_seed = "dark-castle"
        row.title = "The Dark Castle"
        row.summary = "A tale of adventure."
        row.turn_count = 5
        row.needs_recovery = False
        row.last_played_at = None
        row.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        row.updated_at = None
        return row

    def _build_game_client(self, settings: Settings, game_row: MagicMock) -> TestClient:
        client = _build_client(settings)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = game_row
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        client.app.state.pg = MagicMock(return_value=mock_session)  # type: ignore[union-attr]
        return client

    def test_get_game_returns_full_state(self, settings: Settings) -> None:
        game_id = uuid.uuid4()
        player_id = uuid.uuid4()
        row = self._make_game_row(game_id, player_id)
        client = self._build_game_client(settings, row)

        resp = client.get(f"/admin/games/{game_id}", headers=_auth_headers())

        assert resp.status_code == 200
        body = resp.json()
        assert body["game_id"] == str(game_id)
        assert body["player_id"] == str(player_id)
        assert body["status"] == "active"
        assert "moderation_flags" in body

    def test_get_game_includes_moderation_flags(self, settings: Settings) -> None:
        game_id = uuid.uuid4()
        player_id = uuid.uuid4()
        row = self._make_game_row(game_id, player_id)
        client = self._build_game_client(settings, row)

        recorder = MagicMock()
        recorder.query = AsyncMock(
            return_value=[{"moderation_id": "abc", "category": "violence"}]
        )
        client.app.state.moderation_recorder = recorder  # type: ignore[union-attr]

        resp = client.get(f"/admin/games/{game_id}", headers=_auth_headers())

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["moderation_flags"]) > 0

    def test_get_game_not_found_returns_404(self, settings: Settings) -> None:
        client = _build_client(settings)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        client.app.state.pg = MagicMock(return_value=mock_session)  # type: ignore[union-attr]

        resp = client.get(f"/admin/games/{uuid.uuid4()}", headers=_auth_headers())

        assert resp.status_code == 404

    def test_get_game_turns_returns_paginated_list(self, settings: Settings) -> None:
        client = _build_client(settings)

        def _make_turn_row(n: int) -> MagicMock:
            r = MagicMock()
            r.id = uuid.uuid4()
            r.session_id = uuid.uuid4()
            r.turn_number = n
            r.player_input = f"input {n}"
            r.status = "completed"
            r.narrative_output = f"narrative {n}"
            r.model_used = "gpt-4"
            r.latency_ms = 250
            r.token_count = 100
            r.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            r.completed_at = None
            return r

        turn_rows = [_make_turn_row(1), _make_turn_row(2)]
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = turn_rows
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        client.app.state.pg = MagicMock(return_value=mock_session)  # type: ignore[union-attr]

        resp = client.get(
            f"/admin/games/{uuid.uuid4()}/turns",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["turns"]) == 2
        for turn in body["turns"]:
            assert "turn_id" in turn
            assert "turn_number" in turn
            assert "player_input" in turn


# ── AC-26.5 (game): Game termination ────────────────────────────


class TestGameTermination:
    """POST /admin/games/{game_id}/terminate force-ends a game (AC-26.5)."""

    def test_terminate_game_success(self, settings: Settings) -> None:
        client = _build_client(settings)
        game_id = uuid.uuid4()

        # Step 1: SELECT returns a row with status="active"
        select_result = MagicMock()
        active_row = MagicMock()
        active_row.status = "active"
        select_result.first.return_value = active_row

        # Step 2: UPDATE returns nothing
        update_result = MagicMock()
        update_result.first.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[select_result, update_result])
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        client.app.state.pg = MagicMock(return_value=mock_session)  # type: ignore[union-attr]

        resp = client.post(
            f"/admin/games/{game_id}/terminate",
            json={"reason": "Admin force-terminated for policy violation"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ended"
        audit_repo = client.app.state.audit_repo  # type: ignore[union-attr]
        audit_repo.create_and_append.assert_awaited_once()

    def test_terminate_game_not_active_returns_error(self, settings: Settings) -> None:
        """EC-26.2: Game exists but is non-active → 409 GAME_ALREADY_TERMINATED."""
        client = _build_client(settings)

        # SELECT returns a row with status="ended" (game found, but non-terminable)
        select_result = MagicMock()
        ended_row = MagicMock()
        ended_row.status = "ended"
        select_result.first.return_value = ended_row

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=select_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        client.app.state.pg = MagicMock(return_value=mock_session)  # type: ignore[union-attr]

        resp = client.post(
            f"/admin/games/{uuid.uuid4()}/terminate",
            json={"reason": "Trying to end a completed game"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 409
        body = resp.json()
        assert "GAME_ALREADY_TERMINATED" in str(body)

    def test_terminate_requires_reason_min_length(self, settings: Settings) -> None:
        """EC-26.4: TerminateRequest.reason min_length=10 → 422."""
        client = _build_client(settings)

        resp = client.post(
            f"/admin/games/{uuid.uuid4()}/terminate",
            json={"reason": "short"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 422

    def test_terminate_game_not_found_returns_404(self, settings: Settings) -> None:
        """EC-26.2: Game does not exist → 404 GAME_NOT_FOUND."""
        client = _build_client(settings)

        # SELECT returns None (game not found)
        select_result = MagicMock()
        select_result.first.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=select_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        client.app.state.pg = MagicMock(return_value=mock_session)  # type: ignore[union-attr]

        resp = client.post(
            f"/admin/games/{uuid.uuid4()}/terminate",
            json={"reason": "Attempting to terminate a non-existent game"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 404
        body = resp.json()
        assert "GAME_NOT_FOUND" in str(body)


# ── AC-26.6: Moderation flag review ─────────────────────────────


class TestModerationFlagReview:
    """POST /admin/moderation/flags/{flag_id}/review (AC-26.6)."""

    def _build_recorder_client(
        self,
        settings: Settings,
        *,
        update_verdict_return: object = True,
    ) -> TestClient:
        client = _build_client(settings)
        recorder = MagicMock()
        recorder.update_verdict = AsyncMock(return_value=update_verdict_return)
        recorder.query = AsyncMock(return_value=[])
        client.app.state.moderation_recorder = recorder  # type: ignore[union-attr]
        return client

    def test_review_dismiss_returns_200_and_audit(self, settings: Settings) -> None:
        client = self._build_recorder_client(settings, update_verdict_return=True)
        flag_id = "flag-abc-123"

        resp = client.post(
            f"/admin/moderation/flags/{flag_id}/review",
            json={"action": "dismiss", "notes": "False positive notes here"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["flag_id"] == flag_id
        assert body["action"] == "dismiss"
        assert body["new_verdict"] == "pass"

        # AC-26.6: flag verdict updated to "pass" (the reviewed/dismissed state)
        recorder = client.app.state.moderation_recorder  # type: ignore[union-attr]
        recorder.update_verdict.assert_awaited_once_with(flag_id, "pass")

        # AC-26.6: audit entry created with action "moderation_review_dismiss"
        audit_repo = client.app.state.audit_repo  # type: ignore[union-attr]
        audit_repo.create_and_append.assert_awaited_once()
        call_kwargs = audit_repo.create_and_append.call_args
        assert call_kwargs.kwargs["action"] == "moderation_review_dismiss"

    def test_review_warn_maps_to_flag_verdict(self, settings: Settings) -> None:
        client = self._build_recorder_client(settings, update_verdict_return=True)
        flag_id = "flag-def-456"

        resp = client.post(
            f"/admin/moderation/flags/{flag_id}/review",
            json={
                "action": "warn",
                "notes": "Player was warned for inappropriate content",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["new_verdict"] == "flag"
        assert body["action"] == "warn"

    def test_review_flag_not_found_returns_404(self, settings: Settings) -> None:
        client = self._build_recorder_client(settings, update_verdict_return=False)

        resp = client.post(
            "/admin/moderation/flags/nonexistent-flag/review",
            json={"action": "dismiss", "notes": "This flag does not exist here"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 404
        body = resp.json()
        assert "FLAG_NOT_FOUND" in str(body)

    def test_review_no_recorder_returns_503(self, settings: Settings) -> None:
        client = _build_client(settings)
        # moderation_recorder is None by default in _build_client

        resp = client.post(
            "/admin/moderation/flags/some-flag/review",
            json={"action": "dismiss", "notes": "Notes that are long enough to pass"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 503
        body = resp.json()
        assert "MODERATION_NOT_CONFIGURED" in str(body)

    def test_review_invalid_action_returns_422(self, settings: Settings) -> None:
        client = self._build_recorder_client(settings)

        resp = client.post(
            "/admin/moderation/flags/some-flag/review",
            json={"action": "approve", "notes": "This action is not allowed here"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 422

    def test_review_short_notes_returns_422(self, settings: Settings) -> None:
        client = self._build_recorder_client(settings)

        resp = client.post(
            "/admin/moderation/flags/some-flag/review",
            json={"action": "dismiss", "notes": "short"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 422


# ── AC-26.7: Rate-limit inspection (read paths) ──────────────────


class TestRateLimitInspection:
    """GET /admin/rate-limits/player/{id} and /ip/{ip} (AC-26.7 read paths)."""

    def test_get_player_rate_limits_no_detector(self, settings: Settings) -> None:
        client = _build_client(settings)
        # abuse_detector is None by default

        resp = client.get(
            f"/admin/rate-limits/player/{uuid.uuid4()}",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["cooldown"] is None

    def test_get_player_rate_limits_with_detector(self, settings: Settings) -> None:
        client = _build_client(settings)

        # Active cooldown returned for player-id lookups (route handler).
        cd_active = MagicMock()
        cd_active.active = True
        cd_active.remaining_seconds = 45
        cd_active.pattern = "rapid_turn"
        cd_active.violation_count = 3

        # Inactive cooldown returned for IP-based lookups (middleware).
        cd_inactive = MagicMock()
        cd_inactive.active = False
        cd_inactive.remaining_seconds = 0
        cd_inactive.pattern = None
        cd_inactive.violation_count = 0

        async def _check_cooldown(key: str) -> MagicMock:
            # Middleware calls with "ip:<addr>"; route calls with player UUID string.
            return cd_inactive if key.startswith("ip:") else cd_active

        detector = MagicMock()
        detector.check_cooldown = _check_cooldown
        client.app.state.abuse_detector = detector  # type: ignore[union-attr]

        resp = client.get(
            f"/admin/rate-limits/player/{uuid.uuid4()}",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["cooldown"] is not None
        assert body["cooldown"]["active"] is True
        assert body["cooldown"]["remaining_seconds"] == 45
        assert body["cooldown"]["pattern"] == "rapid_turn"
        assert body["cooldown"]["violation_count"] == 3

    def test_get_ip_rate_limits_no_detector(self, settings: Settings) -> None:
        client = _build_client(settings)
        # abuse_detector is None by default

        resp = client.get(
            "/admin/rate-limits/ip/192.168.1.1",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["cooldown"] is None
        assert body["ip"] == "192.168.1.1"

    def test_get_player_rate_limits_no_activity_ec26_7(
        self, settings: Settings
    ) -> None:
        """EC-26.7: zero-activity player returns 200 with zeros, not 404."""
        client = _build_client(settings)
        cd = MagicMock()
        cd.active = False
        cd.remaining_seconds = 0
        cd.pattern = None
        cd.violation_count = 0
        detector = MagicMock()
        detector.check_cooldown = AsyncMock(return_value=cd)
        client.app.state.abuse_detector = detector  # type: ignore[union-attr]

        player_id = uuid.uuid4()
        resp = client.get(
            f"/admin/rate-limits/player/{player_id}",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["cooldown"]["active"] is False
        assert body["cooldown"]["violation_count"] == 0
        assert body["player_id"] == str(player_id)


# ── AC-26.7: Rate-limit management (write paths) ─────────────────


class TestRateLimitReset:
    """POST /admin/rate-limits/player/{id}/reset and /ip/{ip}/unblock (AC-26.7 write)."""

    def test_reset_player_rate_limits_clears_and_audits(
        self, settings: Settings
    ) -> None:
        client = _build_client(settings)
        detector = MagicMock()
        detector.clear_cooldown = AsyncMock()
        client.app.state.abuse_detector = detector  # type: ignore[union-attr]

        player_id = uuid.uuid4()
        resp = client.post(
            f"/admin/rate-limits/player/{player_id}/reset",
            json={"reason": "Manual admin reset for player"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rate_limits_cleared"
        assert body["player_id"] == str(player_id)

        detector.clear_cooldown.assert_awaited_once_with(str(player_id))

        audit_repo = client.app.state.audit_repo  # type: ignore[union-attr]
        call_kwargs = audit_repo.create_and_append.call_args
        assert call_kwargs.kwargs["action"] == "reset_player_rate_limits"

    def test_reset_player_no_detector_still_audits(self, settings: Settings) -> None:
        client = _build_client(settings)
        # abuse_detector is None by default

        player_id = uuid.uuid4()
        resp = client.post(
            f"/admin/rate-limits/player/{player_id}/reset",
            json={"reason": "Resetting player with no detector configured"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rate_limits_cleared"
        assert body["player_id"] == str(player_id)

        audit_repo = client.app.state.audit_repo  # type: ignore[union-attr]
        audit_repo.create_and_append.assert_awaited_once()

    def test_unblock_ip_clears_all_groups_and_audits(self, settings: Settings) -> None:
        client = _build_client(settings)
        client.app.state.rate_limiter.clear_key = AsyncMock()  # type: ignore[union-attr]

        resp = client.post(
            "/admin/rate-limits/ip/10.0.0.1/unblock",
            json={"reason": "Unblocking IP for admin review"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "unblocked"
        assert body["ip"] == "10.0.0.1"

        rl = client.app.state.rate_limiter  # type: ignore[union-attr]
        assert (
            rl.clear_key.await_count == 5
        )  # one per group: turns, game_mgmt, auth, sse, health

        audit_repo = client.app.state.audit_repo  # type: ignore[union-attr]
        call_kwargs = audit_repo.create_and_append.call_args
        assert call_kwargs.kwargs["action"] == "unblock_ip"

    def test_reset_requires_reason(self, settings: Settings) -> None:
        client = _build_client(settings)

        # Empty string fails min_length=1
        resp = client.post(
            f"/admin/rate-limits/player/{uuid.uuid4()}/reset",
            json={"reason": ""},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

        # Missing reason field also fails
        resp2 = client.post(
            f"/admin/rate-limits/player/{uuid.uuid4()}/reset",
            json={},
            headers=_auth_headers(),
        )
        assert resp2.status_code == 422
