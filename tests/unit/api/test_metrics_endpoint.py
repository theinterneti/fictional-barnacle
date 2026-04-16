"""Tests for Prometheus metrics endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.config import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest.fixture
def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


@pytest.fixture
def app(_settings: Settings) -> FastAPI:
    return create_app(settings=_settings)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestMetricsEndpoint:
    """GET /metrics returns Prometheus exposition format."""

    def test_status_200(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_content_type(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]
        assert "0.0.4" in resp.headers["content-type"]

    def test_body_contains_tta_metrics(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        body = resp.text
        assert "tta_http_requests_total" in body or "tta_turn_total" in body

    def test_not_under_api_prefix(self, client: TestClient) -> None:
        resp = client.get("/api/v1/metrics")
        assert resp.status_code in {404, 405}
