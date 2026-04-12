"""LLM cost tracking per S15 §4 US-15.11.

Provides per-model pricing tables, cost estimation, and a session-level
cost tracker that feeds into Prometheus metrics and Langfuse metadata.
"""

from __future__ import annotations

import contextvars
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

    ``session_total_usd`` is seeded from the DB at request start so
    budget checks reflect the full session history, not just the
    current turn.
    """

    def __init__(
        self,
        session_id: str | None = None,
        session_total_usd: float = 0.0,
    ) -> None:
        self.session_id = session_id
        self._calls: list[dict[str, float | str]] = []
        self._turn_cost_usd: float = 0.0
        self._session_total_usd: float = session_total_usd

    @property
    def total_usd(self) -> float:
        """Cost accumulated *this turn* (backwards-compat name)."""
        return self._turn_cost_usd

    @property
    def turn_cost_usd(self) -> float:
        return self._turn_cost_usd

    @property
    def session_total_usd(self) -> float:
        """Full session cost including prior turns + this turn."""
        return self._session_total_usd + self._turn_cost_usd

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
        """Record one LLM call's cost via estimation. Returns the cost."""
        cost = estimate_cost(model, prompt_tokens, completion_tokens, pricing)
        self._calls.append(
            {
                "model": model,
                "prompt_tokens": float(prompt_tokens),
                "completion_tokens": float(completion_tokens),
                "cost_usd": cost,
            }
        )
        self._turn_cost_usd += cost

        # Push to Prometheus
        TURN_LLM_COST.labels(model=model).observe(cost)
        return cost

    def record_actual(
        self,
        model: str,
        cost_usd: float,
    ) -> None:
        """Record one LLM call using the actual provider cost."""
        self._calls.append(
            {
                "model": model,
                "cost_usd": cost_usd,
            }
        )
        self._turn_cost_usd += cost_usd
        TURN_LLM_COST.labels(model=model).observe(cost_usd)

    def check_session_budget(
        self,
        cap_usd: float,
        warn_pct: float = 0.8,
    ) -> str:
        """Check session cost against the cap.

        Returns one of ``"ok"``, ``"warning"``, ``"exceeded"``.
        """
        total = self.session_total_usd
        if total >= cap_usd:
            return "exceeded"
        if total >= cap_usd * warn_pct:
            return "warning"
        return "ok"

    def summary(self) -> dict[str, float | int | str | None]:
        """Return a JSON-safe summary for Langfuse metadata."""
        return {
            "session_id": self.session_id,
            "turn_cost_usd": round(self._turn_cost_usd, 6),
            "session_total_usd": round(self.session_total_usd, 6),
            "call_count": self.call_count,
        }


# Per-request tracker via contextvars (safe for concurrent async requests).
_tracker_var: contextvars.ContextVar[LLMCostTracker | None] = contextvars.ContextVar(
    "llm_cost_tracker", default=None
)


def get_cost_tracker() -> LLMCostTracker:
    """Get the current cost tracker (creates one if needed)."""
    tracker = _tracker_var.get()
    if tracker is None:
        tracker = LLMCostTracker()
        _tracker_var.set(tracker)
    return tracker


def reset_cost_tracker(
    session_id: str | None = None,
    session_total_usd: float = 0.0,
) -> LLMCostTracker:
    """Reset and return a fresh tracker for a new request."""
    tracker = LLMCostTracker(
        session_id=session_id,
        session_total_usd=session_total_usd,
    )
    _tracker_var.set(tracker)
    return tracker
