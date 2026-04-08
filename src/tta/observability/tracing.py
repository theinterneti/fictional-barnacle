"""OpenTelemetry distributed tracing for TTA.

Provides:
- ``init_tracing()``: set up the TracerProvider + OTLP exporter
- ``get_tracer()``: convenience accessor for the TTA tracer
- ``shutdown_tracing()``: flush and shut down the provider

Degrades silently when disabled or when the collector is unreachable
(EC-15.3).  100 % sampling for v1 (FR-15.12).
"""

from __future__ import annotations

import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import StatusCode

_log = structlog.get_logger()
_SERVICE_NAME = "tta-api"
_SERVICE_VERSION = "0.1.0"
_TRACER_NAME = "tta"


def init_tracing(
    *,
    enabled: bool = True,
    endpoint: str = "http://localhost:4317",
) -> None:
    """Initialise the OTel TracerProvider and OTLP exporter.

    When *enabled* is ``False`` the default no-op provider remains
    active so all ``tracer.start_as_current_span`` calls become no-ops.
    """
    if not enabled:
        _log.info("otel_tracing_disabled")
        return

    resource = Resource.create(
        {
            "service.name": _SERVICE_NAME,
            "service.version": _SERVICE_VERSION,
        }
    )
    provider = TracerProvider(resource=resource)

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    except Exception:
        _log.warning("otel_exporter_init_failed", endpoint=endpoint, exc_info=True)

    trace.set_tracer_provider(provider)
    _log.info("otel_tracing_enabled", endpoint=endpoint)


def get_tracer() -> trace.Tracer:
    """Return the TTA application tracer."""
    return trace.get_tracer(_TRACER_NAME)


def current_trace_id() -> str | None:
    """Return the current OTel trace-id as a hex string, or *None*."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.trace_id:
        return format(ctx.trace_id, "032x")
    return None


def set_span_error(error: Exception) -> None:
    """Record an exception on the current span."""
    span = trace.get_current_span()
    span.set_status(StatusCode.ERROR, str(error))
    span.record_exception(error)


def shutdown_tracing() -> None:
    """Flush and shut down the tracer provider."""
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()
        _log.info("otel_tracing_shutdown")
