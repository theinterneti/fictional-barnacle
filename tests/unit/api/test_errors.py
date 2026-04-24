"""Tests for tta.api.errors — error types and exception handlers."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from tta.api.errors import (
    AppError,
    _request_context,
    _sanitize_traceback,
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

    @app.get("/app-error-with-context")
    async def trigger_app_error_with_ctx(request: Request) -> None:
        request.state.request_id = "test-req-id"
        request.state.player_id = "player-42"
        request.state.game_id = "game-7"
        raise AppError(
            ErrorCategory.NOT_FOUND,
            "GAME_NOT_FOUND",
            "Game not found.",
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

    @app.get("/unhandled-pii")
    async def trigger_unhandled_pii(request: Request) -> None:
        request.state.request_id = "test-req-id"
        msg = "Failed to process user@secret.com with token abc123"
        raise ValueError(msg)

    return app


@pytest.fixture()
def capture_logs() -> Generator[list[dict[str, object]], None, None]:
    """Capture structlog output for assertion."""
    with structlog.testing.capture_logs() as logs:
        yield logs


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

    @pytest.mark.spec("AC-23.01")
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
    pytestmark = [pytest.mark.spec("AC-23.01")]

    def test_returns_correct_status_and_envelope(self, client: TestClient) -> None:
        """AC-23.10: Standard error envelope shape."""
        resp = client.get("/app-error")
        assert resp.status_code == 409
        body = resp.json()
        err = body["error"]
        assert err["code"] == "HANDLE_ALREADY_TAKEN"
        assert err["message"] == "Handle is taken."
        assert err["details"] == {"handle": "Zara"}
        assert "correlation_id" in err
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
    pytestmark = [pytest.mark.spec("AC-23.11")]

    def test_returns_422_with_envelope(self, client: TestClient) -> None:
        resp = client.post("/validation", json={"name": ""})
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "errors" in body["error"]["details"]
        assert body["error"]["retry_after_seconds"] is None

    def test_strips_input_field_from_errors(self, client: TestClient) -> None:
        """PR #76 review debt: validation errors must not leak user input."""
        resp = client.post("/validation", json={"name": ""})
        assert resp.status_code == 422
        errors = resp.json()["error"]["details"]["errors"]
        for err in errors:
            assert "input" not in err, "Pydantic 'input' field leaked to client"

    def test_strips_url_field_from_errors(self, client: TestClient) -> None:
        """Pydantic V2 'url' field is not useful to clients and stripped."""
        resp = client.post("/validation", json={"name": ""})
        assert resp.status_code == 422
        errors = resp.json()["error"]["details"]["errors"]
        for err in errors:
            assert "url" not in err

    def test_preserves_type_loc_msg_fields(self, client: TestClient) -> None:
        """Essential error fields (type, loc, msg) are preserved."""
        resp = client.post("/validation", json={"name": ""})
        assert resp.status_code == 422
        errors = resp.json()["error"]["details"]["errors"]
        assert len(errors) >= 1
        err = errors[0]
        assert "type" in err
        assert "loc" in err
        assert "msg" in err


class TestUnhandledErrorHandler:
    @pytest.mark.spec("AC-23.10")
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
        assert body["error"]["details"] == {"exception_type": "RuntimeError"}


