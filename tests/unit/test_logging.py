"""Tests for TTA structured logging setup."""

import structlog

from tta.config import Settings
from tta.logging import (
    _privacy_filter,
    bind_correlation_id,
    clear_contextvars,
    configure_logging,
    get_logger,
)


def _make_settings(**overrides: object) -> Settings:
    """Build a Settings with required fields filled in."""
    defaults: dict[str, object] = {
        "database_url": "postgresql://u:p@localhost/tta",
        "neo4j_password": "test-secret",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestPrivacyFilter:
    """_privacy_filter redacts sensitive fields."""

    def test_redacts_password(self) -> None:
        event: dict[str, object] = {
            "event": "login",
            "password": "hunter2",
        }
        result = _privacy_filter(None, "info", event)  # type: ignore[arg-type]
        assert result["password"] == "[REDACTED]"
        assert result["event"] == "login"

    def test_redacts_partial_match(self) -> None:
        event: dict[str, object] = {
            "event": "request",
            "auth_token": "abc123",
        }
        result = _privacy_filter(None, "info", event)  # type: ignore[arg-type]
        assert result["auth_token"] == "[REDACTED]"

    def test_leaves_safe_fields(self) -> None:
        event: dict[str, object] = {
            "event": "startup",
            "host": "localhost",
            "port": 8000,
        }
        result = _privacy_filter(None, "info", event)  # type: ignore[arg-type]
        assert result["host"] == "localhost"
        assert result["port"] == 8000


class TestConfigureLogging:
    """configure_logging applies structlog configuration."""

    def test_does_not_raise_json(self) -> None:
        settings = _make_settings(log_format="json")
        configure_logging(settings)

    def test_does_not_raise_console(self) -> None:
        settings = _make_settings(log_format="console")
        configure_logging(settings)


class TestGetLogger:
    """get_logger returns a bound logger with service context."""

    def test_returns_bound_logger(self) -> None:
        configure_logging(_make_settings())
        log = get_logger("test.module")
        # get_logger returns a lazy proxy; bind() resolves it
        # to the configured BoundLogger wrapper class.
        bound = log.bind()
        assert isinstance(bound, structlog.stdlib.BoundLogger)

    def test_logger_has_service_binding(self) -> None:
        configure_logging(_make_settings())
        log = get_logger("test.module")
        # _context holds the initial bindings on BoundLogger
        ctx = log._context  # type: ignore[attr-defined]
        assert ctx.get("service") == "tta"


class TestCorrelationId:
    """bind_correlation_id / clear_contextvars manage context."""

    def test_bind_and_clear(self) -> None:
        configure_logging(_make_settings())
        clear_contextvars()

        bind_correlation_id("req-42")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["correlation_id"] == "req-42"

        clear_contextvars()
        ctx = structlog.contextvars.get_contextvars()
        assert "correlation_id" not in ctx
