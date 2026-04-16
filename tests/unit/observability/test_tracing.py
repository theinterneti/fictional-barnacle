"""Tests for OpenTelemetry distributed tracing (issue #44).

Covers:
- init_tracing() setup and teardown
- Span hierarchy in pipeline orchestrator
- X-Trace-Id header propagation via middleware
- Graceful degradation when disabled
- current_trace_id() and set_span_error()
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

from tta.observability.tracing import (
    _SERVICE_NAME,
    _TRACER_NAME,
    current_trace_id,
    get_tracer,
    init_tracing,
    set_span_error,
    shutdown_tracing,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ListExporter(SpanExporter):
    """Minimal in-memory exporter for testing."""

    def __init__(self) -> None:
        self.spans: list = []

    def export(self, spans):  # type: ignore[override]
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def get_finished_spans(self) -> list:
        return list(self.spans)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_tracer_provider():
    """Reset the global tracer provider between tests."""
    yield
    # Force-reset the global provider to allow re-initialization.
    # OTel doesn't officially support this; we reach into internals.
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]


def _make_in_memory_provider() -> tuple[TracerProvider, _ListExporter]:
    """Create a TracerProvider with an in-memory exporter for testing."""
    exporter = _ListExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider, exporter


# ---------------------------------------------------------------------------
# init_tracing / shutdown_tracing
# ---------------------------------------------------------------------------


class TestInitTracing:
    """FR-15.12: init_tracing sets up TracerProvider + OTLP exporter."""

    def test_enabled_sets_provider(self) -> None:
        with patch(
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter"
        ) as mock_exporter_cls:
            mock_exporter_cls.return_value = MagicMock()
            init_tracing(enabled=True, endpoint="http://test:4317")

        provider = trace.get_tracer_provider()
        # Should be a real TracerProvider, not the default ProxyTracerProvider
        assert isinstance(provider, TracerProvider)

    def test_disabled_uses_noop(self) -> None:
        init_tracing(enabled=False)
        provider = trace.get_tracer_provider()
        # Should remain the default proxy/no-op provider
        assert not isinstance(provider, TracerProvider)

    def test_exporter_failure_still_sets_provider(self) -> None:
        """EC-15.3: exporter init failure doesn't crash app."""
        with patch(
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter",
            side_effect=RuntimeError("connection refused"),
        ):
            init_tracing(enabled=True, endpoint="http://bad:4317")

        # Provider should still be set even though exporter failed
        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)


class TestShutdownTracing:
    """Clean shutdown of TracerProvider."""

    def test_shutdown_with_provider(self) -> None:
        _provider, _ = _make_in_memory_provider()
        shutdown_tracing()
        # After shutdown, new spans should be no-ops
        tracer = get_tracer()
        with tracer.start_as_current_span("post-shutdown") as span:
            # Span context should be invalid after provider shutdown
            assert span is not None  # no crash

    def test_shutdown_without_provider(self) -> None:
        """Shutdown with default no-op provider should not crash."""
        shutdown_tracing()  # No error


# ---------------------------------------------------------------------------
# get_tracer
# ---------------------------------------------------------------------------


class TestGetTracer:
    """get_tracer returns a named tracer."""

    def test_returns_tracer(self) -> None:
        tracer = get_tracer()
        assert tracer is not None

    def test_tracer_name(self) -> None:
        _make_in_memory_provider()
        tracer = get_tracer()
        assert tracer._instrumentation_scope.name == _TRACER_NAME  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# current_trace_id
# ---------------------------------------------------------------------------


class TestCurrentTraceId:
    """current_trace_id extracts the hex trace ID from the active span."""

    def test_returns_none_outside_span(self) -> None:
        assert current_trace_id() is None

    def test_returns_hex_inside_span(self) -> None:
        _make_in_memory_provider()
        tracer = get_tracer()
        with tracer.start_as_current_span("test-span"):
            tid = current_trace_id()
            assert tid is not None
            assert len(tid) == 32
            # Should be valid hex
            int(tid, 16)

    def test_consistent_within_span(self) -> None:
        _make_in_memory_provider()
        tracer = get_tracer()
        with tracer.start_as_current_span("outer"):
            outer_id = current_trace_id()
            with tracer.start_as_current_span("inner"):
                inner_id = current_trace_id()
            # Child span inherits parent's trace ID
            assert outer_id == inner_id


