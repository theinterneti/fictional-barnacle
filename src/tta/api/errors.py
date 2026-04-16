"""Application error types and exception handlers (S23 §3.1, plan §7)."""

from __future__ import annotations

import re
import traceback
from typing import TYPE_CHECKING

import structlog
from fastapi.responses import JSONResponse

from tta.config import Environment, get_settings
from tta.errors import CATEGORY_STATUS, ErrorCategory

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError


def _request_context(request: Request) -> dict[str, str]:
    """Extract structured log context from a request (FR-23.06).

    Returns IDs only — never data values — to satisfy FR-23.08.
    """
    ctx: dict[str, str] = {
        "request_method": request.method,
        "request_path": request.url.path,
    }
    state = request.state
    if rid := getattr(state, "request_id", None):
        ctx["correlation_id"] = rid
    if pid := getattr(state, "player_id", None):
        ctx["player_id"] = str(pid)
    else:
        ctx["player_id"] = "anonymous"
    if gid := getattr(state, "game_id", None):
        ctx["game_id"] = str(gid)
    if tid := getattr(state, "turn_id", None):
        ctx["turn_id"] = str(tid)
    return ctx


class AppError(Exception):
    """Application-level error with category-derived HTTP status (S23 §3.1).

    The ``category`` determines the HTTP status code via CATEGORY_STATUS.
    ``code`` is a machine-readable identifier (e.g. "GAME_NOT_FOUND").
    ``retry_after_seconds`` is included in the envelope and Retry-After
    header when set (mandatory for RATE_LIMITED per S25).
    """

    def __init__(
        self,
        category: ErrorCategory,
        code: str,
        message: str,
        details: dict | None = None,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.category = category
        self.status_code = CATEGORY_STATUS[category]
        self.code = code
        self.message = message
        self.details = details
        self.retry_after_seconds = retry_after_seconds


def _build_envelope(
    code: str,
    message: str,
    correlation_id: str,
    details: dict | None = None,
    retry_after_seconds: int | None = None,
) -> dict:
    """Build the standard S23 error envelope (FR-23.02)."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "correlation_id": correlation_id,
            "retry_after_seconds": retry_after_seconds,
        }
    }


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handle known application errors with the S23 envelope."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger = structlog.get_logger()

    # FR-23.06: structured error log
    logger.warning(
        "app_error",
        error_code=exc.code,
        error_category=exc.category.value,
        status_code=exc.status_code,
        **_request_context(request),
    )

    headers: dict[str, str] = {}
    if exc.retry_after_seconds is not None:
        headers["Retry-After"] = str(exc.retry_after_seconds)
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_envelope(
            code=exc.code,
            message=exc.message,
            correlation_id=request_id,
            details=exc.details,
            retry_after_seconds=exc.retry_after_seconds,
        ),
        headers=headers or None,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic/FastAPI validation errors (stays 422)."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger = structlog.get_logger()

    # FR-23.06: structured warning log
    logger.warning(
        "validation_error",
        error_code="VALIDATION_ERROR",
        error_category="input_invalid",
        status_code=422,
        **_request_context(request),
    )

    # Pydantic V2 errors() can contain non-serializable ctx values
    # (e.g. ValueError objects). Allowlist safe scalar ctx keys only.
    _SAFE_CTX_KEYS = {
        "limit_value",
        "min_length",
        "max_length",
        "expected",
        "ge",
        "le",
        "gt",
        "lt",
    }

    # Keys that may contain user-submitted values (PII risk).
    _STRIP_KEYS = {"input", "url"}

    def _clean_error(e: dict) -> dict:
        out = {k: v for k, v in e.items() if k not in ("ctx", *_STRIP_KEYS)}
        ctx = e.get("ctx")
        if isinstance(ctx, dict):
            safe = {
                k: v
                for k, v in ctx.items()
                if k in _SAFE_CTX_KEYS and isinstance(v, (int, float, str, bool))
            }
            if safe:
                out["ctx"] = safe
        return out

    safe_errors = [_clean_error(e) for e in exc.errors()]
    return JSONResponse(
        status_code=422,
        content=_build_envelope(
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            correlation_id=request_id,
            details={"errors": safe_errors},
        ),
    )


# Matches exception lines in a Python traceback, e.g.
#   "ValueError: some user data here"
#   "anyio.EndOfStream: ..."
#   "StopIteration: ..."
# Keeps the exception type, replaces the message with "<redacted>".
# Matches any "TypeName: message" line that is NOT a standard boilerplate
# prefix (Traceback, File, During handling, The above exception, etc.).
_EXC_LINE_RE = re.compile(
    r"^(?!Traceback |File |During handling|The above exception)(\w[\w.]*):[ \t].+$",
    re.MULTILINE,
)


def _sanitize_traceback(tb: str) -> str:
    """Strip exception messages from a traceback string.

    Keeps frame locations (file/line/function) intact for debugging
    but replaces exception messages that may contain user data.
    """
    return _EXC_LINE_RE.sub(r"\1: <redacted>", tb)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected errors — log traceback, return safe response (FR-23.04)."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger = structlog.get_logger()

    settings = get_settings()

    # FR-23.06 + FR-23.07: structured ERROR log with exception details.
    # In production, strip exception *messages* from the traceback to
    # prevent PII that propagated into the error from reaching logs.
    raw_tb = traceback.format_exc()
    if settings.environment != Environment.DEVELOPMENT:
        raw_tb = _sanitize_traceback(raw_tb)

    logger.error(
        "unhandled_error",
        error_code="INTERNAL_ERROR",
        error_category="internal_error",
        status_code=500,
        exception_type=type(exc).__name__,
        stack_trace=raw_tb,
        **_request_context(request),
    )

    details: dict | None = None
    if settings.environment == Environment.DEVELOPMENT:
        # Show type only — not str(exc) which may contain user input / PII
        details = {"exception_type": type(exc).__name__}
    return JSONResponse(
        status_code=500,
        content=_build_envelope(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            correlation_id=request_id,
            details=details,
        ),
    )
