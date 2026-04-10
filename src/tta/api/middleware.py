"""Request-scoped middleware for TTA API.

Uses pure ASGI middleware (not BaseHTTPMiddleware) to avoid event loop
conflicts with asyncpg and to preserve SSE streaming fidelity.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
import uuid

import structlog
from starlette.datastructures import State
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tta.logging import bind_context, bind_correlation_id, clear_contextvars
from tta.observability.tracing import current_trace_id
from tta.resilience.anti_abuse import AbuseDetector, AbusePattern
from tta.resilience.rate_limiter import (
    EndpointGroup,
    InMemoryRateLimiter,
    RateLimiter,
    RateLimitResult,
)

log = structlog.get_logger()


class RequestIDMiddleware:
    """Ensure every request/response carries correlation headers (pure ASGI).

    Propagated IDs:
    - X-Request-ID → correlation_id (generated if absent)
    - X-Trace-Id → trace_id (from OTel span context, or upstream header)

    All IDs are bound to structlog context vars for correlated logging
    and added as response headers.  Request duration is logged on
    completion (S15 §7).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        scope.setdefault("state", State())
        request = Request(scope)

        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        bind_correlation_id(request_id)

        trace_id = current_trace_id() or request.headers.get("x-trace-id") or request_id
        bind_context(trace_id=trace_id)

        start = time.monotonic()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                # Inject correlation headers into the response
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                headers.append((b"x-trace-id", trace_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            log.info(
                "http_request",
                method=request.method,
                path=str(request.url.path),
                status_code=status_code,
                duration_ms=duration_ms,
            )
            clear_contextvars()


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
                "code": "rate_limited",
                "message": f"Too many requests. Retry after {result.retry_after}s.",
                "details": None,
                "correlation_id": correlation_id,
                "retry_after_seconds": result.retry_after,
            }
        },
        headers=headers,
    )


def _build_cooldown_response(
    remaining: int, pattern: str, correlation_id: str
) -> JSONResponse:
    """Return a 429 for an active abuse-detection cooldown (FR-25.08)."""
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "rate_limited",
                "message": (
                    "Too many requests. Temporarily blocked due to suspicious activity."
                ),
                "details": {"reason": pattern},
                "correlation_id": correlation_id,
                "retry_after_seconds": remaining,
            }
        },
        headers={
            "Retry-After": str(remaining),
            "X-RateLimit-Limit": "0",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(math.ceil(time.time() + remaining)),
        },
    )


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


