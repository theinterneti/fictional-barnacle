"""LLM cost tracking per S15 §4 US-15.11.

Provides per-model pricing tables, cost estimation, and a session-level
cost tracker that feeds into Prometheus metrics and Langfuse metadata.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from tta.observability.metrics import TURN_LLM_COST

_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Pricing per 1M tokens for a single model."""

    model: str
    prompt_cost_per_1m: float
    completion_cost_per_1m: float


# Default pricing table — override via configuration when needed.
_DEFAULT_PRICING: dict[str, ModelPricing] = {
    "openai/gpt-4o-mini": ModelPricing(
        "openai/gpt-4o-mini",
        prompt_cost_per_1m=0.15,
        completion_cost_per_1m=0.60,
    ),
    "openai/gpt-4o": ModelPricing(
        "openai/gpt-4o",
        prompt_cost_per_1m=2.50,
        completion_cost_per_1m=10.00,
    ),
    "openai/gpt-4-turbo": ModelPricing(
        "openai/gpt-4-turbo",
        prompt_cost_per_1m=10.00,
        completion_cost_per_1m=30.00,
    ),
    "anthropic/claude-3-5-sonnet": ModelPricing(
        "anthropic/claude-3-5-sonnet",
        prompt_cost_per_1m=3.00,
        completion_cost_per_1m=15.00,
    ),
    "anthropic/claude-3-haiku": ModelPricing(
        "anthropic/claude-3-haiku",
        prompt_cost_per_1m=0.25,
        completion_cost_per_1m=1.25,
    ),
}


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    pricing: dict[str, ModelPricing] | None = None,
) -> float:
    """Estimate cost in USD for a single LLM call.

    Returns 0.0 for unknown models (logged as warning).
    """
    table = pricing or _DEFAULT_PRICING
    entry = table.get(model)
    if entry is None:
        _log.debug("unknown_model_pricing", model=model)
        return 0.0

    cost = (prompt_tokens * entry.prompt_cost_per_1m / 1_000_000) + (
        completion_tokens * entry.completion_cost_per_1m / 1_000_000
    )
    return round(cost, 8)


class LLMCostTracker:
    """Accumulates LLM costs within a session.

    Thread-safe for single-request use (one tracker per pipeline run).
    Feeds TURN_LLM_COST Prometheus histogram on each ``record()`` call.
    """

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id
        self._calls: list[dict[str, float | str]] = []
        self._total_usd: float = 0.0

    @property
    def total_usd(self) -> float:
        return self._total_usd

    @property
    def call_count(self) -> int:
        return len(self._calls)

    def record(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        pricing: dict[str, ModelPricing] | None = None,
    ) -> float:
        """Record one LLM call's cost. Returns the estimated cost."""
        cost = estimate_cost(model, prompt_tokens, completion_tokens, pricing)
        self._calls.append(
            {
                "model": model,
                "prompt_tokens": float(prompt_tokens),
                "completion_tokens": float(completion_tokens),
                "cost_usd": cost,
            }
        )
        self._total_usd += cost

        # Push to Prometheus
        TURN_LLM_COST.labels(model=model).observe(cost)
        return cost

    def summary(self) -> dict[str, float | int | str | None]:
        """Return a JSON-safe summary for Langfuse metadata."""
        return {
            "session_id": self.session_id,
            "total_cost_usd": round(self._total_usd, 6),
            "call_count": self.call_count,
        }


# Module-level singleton for convenience (reset per request).
_tracker: LLMCostTracker | None = None


def get_cost_tracker() -> LLMCostTracker:
    """Get the current cost tracker (creates one if needed)."""
    global _tracker  # noqa: PLW0603
    if _tracker is None:
        _tracker = LLMCostTracker()
    return _tracker


def reset_cost_tracker(session_id: str | None = None) -> LLMCostTracker:
    """Reset and return a fresh tracker for a new request."""
    global _tracker  # noqa: PLW0603
    _tracker = LLMCostTracker(session_id=session_id)
    return _tracker
