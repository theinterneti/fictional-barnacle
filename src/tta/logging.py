"""Structured logging setup with JSON output and privacy filtering.

Provides request-scoped correlation ID propagation via structlog
context vars. All IDs (correlation_id, session_id, turn_id) flow
through the same contextvars mechanism for consistent log output.

Spec refs: S15 §7 (correlation), S17 §3 (privacy filtering).
"""

import logging
from typing import Any

import structlog

from tta.config import Settings

# Fields whose names (or partial names) trigger redaction.
REDACTED_FIELDS = frozenset(
    {
        "password",
        "token",
        "secret",
        "authorization",
        "cookie",
    }
)

# Content fields that contain PII and must never appear at INFO+.
# These are only logged when log_sensitive=True (dev mode).
PII_CONTENT_FIELDS = frozenset(
    {
        "player_input",
        "email",
        "phone",
        "address",
        "ip_address",
        "display_name",
        "player_name",
        "handle",
    }
)

# Module-level flag set by configure_logging.
_log_sensitive: bool = False


def _privacy_filter(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Redact sensitive fields from log entries.

    Two-tier filtering (FR-15.6, FR-17.5):
    1. Credential fields (REDACTED_FIELDS) — always redacted.
    2. PII content fields (PII_CONTENT_FIELDS) — redacted unless
       log_sensitive=True (dev mode only, FR-15.7).
    """
    for key in list(event_dict.keys()):
        key_lower = key.lower()
        if any(sensitive in key_lower for sensitive in REDACTED_FIELDS):
            event_dict[key] = "[REDACTED]"
        elif not _log_sensitive and key_lower in PII_CONTENT_FIELDS:
            event_dict[key] = "[PII_REDACTED]"
    return event_dict


def configure_logging(settings: Settings | None = None) -> None:
    """Configure structlog with JSON output, timestamps, and
    privacy filter.

    FR-15.7: log_sensitive is forced False in staging/production.
    """
    global _log_sensitive  # noqa: PLW0603

    if settings is None:
        from tta.config import get_settings

        settings = get_settings()

    # FR-15.7: log_sensitive only allowed in development
    if settings.log_sensitive and settings.environment.value != "development":
        _log_sensitive = False
        logging.getLogger(__name__).warning(
            "log_sensitive=True ignored in %s environment",
            settings.environment.value,
        )
    else:
        _log_sensitive = settings.log_sensitive

    # Apply log_level to stdlib logging so structlog respects it
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level.value),
        force=True,
    )

    processors: list[structlog.types.Processor] = [
        structlog.stdlib.filter_by_level,
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        _privacy_filter,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    configure_logging._settings = settings  # type: ignore[attr-defined]


# Module-level ref for get_logger to access configured environment
configure_logging._settings = None  # type: ignore[attr-defined]


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a pre-bound logger with service and environment context."""
    bindings: dict[str, str] = {"service": "tta"}
    settings = configure_logging._settings  # type: ignore[attr-defined]
    if settings is not None:
        bindings["environment"] = settings.environment.value
    return structlog.get_logger(name, **bindings)


def bind_correlation_id(correlation_id: str) -> None:
    """Bind a correlation ID to structlog context vars for the
    current request.
    """
    structlog.contextvars.bind_contextvars(
        correlation_id=correlation_id,
    )


def bind_context(**kwargs: Any) -> None:
    """Bind arbitrary key-value pairs to structlog context vars.

    Typical usage: ``bind_context(session_id=..., turn_id=...)``.
    Values are converted to str to ensure JSON-serializable output.
    ``None`` values are silently skipped.
    """
    filtered = {k: str(v) for k, v in kwargs.items() if v is not None}
    if filtered:
        structlog.contextvars.bind_contextvars(**filtered)


def get_correlation_id() -> str | None:
    """Return the current correlation_id from context, or None."""
    return structlog.contextvars.get_contextvars().get("correlation_id")


def clear_contextvars() -> None:
    """Clear request-scoped context vars."""
    structlog.contextvars.clear_contextvars()
