"""LLM error types and classification.

Defines the error hierarchy for LLM operations and classifies
errors as transient (retryable) or permanent.
"""


class LLMError(Exception):
    """Base error for all LLM operations."""

    def __init__(self, message: str, model: str = "") -> None:
        self.model = model
        super().__init__(message)


class TransientLLMError(LLMError):
    """Retryable LLM error (rate limit, timeout, 5xx)."""


class PermanentLLMError(LLMError):
    """Non-retryable LLM error (auth, invalid request, content filter)."""


class AllTiersFailedError(LLMError):
    """All models in the fallback chain failed."""

    def __init__(self, role: str, errors: list[Exception]) -> None:
        self.role = role
        self.errors = errors
        models = ", ".join(getattr(e, "model", "unknown") for e in errors)
        super().__init__(f"All tiers exhausted for role={role}: [{models}]")


class BudgetExceededError(LLMError):
    """Session cost cap exceeded."""


def classify_error(exc: Exception) -> type[LLMError]:
    """Classify an exception as transient or permanent.

    Uses LiteLLM's exception hierarchy when available, falls back
    to generic classification.
    """
    exc_type = type(exc).__name__

    # LiteLLM transient errors
    transient_types = {
        "RateLimitError",
        "APIConnectionError",
        "Timeout",
        "ServiceUnavailableError",
        "InternalServerError",
    }
    if exc_type in transient_types:
        return TransientLLMError

    # LiteLLM permanent errors
    permanent_types = {
        "AuthenticationError",
        "InvalidRequestError",
        "NotFoundError",
        "ContentPolicyViolationError",
    }
    if exc_type in permanent_types:
        return PermanentLLMError

    # HTTP status code heuristic
    status = getattr(exc, "status_code", None)
    if status is not None:
        if status in (429, 500, 502, 503, 504):
            return TransientLLMError
        if 400 <= status < 500:
            return PermanentLLMError

    # Default: treat as transient (will be retried)
    return TransientLLMError