class RateLimitMiddleware:
    """Sliding-window rate limiting with anti-abuse detection (S25 §3, pure ASGI).

    Order of operations per request:
    1. Classify endpoint group (exempt → pass through)
    2. Check abuse-detection cooldown by IP (blocked → 429 immediately)
    3. Run sliding-window rate limit check
    4. If rejected: record RAPID_FIRE violation, return 429
    5. Forward to app, then inspect response status:
       - 401 → record CREDENTIAL_STUFFING violation (any endpoint)
    6. Add rate-limit headers to every response (FR-25.04)
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        settings = request.app.state.settings

        # Bypass when disabled
        if not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        group = _classify_endpoint(request.url.path, request.method)
        if group is None:
            await self.app(scope, receive, send)
            return

        ip = request.client.host if request.client else "unknown"
        abuse_identity = f"ip:{ip}"
        correlation_id = getattr(request.state, "request_id", "unknown")

        # --- Anti-abuse cooldown check (S25 §3.5, FR-25.10) ---
        detector: AbuseDetector | None = getattr(
            request.app.state, "abuse_detector", None
        )
        if detector is not None:
            try:
                cooldown = await detector.check_cooldown(abuse_identity)
                if cooldown.active:
                    log.warning(
                        "abuse_cooldown_blocked",
                        ip_address=ip,
                        pattern=cooldown.pattern,
                        remaining=cooldown.remaining_seconds,
                    )
                    resp = _build_cooldown_response(
                        cooldown.remaining_seconds,
                        cooldown.pattern or "unknown",
                        correlation_id,
                    )
                    await resp(scope, receive, send)
                    return
            except Exception:
                log.warning("abuse_detector_error", exc_info=True)

        # --- Rate limit check ---
        limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
        if limiter is None:
            limiter = InMemoryRateLimiter()
            request.app.state.rate_limiter = limiter

        token = _extract_session_token(request)
        key, is_player = _rate_limit_key(token, request, group)

        limit = _group_limit(settings, group)
        if not is_player:
            limit *= 2  # per-IP gets 2× headroom

        try:
            result = await limiter.check(key, limit, 60)
        except Exception:
            log.warning("rate_limiter_error", key=key, group=group, exc_info=True)
            await self.app(scope, receive, send)
            return

        if not result.allowed:
            log.warning(
                "rate_limited",
                key=key,
                group=group,
                limit=limit,
                retry_after=result.retry_after,
            )
            if detector is not None:
                try:
                    vr = await detector.record_violation(
                        abuse_identity, AbusePattern.RAPID_FIRE
                    )
                    if vr.cooldown_applied:
                        log.warning(
                            "abuse_pattern_detected",
                            pattern=AbusePattern.RAPID_FIRE,
                            ip_address=ip,
                            violation_count=vr.violation_count,
                            cooldown_seconds=vr.cooldown_seconds,
                            escalated=vr.escalated,
                        )
                except Exception:
                    log.warning("abuse_record_error", exc_info=True)

            resp = _build_429_response(result, correlation_id)
            await resp(scope, receive, send)
            return

        # --- Forward request to app with header injection ---
        response_status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
                # Inject rate-limit headers
                headers = list(message.get("headers", []))
                for name, value in _rate_limit_headers(result).items():
                    headers.append((name.lower().encode(), value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)

        # Detect auth failures for credential-stuffing pattern (FR-25.10)
        if response_status == 401 and detector is not None:
            try:
                vr = await detector.record_violation(
                    abuse_identity, AbusePattern.CREDENTIAL_STUFFING
                )
                if vr.cooldown_applied:
                    log.warning(
                        "abuse_pattern_detected",
                        pattern=AbusePattern.CREDENTIAL_STUFFING,
                        ip_address=ip,
                        violation_count=vr.violation_count,
                        cooldown_seconds=vr.cooldown_seconds,
                        escalated=vr.escalated,
                    )
            except Exception:
                log.warning("abuse_record_error", exc_info=True)


# ---------------------------------------------------------------------------
# Latency budget middleware (S28 FR-28.18/19)
# ---------------------------------------------------------------------------

_EXEMPT_PREFIXES = ("/metrics", "/api/v1/health", "/admin/health")


class LatencyBudgetMiddleware:
    """Track request latency and warn/abort when budget is exceeded.

    Pure ASGI middleware — follows the same pattern as
    RequestIDMiddleware.

    - Adds ``X-Latency-Budget-Remaining-Ms`` header to every response.
    - Logs a warning when ``latency_budget_warn_ms`` is exceeded.
    - Returns 503 when ``latency_budget_abort_ms`` is exceeded (only
      before response headers have been sent).

    Settings are read from ``scope["app"].state.settings``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path

        # Exempt health / metrics endpoints from budget enforcement.
        for prefix in _EXEMPT_PREFIXES:
            if path.startswith(prefix):
                await self.app(scope, receive, send)
                return

        settings = request.app.state.settings
        warn_ms: float = settings.latency_budget_warn_ms
        abort_ms: float = settings.latency_budget_abort_ms

        start = time.monotonic()
        headers_sent = False

        async def send_wrapper(message: Message) -> None:
            nonlocal headers_sent
            elapsed_ms = (time.monotonic() - start) * 1000

            if message["type"] == "http.response.start":
                headers_sent = True
                remaining = max(0, abort_ms - elapsed_ms)
                headers = list(message.get("headers", []))
                headers.append(
                    (
                        b"x-latency-budget-remaining-ms",
                        str(int(remaining)).encode(),
                    )
                )
                message = {**message, "headers": headers}

                if elapsed_ms >= warn_ms:
                    log.warning(
                        "latency_budget_warn",
                        path=path,
                        elapsed_ms=round(elapsed_ms, 1),
                        warn_ms=warn_ms,
                    )
            await send(message)

        try:
            async with asyncio.timeout(abort_ms / 1000):
                await self.app(scope, receive, send_wrapper)
        except TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            if not headers_sent:
                log.error(
                    "latency_budget_abort",
                    path=path,
                    elapsed_ms=round(elapsed_ms, 1),
                    abort_ms=abort_ms,
                )
                resp = JSONResponse(
                    status_code=503,
                    content={
                        "error": {
                            "code": "latency_budget_exceeded",
                            "message": "Request exceeded latency budget.",
                            "details": {
                                "elapsed_ms": round(elapsed_ms, 1),
                                "budget_ms": abort_ms,
                            },
                        }
                    },
                )
                await resp(scope, receive, send)
            else:
                log.warning(
                    "latency_budget_exceeded_headers_sent",
                    path=path,
                    elapsed_ms=round(elapsed_ms, 1),
                    abort_ms=abort_ms,
                )
