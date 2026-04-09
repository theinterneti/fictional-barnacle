"""Domain error taxonomy (S23 §3.1).

Cross-cutting error categories and their HTTP status code mapping.
AppError (the API exception) lives in tta.api.errors and imports from here.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ErrorCategory", "CATEGORY_STATUS"]


class ErrorCategory(StrEnum):
    """Nine error categories per S23 §3.1 error taxonomy."""

    INPUT_INVALID = "input_invalid"
    AUTH_REQUIRED = "auth_required"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    LLM_FAILURE = "llm_failure"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INTERNAL_ERROR = "internal_error"


CATEGORY_STATUS: dict[ErrorCategory, int] = {
    ErrorCategory.INPUT_INVALID: 400,
    ErrorCategory.AUTH_REQUIRED: 401,
    ErrorCategory.FORBIDDEN: 403,
    ErrorCategory.NOT_FOUND: 404,
    ErrorCategory.CONFLICT: 409,
    ErrorCategory.RATE_LIMITED: 429,
    ErrorCategory.LLM_FAILURE: 502,
    ErrorCategory.SERVICE_UNAVAILABLE: 503,
    ErrorCategory.INTERNAL_ERROR: 500,
}