class TestStructuredErrorLogging:
    """AC-23.2: Error handlers emit structured log events with FR-23.06 fields."""

    pytestmark = [pytest.mark.spec("AC-23.02")]

    def test_app_error_logs_structured_fields(
        self,
        app: FastAPI,
        capture_logs: list[dict[str, object]],
    ) -> None:
        """FR-23.06: app errors log error_code, category, status, correlation_id."""
        with TestClient(app) as c:
            c.get("/app-error")
        err_logs = [e for e in capture_logs if e.get("event") == "app_error"]
        assert len(err_logs) == 1
        log = err_logs[0]
        assert log["error_code"] == "HANDLE_ALREADY_TAKEN"
        assert log["error_category"] == "conflict"
        assert log["status_code"] == 409
        assert log["correlation_id"] == "test-req-id"
        assert log["request_method"] == "GET"
        assert log["request_path"] == "/app-error"
        assert log["player_id"] == "anonymous"
        assert log["log_level"] == "warning"

    def test_app_error_logs_player_and_game_ids(
        self,
        app: FastAPI,
        capture_logs: list[dict[str, object]],
    ) -> None:
        """FR-23.06: player_id and game_id logged when available."""
        with TestClient(app) as c:
            c.get("/app-error-with-context")
        err_logs = [e for e in capture_logs if e.get("event") == "app_error"]
        assert len(err_logs) == 1
        log = err_logs[0]
        assert log["player_id"] == "player-42"
        assert log["game_id"] == "game-7"

    def test_validation_error_logs_structured_fields(
        self,
        app: FastAPI,
        capture_logs: list[dict[str, object]],
    ) -> None:
        """FR-23.06: validation errors logged as structured warnings."""
        with TestClient(app) as c:
            c.post("/validation", json={"name": ""})
        err_logs = [e for e in capture_logs if e.get("event") == "validation_error"]
        assert len(err_logs) == 1
        log = err_logs[0]
        assert log["error_code"] == "VALIDATION_ERROR"
        assert log["error_category"] == "schema_invalid"
        assert log["status_code"] == 422
        assert log["request_method"] == "POST"
        assert log["request_path"] == "/validation"
        assert log["log_level"] == "warning"

    def test_unhandled_error_logs_exception_fields(
        self,
        app: FastAPI,
        capture_logs: list[dict[str, object]],
    ) -> None:
        """FR-23.07: unhandled errors include exception_type, message, stack_trace."""
        mock_settings = type("S", (), {"environment": Environment.PRODUCTION})()
        with (
            patch("tta.api.errors.get_settings", return_value=mock_settings),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.get("/unhandled")
        err_logs = [e for e in capture_logs if e.get("event") == "unhandled_error"]
        assert len(err_logs) == 1
        log = err_logs[0]
        assert log["error_code"] == "INTERNAL_ERROR"
        assert log["error_category"] == "internal_error"
        assert log["status_code"] == 500
        assert log["exception_type"] == "RuntimeError"
        assert "Traceback" in str(log["stack_trace"])
        assert log["request_method"] == "GET"
        assert log["request_path"] == "/unhandled"
        assert log["log_level"] == "error"

    def test_error_logs_contain_no_pii(
        self,
        app: FastAPI,
        capture_logs: list[dict[str, object]],
    ) -> None:
        """FR-23.08: error logs contain IDs only, never data values."""
        with TestClient(app) as c:
            c.get("/app-error")
        err_logs = [e for e in capture_logs if e.get("event") == "app_error"]
        log = err_logs[0]
        # Error details (handle: Zara) must NOT leak into logs
        pii_fields = {"player_input", "turn_content", "narrative_text", "email"}
        assert not pii_fields.intersection(log.keys())


class TestRequestContext:
    """Unit tests for _request_context helper."""

    def _make_request(self, **state_attrs: object) -> Request:
        """Build a minimal ASGI request with state attributes."""
        scope = {"type": "http", "method": "POST", "path": "/test", "headers": []}
        req = Request(scope)
        for k, v in state_attrs.items():
            setattr(req.state, k, v)
        return req

    def test_extracts_all_ids(self) -> None:
        req = self._make_request(
            request_id="req-1",
            player_id="player-2",
            game_id="game-3",
            turn_id="turn-4",
        )
        ctx = _request_context(req)
        assert ctx["correlation_id"] == "req-1"
        assert ctx["player_id"] == "player-2"
        assert ctx["game_id"] == "game-3"
        assert ctx["turn_id"] == "turn-4"
        assert ctx["request_method"] == "POST"
        assert ctx["request_path"] == "/test"

    def test_anonymous_player_when_no_player_id(self) -> None:
        req = self._make_request(request_id="req-1")
        ctx = _request_context(req)
        assert ctx["player_id"] == "anonymous"

    def test_omits_missing_optional_ids(self) -> None:
        req = self._make_request(request_id="req-1")
        ctx = _request_context(req)
        assert "game_id" not in ctx
        assert "turn_id" not in ctx


class TestSanitizeTraceback:
    """PR #76 review debt: stack traces must not leak user data."""

    def test_redacts_exception_messages(self) -> None:
        tb = (
            "Traceback (most recent call last):\n"
            '  File "app.py", line 42, in handle\n'
            "    process(data)\n"
            "ValueError: user@secret.com is invalid\n"
        )
        result = _sanitize_traceback(tb)
        assert "user@secret.com" not in result
        assert "ValueError: <redacted>" in result

    def test_preserves_frame_info(self) -> None:
        tb = (
            "Traceback (most recent call last):\n"
            '  File "app.py", line 42, in handle\n'
            "    process(data)\n"
            "RuntimeError: sensitive data here\n"
        )
        result = _sanitize_traceback(tb)
        assert "Traceback (most recent call last):" in result
        assert 'File "app.py", line 42' in result
        assert "process(data)" in result

    def test_handles_chained_exceptions(self) -> None:
        tb = (
            "Traceback (most recent call last):\n"
            '  File "a.py", line 1, in f\n'
            "    g()\n"
            "KeyError: 'secret_key'\n"
            "\nDuring handling of the above exception:\n\n"
            "Traceback (most recent call last):\n"
            '  File "b.py", line 2, in h\n'
            "    raise RuntimeError(str(e))\n"
            "RuntimeError: secret_key\n"
        )
        result = _sanitize_traceback(tb)
        assert "KeyError: <redacted>" in result
        assert "RuntimeError: <redacted>" in result
        assert "secret_key" not in result

    def test_preserves_bare_exception_type(self) -> None:
        """Exception lines with no message stay intact."""
        tb = (
            "Traceback (most recent call last):\n"
            '  File "x.py", line 1, in f\n'
            "    raise StopIteration\n"
            "StopIteration\n"
        )
        result = _sanitize_traceback(tb)
        assert "StopIteration" in result

    def test_empty_input(self) -> None:
        assert _sanitize_traceback("") == ""
        assert _sanitize_traceback("No traceback here") == "No traceback here"


class TestStackTraceSanitizationInLogs:
    """Integration: production logs have sanitized traces, dev preserves them."""

    def test_production_logs_redact_exception_message(
        self,
        app: FastAPI,
        capture_logs: list[dict[str, object]],
    ) -> None:
        """Production mode redacts exception messages from stack traces."""
        mock_settings = type("S", (), {"environment": Environment.PRODUCTION})()
        with (
            patch("tta.api.errors.get_settings", return_value=mock_settings),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.get("/unhandled-pii")
        err_logs = [e for e in capture_logs if e.get("event") == "unhandled_error"]
        assert len(err_logs) == 1
        trace = str(err_logs[0]["stack_trace"])
        assert "Traceback" in trace
        assert "user@secret.com" not in trace
        assert "ValueError: <redacted>" in trace

    def test_development_logs_preserve_full_traceback(
        self,
        app: FastAPI,
        capture_logs: list[dict[str, object]],
    ) -> None:
        """Development mode preserves full exception messages for debugging."""
        mock_settings = type("S", (), {"environment": Environment.DEVELOPMENT})()
        with (
            patch("tta.api.errors.get_settings", return_value=mock_settings),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.get("/unhandled-pii")
        err_logs = [e for e in capture_logs if e.get("event") == "unhandled_error"]
        assert len(err_logs) == 1
        trace = str(err_logs[0]["stack_trace"])
        # Dev mode shows full message
        assert "user@secret.com" in trace
