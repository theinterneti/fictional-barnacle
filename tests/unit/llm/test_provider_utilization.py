"""Tests for provider-utilization state modeling (S66 AC-66.04 spike).

These tests define the provider-utilization signal seam before any runtime
integration. The spike uses 429/retry-after events as the primary signal
source — deterministic in unit tests, no spend, directly observable from
LiteLLM exceptions.

AC-66.04 routing behavior (LOW calls prefer HEALTHY over NEAR_LIMIT) is
NOT implemented in this spike. That belongs to the next slice.
"""

from __future__ import annotations

import pytest


@pytest.mark.spec("AC-66.04")
class TestProviderUtilizationState:
    """State enum covers all provider utilization levels."""

    def test_healthy_state_value(self) -> None:
        """HEALTHY maps to 'healthy' string for log observability."""
        from tta.llm.provider_utilization import ProviderUtilizationState

        assert ProviderUtilizationState.HEALTHY == "healthy"

    def test_elevated_state_value(self) -> None:
        """ELEVATED maps to 'elevated' string."""
        from tta.llm.provider_utilization import ProviderUtilizationState

        assert ProviderUtilizationState.ELEVATED == "elevated"

    def test_near_limit_state_value(self) -> None:
        """NEAR_LIMIT maps to 'near_limit' string."""
        from tta.llm.provider_utilization import ProviderUtilizationState

        assert ProviderUtilizationState.NEAR_LIMIT == "near_limit"

    def test_exhausted_state_value(self) -> None:
        """EXHAUSTED maps to 'exhausted' string."""
        from tta.llm.provider_utilization import ProviderUtilizationState

        assert ProviderUtilizationState.EXHAUSTED == "exhausted"

    def test_unknown_state_value(self) -> None:
        """UNKNOWN maps to 'unknown' — safe default, not HEALTHY."""
        from tta.llm.provider_utilization import ProviderUtilizationState

        assert ProviderUtilizationState.UNKNOWN == "unknown"


