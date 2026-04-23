"""S45 — Evaluation pipeline data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EvalMode = Literal["ci", "local", "full"]


@dataclass
class BatchConfig:
    """Configuration for a single evaluation batch (default: 4×5×1 = 20 runs)."""

    scenario_seed_ids: list[str] = field(
        default_factory=lambda: [
            "bus-stop-shimmer",
            "cafe-with-strange-symbols",
            "dirty-frodo",
            "library-forbidden-book",
        ]
    )
    persona_ids: list[str] = field(
        default_factory=lambda: [
            "curious-explorer",
            "verbose-narrator",
            "terse-minimalist",
            "impulsive-actor",
            "disengaged-skeptic",
        ]
    )
    runs_per_combination: int = 1
    max_parallel_runs: int = 5
    mode: EvalMode = "ci"
    baseline_path: str = "data/eval_baseline.json"
    output_dir: str = "data/eval_output"
    human_feedback_dir: str | None = None

    @property
    def total_planned(self) -> int:
        return (
            len(self.scenario_seed_ids)
            * len(self.persona_ids)
            * self.runs_per_combination
        )


@dataclass
class PlannedRun:
    run_id: str
    scenario_seed_id: str
    persona_id: str
    run_seed: int
    persona_jitter_seed: int = 0


@dataclass
class RunResult:
    run_id: str
    scenario_seed_id: str
    persona_id: str
    status: Literal["complete", "abandoned", "error"]
    playtest_report: Any | None = None  # PlaytestReport
    error: str | None = None


@dataclass
class RegressionResult:
    category_id: str
    baseline_score: float
    batch_median: float
    delta: float


@dataclass
class BatchEvalResult:
    batch_id: str
    total_runs: int
    complete_runs: int
    error_runs: int
    quality_reports: list[Any] = field(default_factory=list)  # NarrativeQualityReport
    batch_category_medians: dict[str, float] = field(default_factory=dict)
    baseline: dict[str, float] = field(default_factory=dict)
    regressions: list[RegressionResult] = field(default_factory=list)
    batch_verdict: Literal["pass", "fail", "inconclusive"] = "inconclusive"
    human_feedback_count: int = 0
