"""Tests for PrometheusMiddleware."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.config import Settings
from tta.observability.metrics import (
    REGISTRY,
)


@pytest.fixture()
def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


@pytest.fixture()
def app(_settings: Settings) -> FastAPI:
    return create_app(settings=_settings)


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _sample_value(
    sample_name: str,
    labels: dict[str, str],
) -> float | None:
    """Read a specific sample value from the custom REGISTRY.

    Uses sample.name (e.g. ``tta_http_requests_total``) rather than
    metric family name, because prometheus_client strips ``_total``
    from Counter family names.
    """
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == sample_name and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return None


class TestPrometheusMiddleware:
    """PrometheusMiddleware records HTTP metrics."""

    def test_records_request_count(self, client: TestClient) -> None:
        """Middleware increments tta_http_requests_total."""
        client.get("/api/v1/health")
        val = _sample_value(
            "tta_http_requests_total",
            {"method": "GET", "status": "200"},
        )
        assert val is not None and val >= 1.0

    def test_records_request_duration(self, client: TestClient) -> None:
        """Middleware records tta_http_request_duration_seconds."""
        client.get("/api/v1/health")
        found = False
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if (
                    sample.name == "tta_http_request_duration_seconds_count"
                    and sample.value >= 1
                ):
                    found = True
        assert found, "Expected at least 1 duration sample"

    def test_metrics_excluded_from_self_instrumentation(
        self, client: TestClient
    ) -> None:
        """GET /metrics should not appear in HTTP metrics."""
        client.get("/metrics")
        val = _sample_value(
            "tta_http_requests_total",
            {"method": "GET", "route": "/metrics"},
        )
        assert val is None


class TestRoutePatternExtraction:
    """Middleware uses route patterns, not raw paths, as labels."""

    def test_uses_route_pattern(self, client: TestClient) -> None:
        """Route pattern should appear as label, not raw path with IDs."""
        client.get("/api/v1/health")
        val = _sample_value(
            "tta_http_requests_total",
            {"method": "GET", "route": "/api/v1/health"},
        )
        assert val is not None and val >= 1.0
