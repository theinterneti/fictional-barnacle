"""Data models for S44 — Narrative Quality Evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

CategoryStatus = Literal["scored", "not_evaluated", "failed"]
Verdict = Literal["pass", "fail", "inconclusive"]

# Category IDs
QC_COHERENCE = "QC-01"
QC_TENSION = "QC-02"
QC_WONDER = "QC-03"
QC_CHARACTER_DEPTH = "QC-04"
QC_GENRE_FIDELITY = "QC-05"
QC_CONSEQUENCE_WEIGHT = "QC-06"

ALL_CATEGORIES = [
    QC_COHERENCE,
    QC_TENSION,
    QC_WONDER,
    QC_CHARACTER_DEPTH,
    QC_GENRE_FIDELITY,
    QC_CONSEQUENCE_WEIGHT,
]

# Composite score weights (must sum to 1.0)
CATEGORY_WEIGHTS: dict[str, float] = {
    QC_COHERENCE: 0.25,
    QC_TENSION: 0.15,
    QC_WONDER: 0.20,
    QC_CHARACTER_DEPTH: 0.20,
    QC_GENRE_FIDELITY: 0.10,
    QC_CONSEQUENCE_WEIGHT: 0.10,
}

# Verdict thresholds
PASS_COMPOSITE_THRESHOLD = 0.65
FAIL_INDIVIDUAL_THRESHOLD = 0.40
INCONCLUSIVE_MIN_NOT_EVALUATED = 3


@dataclass
class CategoryScore:
    """Score for a single quality category (S44 §4)."""

    category_id: str
    score: float | None  # 0.0–1.0, or None when not_evaluated
    status: CategoryStatus
    sources: list[str]  # e.g. ["automated"], ["human"], ["automated", "human"]
    notes: str = ""

    def is_evaluated(self) -> bool:
        return self.status == "scored"


@dataclass
class NarrativeQualityReport:
    """Full output of a narrative quality evaluation run (S44 §4)."""

    report_id: str
    session_id: str
    run_id: str | None
    scenario_seed_id: str
    evaluated_at: datetime
    categories: list[CategoryScore]
    composite_score: float
    verdict: Verdict
    fail_reasons: list[str] = field(default_factory=list)

    def category(self, category_id: str) -> CategoryScore | None:
        for c in self.categories:
            if c.category_id == category_id:
                return c
        return None
