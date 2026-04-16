"""Tests for player registration, profile, and consent routes."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import get_current_player, get_pg
from tta.api.errors import AppError
from tta.config import CURRENT_CONSENT_VERSION, Settings
from tta.models.player import Player

if TYPE_CHECKING:
    from fastapi import FastAPI

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_PLAYER = Player(id=_PLAYER_ID, handle="Zara", created_at=_NOW)

# Player with consent populated (for consent-aware tests)
_CONSENTED_PLAYER = Player(
    id=_PLAYER_ID,
    handle="Zara",
    created_at=_NOW,
    consent_version=CURRENT_CONSENT_VERSION,
    consent_accepted_at=_NOW,
    consent_categories={"core_gameplay": True, "llm_processing": True},
    age_confirmed_at=_NOW,
    consent_ip_hash="abc123",
)

# Valid registration body matching new CreatePlayerRequest schema
_VALID_REG = {
    "handle": "NewPlayer",
    "age_13_plus_confirmed": True,
    "consent_version": CURRENT_CONSENT_VERSION,
    "consent_categories": {"core_gameplay": True, "llm_processing": True},
}


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


def _make_result(
    rows: list[dict[str, Any]] | None = None,
    *,
    scalar: Any = None,
) -> MagicMock:
    """Build a mock CursorResult with .one_or_none / .scalar_one / .all.

    These methods are synchronous on SQLAlchemy CursorResult, so use
    MagicMock (not AsyncMock).
    """
    result = MagicMock()
    if rows is not None:
        objs = [SimpleNamespace(**r) for r in rows]
        result.one_or_none.return_value = objs[0] if objs else None
        result.one.return_value = objs[0] if objs else None
        result.all.return_value = objs
    else:
        result.one_or_none.return_value = None
        result.one.return_value = None
        result.all.return_value = []
    if scalar is not None:
        result.scalar_one.return_value = scalar
    return result


@pytest.fixture
def pg() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def app(pg: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    settings = _settings()
    monkeypatch.setattr("tta.api.routes.players.get_settings", lambda: settings)
    monkeypatch.setattr("tta.auth.jwt.get_settings", lambda: settings)
    monkeypatch.setattr("tta.auth.passwords.get_settings", lambda: settings)
    a = create_app(settings=settings)

    async def _pg():
        yield pg

    a.dependency_overrides[get_pg] = _pg
    a.dependency_overrides[get_current_player] = lambda: _PLAYER
    return a


@pytest.fixture
def consented_app(pg: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """App where the authenticated player has valid consent."""
    settings = _settings()
    monkeypatch.setattr("tta.api.routes.players.get_settings", lambda: settings)
    monkeypatch.setattr("tta.auth.jwt.get_settings", lambda: settings)
    monkeypatch.setattr("tta.auth.passwords.get_settings", lambda: settings)
    a = create_app(settings=settings)

    async def _pg():
        yield pg

    a.dependency_overrides[get_pg] = _pg
    a.dependency_overrides[get_current_player] = lambda: _CONSENTED_PLAYER
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def consented_client(consented_app: FastAPI) -> TestClient:
    return TestClient(consented_app)


# ------------------------------------------------------------------
# POST /api/v1/players — Registration
# ------------------------------------------------------------------


class TestRegisterPlayer:
    def test_creates_player_and_returns_201(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),  # SELECT id → None (handle not taken)
                _make_result(),  # INSERT player
                _make_result(),  # INSERT session
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/players", json=_VALID_REG)

        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["handle"] == "NewPlayer"
        assert "session_token" in body
        assert "player_id" in body
        assert pg.commit.await_count == 1

    def test_sets_session_cookie(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),
                _make_result(),
                _make_result(),
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(
            "/api/v1/players",
            json={**_VALID_REG, "handle": "CookieTest"},
        )

        assert resp.status_code == 201
        assert "tta_session" in resp.cookies

    def test_rejects_duplicate_handle(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(return_value=_make_result([{"id": uuid4()}]))

        resp = client.post(
            "/api/v1/players",
            json={**_VALID_REG, "handle": "Zara"},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "HANDLE_ALREADY_TAKEN"

    def test_rejects_empty_handle(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/players",
            json={**_VALID_REG, "handle": ""},
        )
        assert resp.status_code == 422

    def test_rejects_invalid_handle_chars(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/players",
            json={**_VALID_REG, "handle": "bad@handle!"},
        )
        assert resp.status_code == 422

    # --- Age gate (S17 FR-17.36) ---

    def test_rejects_age_not_confirmed(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/players",
            json={**_VALID_REG, "age_13_plus_confirmed": False},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "AGE_CONFIRMATION_REQUIRED"

    # --- Consent version (S17 FR-17.22) ---

    def test_rejects_wrong_consent_version(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/players",
            json={**_VALID_REG, "consent_version": "0.1"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "CONSENT_VERSION_MISMATCH"

    # --- Required consent categories (S17 FR-17.24) ---

    def test_rejects_missing_required_consent_category(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/v1/players",
            json={
                **_VALID_REG,
                "consent_categories": {"core_gameplay": True},
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "REQUIRED_CONSENT_MISSING"

    def test_rejects_declined_required_consent(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/players",
            json={
                **_VALID_REG,
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": False,
                },
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "REQUIRED_CONSENT_MISSING"

    def test_registration_missing_consent_fields_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post("/api/v1/players", json={"handle": "OnlyHandle"})
        assert resp.status_code == 422


# ------------------------------------------------------------------
# GET /api/v1/players/me — Profile
# ------------------------------------------------------------------


class TestGetProfile:
    def test_returns_authenticated_player(self, client: TestClient) -> None:
        resp = client.get("/api/v1/players/me")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["player_id"] == str(_PLAYER_ID)
        assert body["handle"] == "Zara"


# ------------------------------------------------------------------
# PATCH /api/v1/players/me — Update profile
# ------------------------------------------------------------------


class TestUpdateProfile:
    def test_updates_handle(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),  # uniqueness check → not taken
                _make_result(),  # UPDATE
            ]
        )
        pg.commit = AsyncMock()

        resp = client.patch(
            "/api/v1/players/me",
            json={"handle": "NewName"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["handle"] == "NewName"
        assert pg.commit.await_count == 1

    def test_noop_when_no_changes(self, client: TestClient) -> None:
        resp = client.patch(
            "/api/v1/players/me",
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["handle"] == "Zara"

    def test_rejects_duplicate_handle(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(return_value=_make_result([{"id": uuid4()}]))

        resp = client.patch(
            "/api/v1/players/me",
            json={"handle": "TakenName"},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "HANDLE_ALREADY_TAKEN"

    def test_skips_uniqueness_check_when_unchanged(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        resp = client.patch(
            "/api/v1/players/me",
            json={"handle": "Zara"},  # same as current
        )
        assert resp.status_code == 200
        # No DB calls needed
        pg.execute.assert_not_awaited()


# ------------------------------------------------------------------
# GET /api/v1/players/me/consent — Consent state
# ------------------------------------------------------------------


class TestGetConsent:
    def test_returns_consent_state(self, consented_client: TestClient) -> None:
        resp = consented_client.get("/api/v1/players/me/consent")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["consent_version"] == CURRENT_CONSENT_VERSION
        assert data["consent_accepted_at"] is not None
        assert data["consent_categories"]["core_gameplay"] is True
        assert data["consent_categories"]["llm_processing"] is True
        assert data["age_confirmed_at"] is not None

    def test_returns_null_consent_for_pre_consent_player(
        self, client: TestClient
    ) -> None:
        """Pre-consent player (consent fields are None)."""
        resp = client.get("/api/v1/players/me/consent")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["consent_version"] is None
        assert data["consent_accepted_at"] is None
        assert data["consent_categories"] is None
        assert data["age_confirmed_at"] is None


# ------------------------------------------------------------------
# PATCH /api/v1/players/me/consent — Update consent
# ------------------------------------------------------------------


class TestUpdateConsent:
    def test_update_consent_happy_path(
        self, consented_client: TestClient, pg: AsyncMock
    ) -> None:
        # UPDATE + commit + SELECT for merged state
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),  # UPDATE
                _make_result(
                    [
                        {
                            "consent_version": CURRENT_CONSENT_VERSION,
                            "consent_accepted_at": _NOW,
                            "consent_categories": {
                                "core_gameplay": True,
                                "llm_processing": True,
                                "analytics": True,
                            },
                            "age_confirmed_at": _NOW,
                        }
                    ]
                ),
            ]
        )
        pg.commit = AsyncMock()

        resp = consented_client.patch(
            "/api/v1/players/me/consent",
            json={
                "consent_version": CURRENT_CONSENT_VERSION,
                "consent_categories": {"analytics": True},
            },
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["consent_version"] == CURRENT_CONSENT_VERSION
        assert data["consent_categories"]["analytics"] is True
        assert pg.commit.await_count == 1

    def test_rejects_version_mismatch(self, consented_client: TestClient) -> None:
        resp = consented_client.patch(
            "/api/v1/players/me/consent",
            json={
                "consent_version": "0.1",
                "consent_categories": {"analytics": True},
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "CONSENT_VERSION_MISMATCH"

    def test_rejects_required_category_withdrawal(
        self, consented_client: TestClient
    ) -> None:
        resp = consented_client.patch(
            "/api/v1/players/me/consent",
            json={
                "consent_version": CURRENT_CONSENT_VERSION,
                "consent_categories": {"core_gameplay": False},
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "REQUIRED_CONSENT_WITHDRAWAL"

    def test_allows_optional_category_withdrawal(
        self, consented_client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),
                _make_result(
                    [
                        {
                            "consent_version": CURRENT_CONSENT_VERSION,
                            "consent_accepted_at": _NOW,
                            "consent_categories": {
                                "core_gameplay": True,
                                "llm_processing": True,
                                "analytics": False,
                            },
                            "age_confirmed_at": _NOW,
                        }
                    ]
                ),
            ]
        )
        pg.commit = AsyncMock()

        resp = consented_client.patch(
            "/api/v1/players/me/consent",
            json={
                "consent_version": CURRENT_CONSENT_VERSION,
                "consent_categories": {"analytics": False},
            },
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["consent_categories"]["analytics"] is False


# ------------------------------------------------------------------
# require_consent() dependency
# ------------------------------------------------------------------


class TestRequireConsent:
    """Test the require_consent dependency via a route that uses it.

    The game routes depend on require_consent. We test indirectly by
    checking that a player without consent gets 403.
    """

    @pytest.mark.asyncio
    async def test_blocks_player_without_consent(self) -> None:
        """_PLAYER has no consent fields → game routes should 403."""
        from tta.api.deps import require_consent

        with pytest.raises(AppError) as exc_info:
            await require_consent(_PLAYER)
        assert exc_info.value.code == "CONSENT_REQUIRED"
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_passes_consented_player(self) -> None:
        """_CONSENTED_PLAYER has valid consent → should pass."""
        from tta.api.deps import require_consent

        result = await require_consent(_CONSENTED_PLAYER)
        assert result.id == _CONSENTED_PLAYER.id

    @pytest.mark.asyncio
    async def test_blocks_stale_consent_version(self) -> None:
        """Player with old consent version → should 403."""
        from tta.api.deps import require_consent

        stale = Player(
            id=_PLAYER_ID,
            handle="Stale",
            created_at=_NOW,
            consent_version="0.9",
            consent_accepted_at=_NOW,
        )
        with pytest.raises(AppError) as exc_info:
            await require_consent(stale)
        assert exc_info.value.code == "CONSENT_REQUIRED"
        assert exc_info.value.status_code == 403


# ------------------------------------------------------------------
# GET /api/v1/disclaimer
# ------------------------------------------------------------------


class TestDisclaimerEndpoint:
    def test_returns_disclaimer(self, client: TestClient) -> None:
        resp = client.get("/api/v1/disclaimer")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "disclaimer" in data
        assert "not a substitute" in data["disclaimer"].lower()
        assert "hipaa_notice" in data
        assert "PHI" in data["hipaa_notice"]
