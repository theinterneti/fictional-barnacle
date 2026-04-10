"""Tests for admin authentication (S26 FR-26.01–FR-26.04)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from tta.admin.auth import AdminIdentity, require_admin
from tta.api.errors import AppError

# ── Helpers ──────────────────────────────────────────────────────────


@dataclass
class _FakeClient:
    host: str = "127.0.0.1"


@dataclass
class _FakeURL:
    path: str = "/admin/test"


@dataclass
class _FakeSettings:
    admin_api_key: str | None = "test-secret-key"


@dataclass
class _FakeAppState:
    settings: _FakeSettings = field(default_factory=_FakeSettings)


@dataclass
class _FakeApp:
    state: _FakeAppState = field(default_factory=_FakeAppState)


class _FakeRequest:
    """Minimal Request double for testing require_admin."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        *,
        admin_key: str | None = "test-secret-key",
    ) -> None:
        self._headers = headers or {}
        self.client = _FakeClient()
        self.url = _FakeURL()
        self.method = "GET"
        self.app = _FakeApp(
            state=_FakeAppState(settings=_FakeSettings(admin_api_key=admin_key))
        )

    @property
    def headers(self) -> dict[str, Any]:
        return self._headers


# ── Tests ────────────────────────────────────────────────────────────


class TestRequireAdmin:
    """Test the require_admin FastAPI dependency."""

    @pytest.mark.anyio
    async def test_valid_token_returns_identity(self) -> None:
        req = _FakeRequest(headers={"Authorization": "Bearer test-secret-key"})
        result = await require_admin(req)  # type: ignore[arg-type]
        assert isinstance(result, AdminIdentity)
        assert result.admin_id == "admin"

    @pytest.mark.anyio
    async def test_missing_auth_header_raises_401(self) -> None:
        req = _FakeRequest(headers={})
        with pytest.raises(AppError) as exc:
            await require_admin(req)  # type: ignore[arg-type]
        assert exc.value.code == "ADMIN_TOKEN_MISSING"

    @pytest.mark.anyio
    async def test_no_bearer_prefix_raises_401(self) -> None:
        req = _FakeRequest(headers={"Authorization": "test-secret-key"})
        with pytest.raises(AppError) as exc:
            await require_admin(req)  # type: ignore[arg-type]
        assert exc.value.code == "ADMIN_TOKEN_MISSING"

    @pytest.mark.anyio
    async def test_wrong_token_raises_403(self) -> None:
        req = _FakeRequest(headers={"Authorization": "Bearer wrong-token"})
        with pytest.raises(AppError) as exc:
            await require_admin(req)  # type: ignore[arg-type]
        assert exc.value.code == "ADMIN_TOKEN_INVALID"

    @pytest.mark.anyio
    async def test_admin_not_configured_raises_403(self) -> None:
        req = _FakeRequest(
            headers={"Authorization": "Bearer anything"},
            admin_key=None,
        )
        with pytest.raises(AppError) as exc:
            await require_admin(req)  # type: ignore[arg-type]
        assert exc.value.code == "ADMIN_NOT_CONFIGURED"

    @pytest.mark.anyio
    async def test_empty_admin_key_raises_403(self) -> None:
        req = _FakeRequest(
            headers={"Authorization": "Bearer anything"},
            admin_key="",
        )
        with pytest.raises(AppError) as exc:
            await require_admin(req)  # type: ignore[arg-type]
        assert exc.value.code == "ADMIN_NOT_CONFIGURED"

    @pytest.mark.anyio
    async def test_similar_token_rejected(self) -> None:
        """Timing-safe comparison rejects near-match tokens."""
        req = _FakeRequest(headers={"Authorization": "Bearer test-secret-ke"})
        with pytest.raises(AppError) as exc:
            await require_admin(req)  # type: ignore[arg-type]
        assert exc.value.code == "ADMIN_TOKEN_INVALID"
