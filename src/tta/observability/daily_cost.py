"""Daily LLM cost summary — S15 §9 AC-31, FR-15.37.

Provides an in-memory per-model cost accumulator and a background task
that emits a structured log line at midnight UTC with the daily cost
breakdown.  The accumulator is incremented from ``guarded_llm_call()``
after each LLM call, so it is always up to date.

FR-15.37 requires ``total_cost_usd``, ``total_turns``, ``by_model``,
and ``avg_cost_per_turn_usd`` in the summary log.

The task is started in the FastAPI lifespan and cancelled on shutdown.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from threading import Lock

import structlog

_log = structlog.get_logger(__name__)

# Per-model cost accumulator (thread-safe via lock)
_daily_costs: dict[str, float] = defaultdict(float)
_daily_turns: int = 0
_daily_lock = Lock()


def record_daily_cost(model: str, cost_usd: float) -> None:
    """Add a cost entry to the daily accumulator."""
    if cost_usd <= 0:
        return
    with _daily_lock:
        _daily_costs[model] += cost_usd


def record_daily_turn() -> None:
    """Increment the daily turn counter (called once per pipeline turn)."""
    global _daily_turns  # noqa: PLW0603
    with _daily_lock:
        _daily_turns += 1


def get_daily_costs() -> dict[str, float]:
    """Return a snapshot of the current daily cost accumulator."""
    with _daily_lock:
        return dict(_daily_costs)


def get_daily_turns() -> int:
    """Return the current daily turn count."""
    with _daily_lock:
        return _daily_turns


def reset_daily_costs() -> None:
    """Reset the daily accumulator — called after emission."""
    global _daily_turns  # noqa: PLW0603
    with _daily_lock:
        _daily_costs.clear()
        _daily_turns = 0


def _seconds_until_midnight_utc() -> float:
    """Return seconds from now until next midnight UTC."""
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (tomorrow - now).total_seconds()


async def daily_cost_summary_loop() -> None:
    """Background task: emit daily cost summary at midnight UTC.

    Runs indefinitely until cancelled.  On each tick:
    1. Sleep until midnight UTC
    2. Snapshot and reset the accumulator
    3. Emit a structured INFO log per FR-15.37 format
    """
    while True:
        await asyncio.sleep(_seconds_until_midnight_utc())
        snapshot = get_daily_costs()
        turns = get_daily_turns()
        reset_daily_costs()

        total = sum(snapshot.values())
        avg_per_turn = round(total / turns, 6) if turns > 0 else 0.0
        _log.info(
            "daily_llm_cost_summary",
            total_cost_usd=round(total, 6),
            by_model={k: round(v, 6) for k, v in snapshot.items()},
            total_turns=turns,
            avg_cost_per_turn_usd=avg_per_turn,
            date=(datetime.now(UTC) - timedelta(seconds=1)).strftime("%Y-%m-%d"),
        )
