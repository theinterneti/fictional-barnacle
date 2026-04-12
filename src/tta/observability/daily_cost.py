"""Daily LLM cost summary — S15 §9 AC-31.

Provides an in-memory per-model cost accumulator and a background task
that emits a structured log line at midnight UTC with the daily cost
breakdown.  The accumulator is incremented from ``guarded_llm_call()``
after each LLM call, so it is always up to date.

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
_daily_lock = Lock()


def record_daily_cost(model: str, cost_usd: float) -> None:
    """Add a cost entry to the daily accumulator."""
    if cost_usd <= 0:
        return
    with _daily_lock:
        _daily_costs[model] += cost_usd


def get_daily_costs() -> dict[str, float]:
    """Return a snapshot of the current daily cost accumulator."""
    with _daily_lock:
        return dict(_daily_costs)


def reset_daily_costs() -> None:
    """Reset the daily accumulator — called after emission."""
    with _daily_lock:
        _daily_costs.clear()


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
    3. Emit a structured INFO log with per-model breakdown
    """
    while True:
        await asyncio.sleep(_seconds_until_midnight_utc())
        snapshot = get_daily_costs()
        reset_daily_costs()

        total = sum(snapshot.values())
        _log.info(
            "daily_llm_cost_summary",
            total_usd=round(total, 6),
            by_model={k: round(v, 6) for k, v in snapshot.items()},
            date=(datetime.now(UTC) - timedelta(seconds=1)).strftime("%Y-%m-%d"),
        )
