"""Application error types and exception handlers (S23 §3.1, plan §7)."""

from __future__ import annotations

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from tta.config import Environment, get_settings
from tta.errors import CATEGORY_STATUS, ErrorCategory

logger = structlog.get_logger()


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
    request_id: str,
    details: dict | None = None,
    retry_after_seconds: int | None = None,
) -> dict:
    """Build the standard S23 error envelope."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
            "retry_after_seconds": retry_after_seconds,
        }
    }


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handle known application errors with the S23 envelope."""
    request_id = getattr(request.state, "request_id", "unknown")
    headers: dict[str, str] = {}
    if exc.retry_after_seconds is not None:
        headers["Retry-After"] = str(exc.retry_after_seconds)
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_envelope(
            code=exc.code,
            message=exc.message,
            request_id=request_id,
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
    # Pydantic V2 errors() can contain non-serializable ctx values
    # (e.g. ValueError objects). Strip ctx to guarantee safe JSON.
    safe_errors = [{k: v for k, v in e.items() if k != "ctx"} for e in exc.errors()]
    return JSONResponse(
        status_code=422,
        content=_build_envelope(
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            request_id=request_id,
            details={"errors": safe_errors},
        ),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected errors — log traceback, return safe response (FR-23.04)."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception("unhandled_error", request_id=request_id)
    settings = get_settings()
    details: dict | None = None
    if settings.environment == Environment.DEVELOPMENT:
        details = {"exception": f"{type(exc).__name__}: {exc}"}
    return JSONResponse(
        status_code=500,
        content=_build_envelope(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            request_id=request_id,
            details=details,
        ),
    )