@pytest.mark.spec("AC-66.04")
class TestProviderUtilizationDataclass:
    """ProviderUtilization is a frozen, serializable record."""

    def test_required_fields(self) -> None:
        """Must capture provider and state at minimum."""
        from tta.llm.provider_utilization import (
            ProviderUtilization,
            ProviderUtilizationState,
        )

        pu = ProviderUtilization(
            provider="google", state=ProviderUtilizationState.HEALTHY
        )
        assert pu.provider == "google"
        assert pu.state == ProviderUtilizationState.HEALTHY
        assert pu.rpm_utilization is None
        assert pu.retry_after_seconds is None
        assert pu.source == "unknown"

    def test_full_fields(self) -> None:
        """All fields are captured when available."""
        from tta.llm.provider_utilization import (
            ProviderUtilization,
            ProviderUtilizationState,
        )

        pu = ProviderUtilization(
            provider="groq",
            state=ProviderUtilizationState.NEAR_LIMIT,
            rpm_utilization=0.85,
            retry_after_seconds=2.5,
            source="retry_after_header",
        )
        assert pu.provider == "groq"
        assert pu.state == ProviderUtilizationState.NEAR_LIMIT
        assert pu.rpm_utilization == 0.85
        assert pu.retry_after_seconds == 2.5
        assert pu.source == "retry_after_header"

    def test_is_frozen(self) -> None:
        """Immutable to prevent accidental mutation in concurrent contexts."""
        import dataclasses

        from tta.llm.provider_utilization import (
            ProviderUtilization,
            ProviderUtilizationState,
        )

        assert dataclasses.is_dataclass(ProviderUtilization)
        # frozen=True is enforced at runtime by dataclass
        pu = ProviderUtilization(
            provider="openai", state=ProviderUtilizationState.HEALTHY
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            pu.provider = "anthropic"  # type: ignore[reportAttributeAccessIssue]


@pytest.mark.spec("AC-66.04")
class TestFrom429Event:
    """Build ProviderUtilization from a LiteLLM RateLimitError or synthetic 429."""

    def test_exhausted_from_retry_after_seconds(self) -> None:
        """A 429 with retry_after_seconds marks provider EXHAUSTED.

        This is the primary spike signal: when LiteLLM raises RateLimitError,
        the exception exposes retry-after metadata. This is the most reliable
        provider-awareness signal we can extract without network probing.
        """
        from tta.llm.provider_utilization import (
            ProviderUtilizationState,
            from_rate_limit_error,
        )

        exc = _make_rate_limit_error(
            status_code=429,
            retry_after=2.0,
            model="google/gemini-2.0-flash",
            headers={"retry-after": "2"},
        )
        pu = from_rate_limit_error(exc)

        assert pu.provider == "google"
        assert pu.state == ProviderUtilizationState.EXHAUSTED
        assert pu.retry_after_seconds == 2.0
        assert pu.source == "retry_after_header"

    def test_near_limit_from_high_utilization(self) -> None:
        """A 429 with no retry_after but high rpm marks provider NEAR_LIMIT.

        When the server returns 429 but without a Retry-After header (e.g.,
        immediate backoff), the provider is congested but not fully exhausted.
        """
        from tta.llm.provider_utilization import (
            ProviderUtilizationState,
            from_rate_limit_error,
        )

        exc = _make_rate_limit_error(
            status_code=429,
            retry_after=None,
            model="nvidia/llama-3.3-70b-instruct",
            headers={},
        )
        pu = from_rate_limit_error(exc)

        assert pu.provider == "nvidia"
        assert pu.state == ProviderUtilizationState.NEAR_LIMIT
        assert pu.retry_after_seconds is None
        assert pu.source == "429_no_retry_after"

    def test_extracts_provider_from_model_name(self) -> None:
        """Provider is the model prefix, extracted from 'openai/gpt-4o'."""
        from tta.llm.provider_utilization import from_rate_limit_error

        exc = _make_rate_limit_error(
            status_code=429,
            retry_after=1.0,
            model="openai/gpt-4o",
            headers={"retry-after": "1"},
        )
        pu = from_rate_limit_error(exc)

        assert pu.provider == "openai"

    def test_missing_signal_is_unknown_not_healthy(self) -> None:
        """UNKNOWN is the safe default — never assume HEALTHY without evidence.

        AC-66.04 requires actual signal before routing preferences change.
        A missing signal must not bias routing toward HEALTHY.
        """
        from tta.llm.provider_utilization import (
            ProviderUtilization,
            ProviderUtilizationState,
        )

        pu = ProviderUtilization(
            provider="google", state=ProviderUtilizationState.UNKNOWN
        )
        assert pu.state == ProviderUtilizationState.UNKNOWN
        # The key invariant: UNKNOWN != HEALTHY
        assert ProviderUtilizationState.UNKNOWN != ProviderUtilizationState.HEALTHY


@pytest.mark.spec("AC-66.04")
class TestProviderUtilizationSnapshot:
    """Optional snapshot interface for batch provider state queries."""

    def test_snapshot_protocol(self) -> None:
        """A ProviderUtilizationSnapshot maps provider names to state."""
        from collections.abc import Mapping

        from tta.llm.provider_utilization import (
            ProviderUtilization,
            ProviderUtilizationSnapshot,
            ProviderUtilizationState,
        )

        # Inline fake implementing the protocol for test isolation
        class FakeSnapshot:
            def snapshot(self) -> Mapping[str, ProviderUtilization]:
                return {
                    "google": ProviderUtilization(
                        provider="google",
                        state=ProviderUtilizationState.NEAR_LIMIT,
                        source="retry_after_header",
                    ),
                }

        snapshot: ProviderUtilizationSnapshot = FakeSnapshot()
        state_map = snapshot.snapshot()
        assert "google" in state_map
        assert state_map["google"].state == ProviderUtilizationState.NEAR_LIMIT


# ---------------------------------------------------------------------------
# Test helpers — synthetic LiteLLM RateLimitError without live calls
# ---------------------------------------------------------------------------


def _make_rate_limit_error(
    *,
    status_code: int,
    retry_after: float | None,
    model: str,
    headers: dict[str, str],
) -> Exception:
    """Build a synthetic LiteLLM RateLimitError with known attributes.

    LiteLLM's RateLimitError has: status_code, response_headers, retry_after,
    model, and message.
    """
    # Use a minimal mock that sets the attributes LiteLLM actually uses
    exc = Exception(f"Rate limit exceeded for model={model}")
    exc.status_code = status_code
    exc.model = model
    exc._response_headers: dict[str, str] = headers  # type: ignore[reportAttributeAccessIssue]
    exc.retry_after = retry_after  # type: ignore[reportAttributeAccessIssue]
    return exc
