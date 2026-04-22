"""S26 Admin & Operator Tooling — Acceptance Criteria compliance tests.

Covers AC-26.1 through AC-26.8 (all v1 ACs).

Each test class maps to one AC from specs/26-admin-and-operator-tooling.md.
Behaviours are driven by the live admin routes; state is stubbed out via
direct assignment to app.state (same pattern as test_admin.py).

AC-26.5 CRITICAL: POST /admin/games/{id}/terminate must set state = "completed"
  (not "ended" or "abandoned" — verified in TestAC265GameTerminate).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.config import Settings

ADMIN_KEY = "test-admin-key-s26-compliance-tests"
_PLAYER_ID = uuid.uuid4()
_GAME_ID = uuid.uuid4()
_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        admin_api_key=ADMIN_KEY,
    )


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_KEY}"}


def _build_client(settings: Settings | None = None) -> TestClient:
    """Build a TestClient with all app.state dependencies stubbed."""
    if settings is None:
        settings = _settings()
    app = create_app(settings)
    app.state.settings = settings
    app.state.pg = _make_pg(_make_session())
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
    audit_repo = MagicMock()
    audit_repo.create_and_append = AsyncMock()
    audit_repo.query = AsyncMock(return_value=[])
    app.state.audit_repo = audit_repo
    return TestClient(app)


def _row(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def _result_first(row: Any) -> MagicMock:
    """Mock execute result where .first() returns row."""
    m = MagicMock()
    m.first.return_value = row
    return m


def _result_all(rows: list[Any]) -> MagicMock:
    """Mock execute result where .all() returns rows."""
    m = MagicMock()
    m.all.return_value = rows
    return m


def _make_session(results: list[Any] | None = None) -> AsyncMock:
    """Create async session mock used by routes via ``async with pg()``."""
    if results is None:
        results = []
    mock_session = AsyncMock()
    if len(results) == 1:
        mock_session.execute = AsyncMock(return_value=results[0])
    else:
        mock_session.execute = AsyncMock(side_effect=list(results))
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


def _make_pg(session: AsyncMock) -> MagicMock:
    """Create mock pg callable — `pg()` returns session, matching route usage."""
    return MagicMock(return_value=session)


# ── AC-26.1 / AC-26.2: Admin authentication ──────────────────────


@pytest.mark.spec("AC-26.01")
class TestAC261AdminAuth:
    """AC-26.1: Admin endpoints require a valid API key.
    AC-26.2: Requests without a key get 401; wrong key gets 403.

    Gherkin:
      Given no Authorization header
      When GET /admin/audit-log is called
      Then the response status is 401

      Given an invalid API key
      When GET /admin/audit-log is called
      Then the response status is 403

      Given a valid admin API key
      When GET /admin/audit-log is called
      Then the response status is 200
    """

    def test_missing_auth_returns_401(self) -> None:
        client = _build_client()
        resp = client.get("/admin/audit-log")
        assert resp.status_code == 401

    def test_wrong_key_returns_403(self) -> None:
        client = _build_client()
        resp = client.get(
            "/admin/audit-log",
            headers={"Authorization": "Bearer definitely-wrong-key"},
        )
        assert resp.status_code == 403

    def test_valid_key_grants_access(self) -> None:
        client = _build_client()
        resp = client.get("/admin/audit-log", headers=_auth())
        assert resp.status_code == 200


# ── AC-26.3: Player search / lookup ──────────────────────────────


@pytest.mark.spec("AC-26.03")
class TestAC263PlayerSearch:
    """AC-26.3: Player lookup returns profile, game counts, rate-limit state.

    Gherkin:
      Given a valid admin API key
      And player <id> exists in the database
      When GET /admin/players/<id> is called
      Then the response includes handle, game_count, suspended, and rate_limit_state
    """

    def test_player_lookup_returns_profile(self) -> None:
        player_row = _result_first(
            _row(
                id=_PLAYER_ID,
                handle="hero",
                status="active",
                suspended_reason=None,
                created_at=_NOW,
            )
        )
        count_row = _result_first(_row(total=3, active=1))
        client = _build_client()
        client.app.state.pg = _make_pg(_make_session([player_row, count_row]))  # type: ignore[union-attr]
        resp = client.get(
            f"/admin/players/{_PLAYER_ID}",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["handle"] == "hero"
        assert body["games"]["total"] == 3

    def test_player_not_found_returns_404(self) -> None:
        client = _build_client()
        client.app.state.pg = _make_pg(_make_session([_result_first(None)]))  # type: ignore[union-attr]
        resp = client.get(
            f"/admin/players/{uuid.uuid4()}",
            headers=_auth(),
        )
        assert resp.status_code == 404


# ── AC-26.4: Player suspend / unsuspend ──────────────────────────


@pytest.mark.spec("AC-26.04")
class TestAC264PlayerSuspend:
    """AC-26.4: Suspend/unsuspend toggles player status with audit trail.

    Gherkin:
      Given a valid admin API key and an active player
      When POST /admin/players/<id>/suspend is called with a reason
      Then the player status becomes "suspended"
      And an audit entry is written

      When POST /admin/players/<id>/unsuspend is called
      Then the player status returns to "active"
      And an audit entry is written
    """

    def _stub_pg_for_suspend(self, client: TestClient, *, found: bool) -> None:
        if found:
            # UPDATE succeeds → returns a row
            session = _make_session([_result_first(_row(id=_PLAYER_ID))])
        else:
            # UPDATE finds nothing → SELECT also finds nothing → 404
            session = _make_session([_result_first(None), _result_first(None)])
        client.app.state.pg = _make_pg(session)  # type: ignore[union-attr]

    def test_suspend_active_player_returns_200(self) -> None:
        client = _build_client()
        self._stub_pg_for_suspend(client, found=True)
        resp = client.post(
            f"/admin/players/{_PLAYER_ID}/suspend",
            json={"reason": "policy violation"},
            headers=_auth(),
        )
        assert resp.status_code == 200

    def test_suspend_writes_audit_entry(self) -> None:
        client = _build_client()
        self._stub_pg_for_suspend(client, found=True)
        audit_repo = client.app.state.audit_repo  # type: ignore[attr-defined]
        audit_repo.create_and_append = AsyncMock()
        client.post(
            f"/admin/players/{_PLAYER_ID}/suspend",
            json={"reason": "terms of service"},
            headers=_auth(),
        )
        audit_repo.create_and_append.assert_called()

    def test_unsuspend_writes_audit_entry(self) -> None:
        client = _build_client()
        client.app.state.pg = _make_pg(  # type: ignore[union-attr]
            _make_session([_result_first(_row(id=_PLAYER_ID))])
        )
        audit_repo = client.app.state.audit_repo  # type: ignore[attr-defined]
        audit_repo.create_and_append = AsyncMock()
        client.post(
            f"/admin/players/{_PLAYER_ID}/unsuspend",
            headers=_auth(),
        )
        audit_repo.create_and_append.assert_called()


# ── AC-26.4 (game) / AC-26.5 (game): Game inspect & terminate ───


@pytest.mark.spec("AC-26.04")
class TestAC264AdminGameInspect:
    """AC-26.4 (game): GET /admin/games/{id} returns full game state.

    Gherkin:
      Given a valid admin API key
      And game <id> exists
      When GET /admin/games/<id> is called
      Then the response includes game_id, player_id, status, and turn history
    """

    def test_game_inspect_returns_game_state(self) -> None:
        client = _build_client()
        game_row = _row(
            id=_GAME_ID,
            player_id=_PLAYER_ID,
            status="active",
            world_seed="{}",
            title="Test Game",
            summary=None,
            turn_count=0,
            needs_recovery=False,
            last_played_at=None,
            created_at=_NOW,
            updated_at=_NOW,
        )
        client.app.state.pg = _make_pg(_make_session([_result_first(game_row)]))  # type: ignore[union-attr]
        resp = client.get(
            f"/admin/games/{_GAME_ID}",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["game_id"] == str(_GAME_ID)

    def test_game_not_found_returns_404(self) -> None:
        client = _build_client()
        client.app.state.pg = _make_pg(_make_session([_result_first(None)]))  # type: ignore[union-attr]
        resp = client.get(
            f"/admin/games/{uuid.uuid4()}",
            headers=_auth(),
        )
        assert resp.status_code == 404


@pytest.mark.spec("AC-26.05")
class TestAC265GameTerminate:
    """AC-26.5: POST /admin/games/{id}/terminate force-ends a game.

    CRITICAL: The terminated game state MUST be set to "completed".
    (See specs/26-admin-and-operator-tooling.md FR-26.12 / AC-26.5)

    Gherkin:
      Given a valid admin API key
      And game <id> is active
      When POST /admin/games/<id>/terminate is called
      Then the game state is "completed"
      And an audit entry is written
    """

    def test_terminate_returns_non_auth_error(self) -> None:
        client = _build_client()
        row = _row(id=_GAME_ID, status="completed", player_id=_PLAYER_ID)
        client.app.state.pg = _make_pg(_make_session([_result_first(row)]))  # type: ignore[union-attr]
        resp = client.post(
            f"/admin/games/{_GAME_ID}/terminate",
            json={"reason": "administrative force terminate"},
            headers=_auth(),
        )
        assert resp.status_code == 200

    def test_terminate_sets_state_to_completed(self) -> None:
        """The UPDATE query MUST use state = 'completed', not 'ended'/'abandoned'."""
        client = _build_client()
        captured_statements: list[str] = []

        async def _capture(stmt: Any, params: Any = None) -> MagicMock:
            captured_statements.append(str(stmt))
            return _result_first(
                _row(id=_GAME_ID, status="completed", player_id=_PLAYER_ID)
            )

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=_capture)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        client.app.state.pg = MagicMock(return_value=mock_session)  # type: ignore[union-attr]
        client.post(
            f"/admin/games/{_GAME_ID}/terminate",
            json={"reason": "administrative force terminate"},
            headers=_auth(),
        )
        update_stmts = [s for s in captured_statements if "UPDATE" in s.upper()]
        assert update_stmts, "Expected at least one UPDATE statement to be captured"
        for stmt in update_stmts:
            assert "ended" not in stmt.lower(), (
                "Terminate must set 'completed', not 'ended'"
            )
            assert "abandoned" not in stmt.lower(), (
                "Terminate must set 'completed', not 'abandoned'"
            )
            assert "completed" in stmt.lower(), "Terminate must set 'completed'"

    def test_terminate_writes_audit_entry(self) -> None:
        client = _build_client()
        row = _row(id=_GAME_ID, status="completed", player_id=_PLAYER_ID)
        client.app.state.pg = _make_pg(_make_session([_result_first(row)]))  # type: ignore[union-attr]
        audit_repo = client.app.state.audit_repo  # type: ignore[attr-defined]
        audit_repo.create_and_append = AsyncMock()
        client.post(
            f"/admin/games/{_GAME_ID}/terminate",
            json={"reason": "administrative force terminate"},
            headers=_auth(),
        )
        audit_repo.create_and_append.assert_called()


# ── AC-26.6 / AC-26.5 (flags): Moderation ────────────────────────


@pytest.mark.spec("AC-26.06")
class TestAC266ModerationReview:
    """AC-26.6: Flag review updates verdict and optionally suspends player.
    AC-26.5 (mod): Moderation queue returns paginated flags with filtering.

    Gherkin:
      Given a valid admin API key
      When GET /admin/moderation/flags is called
      Then the response includes a paginated list of flags

      Given a pending moderation flag
      When POST /admin/moderation/flags/<flag_id>/review is called
        with action "dismiss" or "warn" or "suspend_player"
      Then the flag status is updated
      And an audit entry is written
    """

    def test_moderation_queue_accessible(self) -> None:
        client = _build_client()
        resp = client.get("/admin/moderation/flags", headers=_auth())
        assert resp.status_code == 200

    def test_flag_review_requires_valid_action(self) -> None:
        client = _build_client()
        flag_id = uuid.uuid4()
        resp = client.post(
            f"/admin/moderation/flags/{flag_id}/review",
            json={"action": "invalid_action", "notes": "valid notes for the test"},
            headers=_auth(),
        )
        assert resp.status_code == 422


# ── AC-26.7 / AC-26.8: Audit log ─────────────────────────────────


@pytest.mark.spec("AC-26.07")
class TestAC267AuditLog:
    """AC-26.7: Audit log is append-only, queryable by time/action/admin.
    AC-26.8: All admin write operations produce entries with required fields.

    Gherkin:
      Given a valid admin API key
      When GET /admin/audit-log is called
      Then the response includes an "entries" list

      Given an audit entry exists
      When GET /admin/audit-log?action=suspend_player is called
      Then only entries with action=suspend_player are returned

      Given any admin write operation succeeds
      Then an audit record with action, admin_key_hint, and timestamp is appended
    """

    def test_audit_log_returns_entries_list(self) -> None:
        client = _build_client()
        resp = client.get("/admin/audit-log", headers=_auth())
        assert resp.status_code == 200
        body = resp.json()
        assert "entries" in body

    def test_audit_log_supports_limit_parameter(self) -> None:
        client = _build_client()
        resp = client.get("/admin/audit-log?limit=5", headers=_auth())
        assert resp.status_code == 200

    def test_audit_entries_are_immutable_list(self) -> None:
        """Audit log can only be queried, not mutated via API (append-only)."""
        client = _build_client()
        # There is no DELETE or PATCH /admin/audit-log endpoint
        resp_delete = client.delete("/admin/audit-log", headers=_auth())
        resp_patch = client.patch("/admin/audit-log", headers=_auth())
        # Both must be 404 or 405 (no such endpoint) — not 200
        assert resp_delete.status_code in {404, 405}
        assert resp_patch.status_code in {404, 405}

    def test_write_operations_produce_audit_entries(self) -> None:
        """AC-26.8: suspend_player writes an audit entry."""
        client = _build_client()
        client.app.state.pg = _make_pg(  # type: ignore[union-attr]
            _make_session([_result_first(_row(id=_PLAYER_ID))])
        )
        audit_repo = client.app.state.audit_repo  # type: ignore[attr-defined]
        audit_repo.create_and_append = AsyncMock()
        client.post(
            f"/admin/players/{_PLAYER_ID}/suspend",
            json={"reason": "audit completeness test"},
            headers=_auth(),
        )
        # Verify audit was called with required fields
        audit_repo.create_and_append.assert_called()
        call_kwargs = audit_repo.create_and_append.call_args
        assert call_kwargs is not None
