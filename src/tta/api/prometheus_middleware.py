"""Prometheus instrumentation middleware for FastAPI.

Records HTTP request count, duration, and in-flight gauge.
Labels are low-cardinality: method, route pattern (not raw path), status code.

Uses pure ASGI middleware (not BaseHTTPMiddleware) to avoid event loop
conflicts with asyncpg and to preserve SSE streaming fidelity.
"""

import time

from starlette.requests import Request
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


class PrometheusMiddleware:
    """Record HTTP metrics for every request (pure ASGI)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        method = request.method
        route = _get_route_pattern(request)
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        HTTP_IN_FLIGHT.inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
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
