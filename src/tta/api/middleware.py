"""Request-scoped middleware for TTA API."""

import time
import uuid

import structlog
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import Response

from tta.logging import bind_context, bind_correlation_id, clear_contextvars

log = structlog.get_logger()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Ensure every request/response carries correlation headers.

    Propagated IDs:
    - X-Request-ID → correlation_id (generated if absent)
    - X-Trace-Id → trace_id (passed through if present)

    All IDs are bound to structlog context vars for correlated logging
    and added as response headers.  Request duration is logged on
    completion (S15 §7).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        trace_id = request.headers.get("x-trace-id")

        request.state.request_id = request_id
        bind_correlation_id(request_id)

        # Bind trace_id when provided by upstream (e.g. OTel gateway).
        if trace_id:
            bind_context(trace_id=trace_id)

        start = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            log.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
            clear_contextvars()

        response.headers["x-request-id"] = request_id
        if trace_id:
            response.headers["x-trace-id"] = trace_id
        return response
