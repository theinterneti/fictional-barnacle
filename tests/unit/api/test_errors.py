"""Tests for tta.api.errors — error types and exception handlers."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from tta.api.errors import (
    AppError,
    app_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from tta.config import Environment
from tta.errors import ErrorCategory


@pytest.fixture()
def app() -> FastAPI:
    """Minimal app with error handlers wired up."""
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)  # type: ignore[arg-type]

    class Item(BaseModel):
        name: str = Field(..., min_length=1)

    @app.get("/ok")
    async def ok(request: Request) -> dict:
        request.state.request_id = "test-req-id"
        return {"status": "ok"}

    @app.get("/app-error")
    async def trigger_app_error(request: Request) -> None:
        request.state.request_id = "test-req-id"
        raise AppError(
            ErrorCategory.CONFLICT,
            "HANDLE_ALREADY_TAKEN",
            "Handle is taken.",
            {"handle": "Zara"},
        )

    @app.post("/validation")
    async def trigger_validation(request: Request, item: Item) -> dict:
        request.state.request_id = "test-req-id"
        return {"name": item.name}

    @app.get("/unhandled")
    async def trigger_unhandled(request: Request) -> None:
        request.state.request_id = "test-req-id"
        msg = "boom"
        raise RuntimeError(msg)

    return app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestAppError:
    def test_attributes(self) -> None:
        err = AppError(ErrorCategory.NOT_FOUND, "NOT_FOUND", "Not found", {"id": "123"})
        assert err.status_code == 404
        assert err.code == "NOT_FOUND"
        assert err.message == "Not found"
        assert err.details == {"id": "123"}

    def test_defaults_details_to_none(self) -> None:
        err = AppError(ErrorCategory.INPUT_INVALID, "BAD", "Bad request")
        assert err.details is None

    def test_retry_after_seconds(self) -> None:
        err = AppError(
            ErrorCategory.RATE_LIMITED,
            "RATE_LIMITED",
            "Too many requests",
            retry_after_seconds=30,
        )
        assert err.retry_after_seconds == 30
        assert err.status_code == 429

    def test_category_to_status_mapping(self) -> None:
        """AC-23.1: Every error category maps to the correct HTTP status."""
        expected = {
            ErrorCategory.INPUT_INVALID: 400,
            ErrorCategory.AUTH_REQUIRED: 401,
            ErrorCategory.FORBIDDEN: 403,
            ErrorCategory.NOT_FOUND: 404,
            ErrorCategory.CONFLICT: 409,
            ErrorCategory.RATE_LIMITED: 429,
            ErrorCategory.LLM_FAILURE: 502,
            ErrorCategory.SERVICE_UNAVAILABLE: 503,
            ErrorCategory.INTERNAL_ERROR: 500,
        }
        for category, status in expected.items():
            err = AppError(category, "TEST", "test")
            assert err.status_code == status, f"{category} → {status}"


class TestAppErrorHandler:
    def test_returns_correct_status_and_envelope(self, client: TestClient) -> None:
        """AC-23.10: Standard error envelope shape."""
        resp = client.get("/app-error")
        assert resp.status_code == 409
        body = resp.json()
        err = body["error"]
        assert err["code"] == "HANDLE_ALREADY_TAKEN"
        assert err["message"] == "Handle is taken."
        assert err["details"] == {"handle": "Zara"}
        assert "request_id" in err
        assert err["retry_after_seconds"] is None

    def test_retry_after_header(self, app: FastAPI) -> None:
        """Retry-After header set when retry_after_seconds is provided."""

        @app.get("/rate-limited")
        async def trigger_rate_limited(request: Request) -> None:
            request.state.request_id = "test-req-id"
            raise AppError(
                ErrorCategory.RATE_LIMITED,
                "RATE_LIMITED",
                "Too fast",
                retry_after_seconds=60,
            )

        with TestClient(app) as c:
            resp = c.get("/rate-limited")
        assert resp.status_code == 429
        assert resp.headers["Retry-After"] == "60"
        assert resp.json()["error"]["retry_after_seconds"] == 60


class TestValidationErrorHandler:
    def test_returns_422_with_envelope(self, client: TestClient) -> None:
        resp = client.post("/validation", json={"name": ""})
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "errors" in body["error"]["details"]
        assert body["error"]["retry_after_seconds"] is None


class TestUnhandledErrorHandler:
    def test_returns_500_without_details(self, app: FastAPI) -> None:
        """AC-23.11: No info leak for unhandled errors in production."""
        mock_settings = type("S", (), {"environment": Environment.PRODUCTION})()
        with (
            patch("tta.api.errors.get_settings", return_value=mock_settings),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            resp = c.get("/unhandled")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["error"]["details"] is None
        assert body["error"]["retry_after_seconds"] is None

    def test_returns_500_with_details_in_dev(self, app: FastAPI) -> None:
        """In development, exception details are exposed for debugging."""
        mock_settings = type("S", (), {"environment": Environment.DEVELOPMENT})()
        with (
            patch("tta.api.errors.get_settings", return_value=mock_settings),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            resp = c.get("/unhandled")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["details"] == {"exception": "RuntimeError: boom"}
