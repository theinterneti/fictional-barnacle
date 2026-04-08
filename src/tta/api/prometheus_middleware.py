"""Prometheus instrumentation middleware for FastAPI.

Records HTTP request count, duration, and in-flight gauge.
Labels are low-cardinality: method, route pattern (not raw path), status code.
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from tta.observability.metrics import (
    HTTP_IN_FLIGHT,
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_TOTAL,
)


def _get_route_pattern(request: Request) -> str:
    """Extract the route pattern (e.g. /api/v1/games/{game_id}) from the request.

    Falls back to the raw path if no matching route is found.
    """
    app = request.app
    for route in app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", request.url.path)
    return "unmatched"


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record HTTP metrics for every request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        route = _get_route_pattern(request)
        status_code = 500

        HTTP_IN_FLIGHT.inc()
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            HTTP_IN_FLIGHT.dec()
            HTTP_REQUESTS_TOTAL.labels(
                method=method,
                route=route,
                status=str(status_code),
            ).inc()
            HTTP_REQUEST_DURATION.labels(
                method=method,
                route=route,
            ).observe(duration)
