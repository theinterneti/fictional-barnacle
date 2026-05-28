"""Tests for FastAPI application factory."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.config import Settings
from tta.llm.rate_limiter import RateLimitedLLMClient


@pytest.fixture()
def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        neo4j_uri="",
    )


@pytest.fixture()
def app(_settings: Settings) -> FastAPI:
    return create_app(_settings)


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ------------------------------------------------------------------
# App factory
# ------------------------------------------------------------------


class TestCreateApp:
    """create_app() returns a properly configured FastAPI app."""

    def test_returns_fastapi_instance(self, app: FastAPI) -> None:
        assert isinstance(app, FastAPI)

    def test_version_is_set(self, app: FastAPI) -> None:
        assert app.version == "0.1.0"

    def test_title_is_set(self, app: FastAPI) -> None:
        assert app.title == "Therapeutic Text Adventure"


# ------------------------------------------------------------------
# Request-ID middleware
# ------------------------------------------------------------------


class TestRequestIDMiddleware:
    """X-Request-ID header is always present on responses."""

    def test_adds_header_when_missing(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert "x-request-id" in resp.headers

    def test_generated_id_is_valid_uuid(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        uuid.UUID(resp.headers["x-request-id"])

    def test_preserves_provided_id(self, client: TestClient) -> None:
        custom_id = "my-custom-request-id"
        resp = client.get(
            "/api/v1/health",
            headers={"x-request-id": custom_id},
        )
        assert resp.headers["x-request-id"] == custom_id

    def test_propagates_x_trace_id(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/health",
            headers={"x-trace-id": "abc-trace-123"},
        )
        assert resp.headers["x-trace-id"] == "abc-trace-123"

    def test_x_trace_id_falls_back_to_request_id(self, client: TestClient) -> None:
        """When no X-Trace-Id is sent, the response still has one."""
        resp = client.get("/api/v1/health")
        assert "x-trace-id" in resp.headers
        assert "x-request-id" in resp.headers
        assert resp.headers["x-trace-id"] == resp.headers["x-request-id"]


# ------------------------------------------------------------------
# CORS middleware
# ------------------------------------------------------------------


class TestCORSMiddleware:
    """CORS headers are returned on preflight requests."""

    def test_cors_allows_origin(self, client: TestClient) -> None:
        resp = client.options(
            "/api/v1/health",
            headers={
                "origin": "http://localhost:3000",
                "access-control-request-method": "GET",
            },
        )
        assert "access-control-allow-origin" in resp.headers


# ------------------------------------------------------------------
# Lifespan wiring
# ------------------------------------------------------------------


class TestLifespanWiring:
    """Lifespan injects required services into app.state."""

    def test_consequence_service_injected(self, app: FastAPI) -> None:
        with TestClient(app) as c:
            deps = c.app.state.pipeline_deps  # type: ignore[union-attr]
            assert deps.consequence_service is not None

    def test_world_service_injected(self, app: FastAPI) -> None:
        with TestClient(app) as c:
            assert c.app.state.world_service is not None  # type: ignore[union-attr]

    def test_default_app_uses_rate_limited_llm_client(self, app: FastAPI) -> None:
        with TestClient(app) as c:
            assert isinstance(c.app.state.llm_client, RateLimitedLLMClient)  # type: ignore[union-attr]

    def test_default_app_shares_provider_snapshot_between_budget_and_inner_client(
        self, app: FastAPI
    ) -> None:
        with TestClient(app) as c:
            llm_client = c.app.state.llm_client  # type: ignore[union-attr]
            assert isinstance(llm_client, RateLimitedLLMClient)
            assert llm_client._budget._provider_utilization_snapshot is not None
            assert (
                llm_client._inner._provider_utilization_snapshot
                is llm_client._budget._provider_utilization_snapshot
            )

    def test_summary_service_qualifies_explicit_summary_model_alias(self) -> None:
        app = create_app(
            Settings(
                database_url="postgresql://test@localhost/test",
                neo4j_password="test",
                neo4j_uri="",
                summary_model="tta",
                llm_backend="openai",
            )
        )

        with TestClient(app) as c:
            assert c.app.state.summary_service._model == "openai/tta"  # type: ignore[union-attr]

    def test_summary_service_uses_qualified_litellm_model_fallback(self) -> None:
        app = create_app(
            Settings(
                database_url="postgresql://test@localhost/test",
                neo4j_password="test",
                neo4j_uri="",
                summary_model="",
                litellm_model="tta",
                llm_backend="openai",
            )
        )

        with TestClient(app) as c:
            assert c.app.state.summary_service._model == "openai/tta"  # type: ignore[union-attr]
