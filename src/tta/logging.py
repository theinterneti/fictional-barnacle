"""Structured logging setup with JSON output and privacy filtering."""

import logging

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
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
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


def clear_contextvars() -> None:
    """Clear request-scoped context vars."""
    structlog.contextvars.clear_contextvars()
