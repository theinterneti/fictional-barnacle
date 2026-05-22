"""Unit tests for admin prompt management endpoints (§3.8 / FB-005)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tta.admin.auth import require_admin
from tta.api.routes.admin_prompts import router as admin_router

# ── fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def mock_bridge() -> MagicMock:
    """Return a mock LangfusePromptBridge."""
    bridge = MagicMock()
    bridge.activate = AsyncMock()
    bridge.preview = AsyncMock()
    return bridge


@pytest.fixture
def mock_audit_repo() -> MagicMock:
    """Return a mock audit repo that accepts create_and_append calls."""
    repo = MagicMock()
    repo.create_and_append = AsyncMock()
    return repo


def _make_app(mock_bridge, mock_audit_repo) -> FastAPI:
    """Create a minimal FastAPI app with admin router and mocks."""
    app = FastAPI()

    # Mock require_admin to always return a test identity
    from tta.admin.auth import AdminIdentity

    test_admin = AdminIdentity(admin_id="test-admin")

    async def override_require_admin() -> AdminIdentity:
        return test_admin

    app.dependency_overrides[require_admin] = override_require_admin

    app.state.prompt_bridge = mock_bridge
    app.state.audit_repo = mock_audit_repo
    app.state.pg = MagicMock()
    app.state.redis = MagicMock()
    app.state.settings = MagicMock()

    app.include_router(admin_router, prefix="/admin")

    return app


@pytest.fixture
def client(mock_bridge, mock_audit_repo) -> TestClient:
    app = _make_app(mock_bridge, mock_audit_repo)
    return TestClient(app)


# ── activate ──────────────────────────────────────────────────────


@pytest.mark.spec("AC-09.02")
def test_activate_prompt_returns_200(client, mock_bridge):
    """POST /admin/prompts/{name}/activate returns 200 with valid label."""
    response = client.post(
        "/admin/prompts/narrative-generate/activate",
        json={"label": "production"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "activated"
    assert data["prompt"] == "narrative-generate"
    assert data["label"] == "production"
    mock_bridge.activate.assert_awaited_once_with(
        "narrative.generate", label="production"
    )


def test_activate_prompt_invalid_label_too_long(client, mock_bridge):
    """POST /admin/prompts/{name}/activate returns 422 for overly long label."""
    response = client.post(
        "/admin/prompts/narrative-generate/activate",
        json={"label": "a" * 37},  # max is 36
    )
    assert response.status_code == 422


def test_activate_prompt_invalid_label_special_chars(client, mock_bridge):
    """POST /admin/prompts/{name}/activate returns 422 for invalid label chars."""
    response = client.post(
        "/admin/prompts/narrative-generate/activate",
        json={"label": "bad label!"},
    )
    assert response.status_code == 422


# ── preview ───────────────────────────────────────────────────────


@pytest.mark.spec("AC-09.09")
def test_preview_prompt_returns_200(client, mock_bridge):
    """POST /admin/prompts/{name}/preview returns rendered prompt."""
    # Setup mock preview to return a rendered prompt
    mock_rendered = MagicMock()
    mock_rendered.template_id = "narrative.generate"
    mock_rendered.text = "You are in a haunted manor."
    mock_rendered.fragment_versions = {}
    mock_rendered.prompt_hash = "abc123"
    mock_rendered.metadata = {
        "langfuse_prompt_version": 2,
        "langfuse_label": "staging",
    }
    mock_bridge.preview.return_value = mock_rendered

    response = client.post(
        "/admin/prompts/narrative-generate/preview",
        json={
            "label": "staging",
            "variables": {"world_name": "Haunted Manor"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["prompt"] == "narrative-generate"
    assert data["label"] == "staging"
    assert data["version"] == 2
    assert "rendered_body" in data
    assert data["rendered_body"] == "You are in a haunted manor."
    mock_bridge.preview.assert_awaited_once_with(
        "narrative.generate",
        variables={"world_name": "Haunted Manor"},
        label="staging",
    )


def test_preview_prompt_default_label(client, mock_bridge):
    """POST /admin/prompts/{name}/preview defaults to production label."""
    mock_rendered = MagicMock()
    mock_rendered.template_id = "narrative.generate"
    mock_rendered.text = "rendered"
    mock_rendered.fragment_versions = {}
    mock_rendered.prompt_hash = "abc"
    mock_rendered.metadata = {}
    mock_bridge.preview.return_value = mock_rendered

    response = client.post(
        "/admin/prompts/narrative-generate/preview",
        json={},
    )
    assert response.status_code == 200
    mock_bridge.preview.assert_awaited_once_with(
        "narrative.generate",
        variables={},
        label="production",
    )


def test_preview_prompt_invalid_label(client, mock_bridge):
    """POST /admin/prompts/{name}/preview returns 422 for invalid label."""
    response = client.post(
        "/admin/prompts/narrative-generate/preview",
        json={"label": "!!!invalid!!!"},
    )
    assert response.status_code == 422
