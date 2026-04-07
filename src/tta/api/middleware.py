"""Request-scoped middleware for TTA API."""

import uuid

from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import Response

from tta.logging import bind_correlation_id, clear_contextvars


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Ensure every request/response carries an X-Request-ID header.

    If the incoming request includes the header, it is preserved;
    otherwise a new UUID is generated.  The ID is also bound to
    structlog context vars for correlated logging.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        bind_correlation_id(request_id)
        try:
            response = await call_next(request)
        finally:
            clear_contextvars()
        response.headers["x-request-id"] = request_id
        return response
