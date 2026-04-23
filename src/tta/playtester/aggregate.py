"""S43 — Aggregate playtester feedback into summary statistics."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from tta.playtester.models import NOT_VALIDATED_THRESHOLD, HumanFeedbackRecord

_FLOAT_FIELDS = (
    "q_coherence",
    "q_wonder",
    "q_character",
    "q_pacing",
    "q_genesis_comfort",
    "q_consequence",
    "q_overall",
)


@dataclass
class AggregateResult:
    count: int
    median_q_coherence: float
    mean_q_coherence: float
    median_q_wonder: float
    mean_q_wonder: float
    median_q_character: float
    mean_q_character: float
    median_q_pacing: float
    mean_q_pacing: float
    median_q_genesis_comfort: float
    mean_q_genesis_comfort: float
    median_q_consequence: float
    mean_q_consequence: float
    median_q_overall: float
    mean_q_overall: float
    not_validated: bool


def compute_aggregate(records: list[HumanFeedbackRecord]) -> AggregateResult:
    """Compute median and mean for each numeric question across *records*."""
    if not records:
        raise ValueError("No records to aggregate")

    count = len(records)
    data: dict[str, object] = {"count": count}
    for fname in _FLOAT_FIELDS:
        values = [float(getattr(r, fname)) for r in records]
        data[f"median_{fname}"] = statistics.median(values)
        data[f"mean_{fname}"] = statistics.mean(values)

    data["not_validated"] = (
        data["median_q_overall"] < NOT_VALIDATED_THRESHOLD  # type: ignore[operator]
        or data["median_q_coherence"] < NOT_VALIDATED_THRESHOLD  # type: ignore[operator]
    )
    return AggregateResult(**data)  # type: ignore[arg-type]


def check_not_validated_threshold(agg: AggregateResult) -> bool:
    """True when median overall OR coherence falls below NOT_VALIDATED_THRESHOLD."""
    return (
        agg.median_q_overall < NOT_VALIDATED_THRESHOLD
        or agg.median_q_coherence < NOT_VALIDATED_THRESHOLD
    )
