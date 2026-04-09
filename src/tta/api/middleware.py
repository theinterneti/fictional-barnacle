"""Request-scoped middleware for TTA API."""

from __future__ import annotations

import hashlib
import math
import time
import uuid

import structlog
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from tta.logging import bind_context, bind_correlation_id, clear_contextvars
from tta.observability.tracing import current_trace_id
from tta.resilience.rate_limiter import (
    EndpointGroup,
    InMemoryRateLimiter,
    RateLimiter,
    RateLimitResult,
)

log = structlog.get_logger()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Ensure every request/response carries correlation headers.

    Propagated IDs:
    - X-Request-ID → correlation_id (generated if absent)
    - X-Trace-Id → trace_id (from OTel span context, or upstream header)

    All IDs are bound to structlog context vars for correlated logging
    and added as response headers.  Request duration is logged on
    completion (S15 §7).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())

        request.state.request_id = request_id
        bind_correlation_id(request_id)

        # Bind trace_id early so the http_request log includes it.
        trace_id = current_trace_id() or request.headers.get("x-trace-id")
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


# ---------------------------------------------------------------------------
# Rate limit middleware (S25)
# ---------------------------------------------------------------------------

# Path patterns for endpoint group classification
_TURN_SUFFIX = "/turns"
_STREAM_SUFFIX = "/stream"
_PLAYERS_PATH = "/api/v1/players"
_HEALTH_PREFIX = "/api/v1/health"
_METRICS_PREFIX = "/metrics"


def _classify_endpoint(path: str, method: str) -> EndpointGroup | None:
    """Map a request to its rate-limit endpoint group.

    Returns ``None`` for exempt endpoints (health, metrics).
    """
    if method == "OPTIONS":
        return None  # CORS preflights are always exempt
    if path.startswith(_HEALTH_PREFIX) or path.startswith(_METRICS_PREFIX):
        return None  # exempt
    if method == "POST" and path.endswith(_TURN_SUFFIX):
        return EndpointGroup.TURNS
    if path.endswith(_STREAM_SUFFIX):
        return EndpointGroup.SSE
    # Unauthenticated player registration
    if method == "POST" and path.rstrip("/") == _PLAYERS_PATH:
        return EndpointGroup.AUTH
    return EndpointGroup.GAME_MGMT


def _extract_session_token(request: Request) -> str | None:
    """Extract session token from cookie or Authorization header.

    Mirrors the logic in ``tta.api.deps._extract_token`` so the
    middleware can identify users without a database lookup.
    """
    token = request.cookies.get("tta_session")
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _rate_limit_key(
    token: str | None, request: Request, group: EndpointGroup
) -> tuple[str, bool]:
    """Build the rate-limit key and return (key, is_player).

    Per-player keys use the SHA-256 prefix of the session token to avoid
    storing raw tokens in Redis.

    NOTE(v1): Token is not validated here — an attacker can rotate tokens
    to bypass per-player limits.  Anti-abuse detection (S25 §4) mitigates
    this.  A future version should key on validated player_id.
    """
    if token:
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
        return f"rl:player:{token_hash}:{group}", True
    ip = request.client.host if request.client else "unknown"
    return f"rl:ip:{ip}:{group}", False


def _rate_limit_headers(result: RateLimitResult) -> dict[str, str]:
    """Build X-RateLimit-* headers from a check result."""
    return {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(max(0, result.remaining)),
        "X-RateLimit-Reset": str(math.ceil(result.reset_at)),
    }


def _build_429_response(result: RateLimitResult, correlation_id: str) -> JSONResponse:
    """Return a 429 response using the S23 error envelope."""
    headers = _rate_limit_headers(result)
    headers["Retry-After"] = str(result.retry_after)

    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMITED",
                "message": "Too many requests. Please try again later.",
                "details": None,
                "correlation_id": correlation_id,
                "retry_after_seconds": result.retry_after,
            }
        },
        headers=headers,
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiting per S25 §3.

    Checks per-player (session token) or per-IP limits depending on
    whether an authentication token is present.  Rate-limit response
    headers are added to ALL responses (FR-25.04).  Rejected requests
    are *not* counted against the window (FR-25.09).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        settings = request.app.state.settings

        # Bypass when disabled
        if not settings.rate_limit_enabled:
            return await call_next(request)

        group = _classify_endpoint(request.url.path, request.method)
        if group is None:
            return await call_next(request)

        # Resolve limiter — prefer configured, fallback to in-memory
        limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
        if limiter is None:
            # Lazy-create a persistent fallback so limits actually accumulate
            limiter = InMemoryRateLimiter()
            request.app.state.rate_limiter = limiter

        # Determine identity and per-group limit
        token = _extract_session_token(request)
        key, is_player = _rate_limit_key(token, request, group)

        limit = self._group_limit(settings, group)
        if not is_player:
            limit *= 2  # per-IP gets 2× headroom

        try:
            result = await limiter.check(key, limit, 60)
        except Exception:
            # Fail-open: allow the request if the limiter is broken
            log.warning("rate_limiter_error", key=key, group=group)
            return await call_next(request)

        if not result.allowed:
            correlation_id = getattr(request.state, "request_id", "unknown")
            log.warning(
                "rate_limited",
                key=key,
                group=group,
                limit=limit,
                retry_after=result.retry_after,
            )
            return _build_429_response(result, correlation_id)

        response = await call_next(request)

        # Add rate-limit headers to every successful response (FR-25.04)
        for name, value in _rate_limit_headers(result).items():
            response.headers[name] = value

        return response

    @staticmethod
    def _group_limit(settings: object, group: EndpointGroup) -> int:
        """Look up the per-minute limit for an endpoint group."""
        mapping = {
            EndpointGroup.TURNS: "rate_limit_turns_per_minute",
            EndpointGroup.GAME_MGMT: "rate_limit_game_mgmt_per_minute",
            EndpointGroup.AUTH: "rate_limit_auth_per_minute",
            EndpointGroup.SSE: "rate_limit_sse_per_minute",
        }
        attr = mapping.get(group, "rate_limit_game_mgmt_per_minute")
        return int(getattr(settings, attr, 30))
