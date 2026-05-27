"""Provider-utilization state modeling for S66 AC-66.04.

This module provides the signal seam for provider-aware routing. It is
deliberately minimal and decoupled from LiteLLM and HTTP clients — the
data model and parser functions can be tested in isolation without live
network calls.

Signal sources (in priority order):
1. 429/retry-after events from LiteLLM exceptions (primary, implemented)
2. LiteLLM response headers (future slice)
3. FMR capacity endpoint (future slice, requires network)

Routing behavior (LOW calls prefer HEALTHY over NEAR_LIMIT) is NOT
implemented here. That belongs to the slice that consumes this signal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ProviderUtilizationState(StrEnum):
    """Provider utilization level (S66 §2.3).

    UNKNOWN is the safe default — never assume HEALTHY without evidence.
    AC-66.04 routing must not bias toward HEALTHY when no signal exists.
    """

    HEALTHY = "healthy"  # <50% RPM — prefer for LOW/BEST_EFFORT
    ELEVATED = "elevated"  # 50-80% RPM — acceptable
    NEAR_LIMIT = "near_limit"  # >80% RPM — avoid for LOW/BEST_EFFORT
    EXHAUSTED = "exhausted"  # 429 received — do not use
    UNKNOWN = "unknown"  # No signal — safe default, never HEALTHY


@dataclass(frozen=True)
class ProviderUtilization:
    """Immutable record of a provider's current utilization.

    Created from: rate-limit errors, response headers, FMR snapshots.
    Serializable for structlog output and future persistence.
    """

    provider: str
    """Provider name, e.g. 'google', 'groq', 'nvidia'."""

    state: ProviderUtilizationState
    """Derived utilization level."""

    rpm_utilization: float | None = None
    """Observed RPM utilization as a fraction [0.0, 1.0], if available."""

    retry_after_seconds: float | None = None
    """Seconds the provider asked us to wait, from Retry-After header."""

    source: str = "unknown"
    """Traceability tag: which signal produced this record."""


class ProviderUtilizationSnapshot(Protocol):
    """Injectable interface for querying provider state.

    Implement this protocol to supply provider state from any source
    (LiteLLM exception handlers, FMR capacity endpoint, in-memory cache).
    RateLimitBudget accepts an optional snapshot for log enrichment.
    """

    def snapshot(self) -> Mapping[str, ProviderUtilization]:
        """Return current utilization state for all tracked providers."""
        ...


#: Type alias for concrete snapshot implementations
type ProviderUtilizationSource = ProviderUtilizationSnapshot


def from_rate_limit_error(exc: Exception) -> ProviderUtilization:
    """Build ProviderUtilization from a LiteLLM RateLimitError.

    This is the primary spike signal. When LiteLLM raises a 429, the
    exception carries retry-after metadata that encodes provider state.

    Args:
        exc: A LiteLLM RateLimitError (or synthetic equivalent) with
            attributes: model, status_code, retry_after, _response_headers.

    Returns:
        ProviderUtilization with provider, state, retry_after_seconds,
        and source tag.

    Signal mapping:
        - retry_after is not None → EXHAUSTED (provider asked us to wait)
        - retry_after is None and status is 429 → NEAR_LIMIT (congested)
        - other 429 with Retry-After header → EXHAUSTED
    """
    provider = _extract_provider(exc)
    status_code = getattr(exc, "status_code", None)

    retry_after: float | None = getattr(exc, "retry_after", None)
    headers: dict[str, str] = getattr(exc, "_response_headers", {})

    if status_code != 429:
        return ProviderUtilization(
            provider=provider,
            state=ProviderUtilizationState.UNKNOWN,
            retry_after_seconds=retry_after,
            source="non_429_error",
        )

    # Parse Retry-After header if retry_after attribute is not set
    if retry_after is None:
        retry_after_header = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after_header is not None:
            try:
                retry_after = float(retry_after_header)
            except ValueError:
                retry_after = None

    # State derivation
    if retry_after is not None:
        state = ProviderUtilizationState.EXHAUSTED
        source = "retry_after_header"
    else:
        # 429 without Retry-After: congested but not fully exhausted
        state = ProviderUtilizationState.NEAR_LIMIT
        source = "429_no_retry_after"

    return ProviderUtilization(
        provider=provider,
        state=state,
        retry_after_seconds=retry_after,
        source=source,
    )


def _extract_provider(exc: Exception) -> str:
    """Extract provider name from a LiteLLM exception's model attribute.

    LiteLLM model strings are '{provider}/{model}', e.g. 'google/gemini-2.0-flash'.
    Returns 'unknown' if the model attribute is missing or malformed.
    """
    model: str = getattr(exc, "model", "") or ""
    if "/" in model:
        return model.split("/", 1)[0]
    if model:
        # Bare model name — treat as provider (some deployments use this)
        return model
    return "unknown"