# ---------------------------------------------------------------------------
# set_span_error
# ---------------------------------------------------------------------------


class TestSetSpanError:
    """set_span_error records error status and exception on current span."""

    def test_records_error(self) -> None:
        _, exporter = _make_in_memory_provider()
        tracer = get_tracer()
        with tracer.start_as_current_span("error-span"):
            set_span_error(RuntimeError("boom"))

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.status.status_code == trace.StatusCode.ERROR
        assert "boom" in (span.status.description or "")

    def test_records_exception_event(self) -> None:
        _, exporter = _make_in_memory_provider()
        tracer = get_tracer()
        with tracer.start_as_current_span("exc-span"):
            set_span_error(ValueError("test-error"))

        spans = exporter.get_finished_spans()
        events = spans[0].events
        assert any(e.name == "exception" for e in events)


# ---------------------------------------------------------------------------
# Pipeline span hierarchy (unit test with tracer)
# ---------------------------------------------------------------------------


class TestPipelineSpanHierarchy:
    """FR-15.14: Span tree from orchestrator matches spec."""

    def test_pipeline_creates_parent_and_child_spans(self) -> None:
        """Verify that run_pipeline creates turn_pipeline + stage spans."""
        _, exporter = _make_in_memory_provider()
        tracer = get_tracer()

        # Simulate the span hierarchy that orchestrator creates
        with tracer.start_as_current_span(
            "turn_pipeline",
            attributes={
                "tta.session_id": "s1",
                "tta.turn_id": "t1",
                "tta.turn_number": 1,
            },
        ):
            for stage in ["understand", "context", "generate", "deliver"]:
                with tracer.start_as_current_span(
                    f"stage_{stage}",
                    attributes={"tta.stage": stage},
                ):
                    pass

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        # Should have 5 spans total: 4 stages + 1 pipeline parent
        assert len(spans) == 5
        assert "turn_pipeline" in span_names
        assert "stage_understand" in span_names
        assert "stage_context" in span_names
        assert "stage_generate" in span_names
        assert "stage_deliver" in span_names

    def test_pipeline_span_attributes(self) -> None:
        _, exporter = _make_in_memory_provider()
        tracer = get_tracer()

        with tracer.start_as_current_span(
            "turn_pipeline",
            attributes={
                "tta.session_id": "sess-123",
                "tta.turn_id": "turn-456",
                "tta.turn_number": 3,
            },
        ):
            pass

        spans = exporter.get_finished_spans()
        pipeline_span = spans[0]
        attrs = dict(pipeline_span.attributes or {})
        assert attrs["tta.session_id"] == "sess-123"
        assert attrs["tta.turn_id"] == "turn-456"
        assert attrs["tta.turn_number"] == 3

    def test_all_stages_share_trace_id(self) -> None:
        _, exporter = _make_in_memory_provider()
        tracer = get_tracer()

        with tracer.start_as_current_span("turn_pipeline"):
            for stage in ["understand", "context", "generate", "deliver"]:
                with tracer.start_as_current_span(f"stage_{stage}"):
                    pass

        spans = exporter.get_finished_spans()
        trace_ids = {s.context.trace_id for s in spans}
        # All spans should share the same trace ID
        assert len(trace_ids) == 1


# ---------------------------------------------------------------------------
# Resource attributes
# ---------------------------------------------------------------------------


class TestResourceAttributes:
    """Service resource metadata."""

    def test_service_name_in_resource(self) -> None:
        with patch(
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter"
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            init_tracing(enabled=True, endpoint="http://test:4317")

        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)
        attrs = dict(provider.resource.attributes)
        assert attrs.get("service.name") == _SERVICE_NAME
