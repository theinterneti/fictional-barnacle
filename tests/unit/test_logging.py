"""Tests for TTA structured logging setup."""

import structlog

from tta.config import Settings
from tta.logging import (
    PII_CONTENT_FIELDS,
    REDACTED_FIELDS,
    _privacy_filter,
    bind_context,
    bind_correlation_id,
    clear_contextvars,
    configure_logging,
    get_correlation_id,
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

    def test_redacts_player_input_by_default(self) -> None:
        """PII content fields redacted when log_sensitive=False."""
        configure_logging(_make_settings(log_sensitive=False))
        event: dict[str, object] = {
            "event": "turn",
            "player_input": "I want to explore the cave",
        }
        result = _privacy_filter(None, "info", event)  # type: ignore[arg-type]
        assert result["player_input"] == "[PII_REDACTED]"

    def test_allows_player_input_when_sensitive(self) -> None:
        """PII content fields pass through when log_sensitive=True."""
        configure_logging(_make_settings(log_sensitive=True))
        event: dict[str, object] = {
            "event": "turn",
            "player_input": "I want to explore the cave",
        }
        result = _privacy_filter(None, "info", event)  # type: ignore[arg-type]
        assert result["player_input"] == "I want to explore the cave"

    def test_redacts_all_pii_content_fields(self) -> None:
        """All PII_CONTENT_FIELDS are redacted by default."""
        configure_logging(_make_settings(log_sensitive=False))
        event: dict[str, object] = {
            "event": "test",
            **{field: f"val-{field}" for field in PII_CONTENT_FIELDS},
        }
        result = _privacy_filter(None, "info", event)  # type: ignore[arg-type]
        for field in PII_CONTENT_FIELDS:
            assert result[field] == "[PII_REDACTED]", f"{field} not redacted"

    def test_credential_fields_always_redacted(self) -> None:
        """Credential fields redacted even with log_sensitive=True."""
        configure_logging(_make_settings(log_sensitive=True))
        event: dict[str, object] = {
            "event": "test",
            **{field: f"val-{field}" for field in REDACTED_FIELDS},
        }
        result = _privacy_filter(None, "info", event)  # type: ignore[arg-type]
        for field in REDACTED_FIELDS:
            assert result[field] == "[REDACTED]", f"{field} not redacted"


class TestConfigureLogging:
    """configure_logging applies structlog configuration."""

    def test_does_not_raise_json(self) -> None:
        settings = _make_settings(log_format="json")
        configure_logging(settings)

    def test_does_not_raise_console(self) -> None:
        settings = _make_settings(log_format="console")
        configure_logging(settings)

    def test_log_sensitive_defaults_false(self) -> None:
        settings = _make_settings()
        assert settings.log_sensitive is False


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

    def test_get_correlation_id_returns_bound_value(self) -> None:
        clear_contextvars()
        bind_correlation_id("req-99")
        assert get_correlation_id() == "req-99"
        clear_contextvars()

    def test_get_correlation_id_returns_none_when_unset(self) -> None:
        clear_contextvars()
        assert get_correlation_id() is None


class TestBindContext:
    """bind_context binds multiple IDs to structlog context."""

    def test_binds_multiple_ids(self) -> None:
        clear_contextvars()
        bind_context(
            session_id="sess-1",
            turn_id="turn-2",
            correlation_id="req-3",
        )
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["session_id"] == "sess-1"
        assert ctx["turn_id"] == "turn-2"
        assert ctx["correlation_id"] == "req-3"
        clear_contextvars()

    def test_skips_none_values(self) -> None:
        clear_contextvars()
        bind_context(session_id="sess-1", turn_id=None)
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["session_id"] == "sess-1"
        assert "turn_id" not in ctx
        clear_contextvars()

    def test_converts_uuid_to_str(self) -> None:
        from uuid import UUID

        clear_contextvars()
        test_uuid = UUID("12345678-1234-5678-1234-567812345678")
        bind_context(session_id=test_uuid)
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["session_id"] == str(test_uuid)
        clear_contextvars()

    def test_empty_kwargs_is_noop(self) -> None:
        clear_contextvars()
        bind_context()
        ctx = structlog.contextvars.get_contextvars()
        assert ctx == {}

    def test_all_none_kwargs_is_noop(self) -> None:
        clear_contextvars()
        bind_context(a=None, b=None)
        ctx = structlog.contextvars.get_contextvars()
        assert ctx == {}
