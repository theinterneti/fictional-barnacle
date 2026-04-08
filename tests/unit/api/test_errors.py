"""Tests for tta.api.errors — error types and exception handlers."""

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
            409, "HANDLE_ALREADY_TAKEN", "Handle is taken.", {"handle": "Zara"}
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
        err = AppError(404, "NOT_FOUND", "Not found", {"id": "123"})
        assert err.status_code == 404
        assert err.code == "NOT_FOUND"
        assert err.message == "Not found"
        assert err.details == {"id": "123"}

    def test_defaults_details_to_empty_dict(self) -> None:
        err = AppError(400, "BAD", "Bad request")
        assert err.details == {}


class TestAppErrorHandler:
    def test_returns_correct_status_and_envelope(self, client: TestClient) -> None:
        resp = client.get("/app-error")
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "HANDLE_ALREADY_TAKEN"
        assert body["error"]["message"] == "Handle is taken."
        assert body["error"]["details"] == {"handle": "Zara"}
        assert "request_id" in body["error"]


class TestValidationErrorHandler:
    def test_returns_422_with_envelope(self, client: TestClient) -> None:
        resp = client.post("/validation", json={"name": ""})
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "errors" in body["error"]["details"]


class TestUnhandledErrorHandler:
    def test_returns_500_without_details(self, app: FastAPI) -> None:
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/unhandled")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["error"]["details"] == {}
