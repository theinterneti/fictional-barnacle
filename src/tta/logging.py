"""Structured logging setup with JSON output and privacy filtering."""

import structlog

from tta.config import Settings

# Fields whose names (or partial names) trigger redaction.
REDACTED_FIELDS = {
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
}


def _privacy_filter(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: dict,  # type: ignore[type-arg]
) -> dict:  # type: ignore[type-arg]
    """Redact sensitive fields from log entries."""
    for key in list(event_dict.keys()):
        if any(sensitive in key.lower() for sensitive in REDACTED_FIELDS):
            event_dict[key] = "[REDACTED]"
    return event_dict


def configure_logging(settings: Settings | None = None) -> None:
    """Configure structlog with JSON output, timestamps, and
    privacy filter.
    """
    if settings is None:
        # Lazy import to avoid circular dependency.
        from tta.config import get_settings

        settings = get_settings()

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
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
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a pre-bound logger with service context."""
    return structlog.get_logger(name, service="tta")


def bind_correlation_id(correlation_id: str) -> None:
    """Bind a correlation ID to structlog context vars for the
    current request.
    """
    structlog.contextvars.bind_contextvars(
        correlation_id=correlation_id,
    )


def clear_contextvars() -> None:
    """Clear request-scoped context vars."""
    structlog.contextvars.clear_contextvars()
