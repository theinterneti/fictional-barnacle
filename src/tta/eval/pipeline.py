"""S45 — EvaluationPipeline: orchestrates batch LLM playtesting and scoring."""

from __future__ import annotations

import asyncio
import csv
import json
import os
import statistics
import uuid
from typing import Any

import structlog

from tta.eval.models import (
    BatchConfig,
    BatchEvalResult,
    PlannedRun,
    RegressionResult,
    RunResult,
)
from tta.observability.langfuse import get_langfuse
from tta.playtester.consent import ConsentDeniedError, check_consent_gate
from tta.playtester.models import HumanFeedbackRecord
from tta.quality.models import ALL_CATEGORIES, NarrativeQualityReport

log = structlog.get_logger(__name__)

_ERROR_RATE_ABORT_THRESHOLD = 0.25
_REGRESSION_DELTA = 0.10


class EvaluationPipeline:
    """9-step batch evaluation pipeline (S45)."""

    def __init__(
        self,
        config: BatchConfig | None = None,
        api_base_url: str = "",
        api_key: str | None = None,
        llm_client: Any = None,
    ) -> None:
        self._config = config or BatchConfig()
        self._api_base_url = api_base_url
        self._api_key = api_key
        self._llm = llm_client

    # ------------------------------------------------------------------
    # Step 1 — plan

    def plan_runs(self) -> list[PlannedRun]:
        """Generate the full list of planned runs (seeds × personas × reps)."""
        import random

        rng = random.Random(42)
        planned: list[PlannedRun] = []
        for seed_id in self._config.scenario_seed_ids:
            for persona_id in self._config.persona_ids:
                for _ in range(self._config.runs_per_combination):
                    planned.append(
                        PlannedRun(
                            run_id=str(uuid.uuid4()),
                            scenario_seed_id=seed_id,
                            persona_id=persona_id,
                            run_seed=rng.randint(0, 2**31 - 1),
                            persona_jitter_seed=rng.randint(0, 2**31 - 1),
                        )
                    )
        return planned

    # ------------------------------------------------------------------
    # Step 2 — execute LLM playtesters

    async def run_llm_playtesters(self, planned: list[PlannedRun]) -> list[RunResult]:
        """Run all planned sessions in parallel (bounded by max_parallel_runs)."""
        from tta.playtest.agent import PlaytesterAgent

        sem = asyncio.Semaphore(self._config.max_parallel_runs)

        async def _run_one(p: PlannedRun) -> RunResult:
            async with sem:
                for attempt in range(2):
                    try:
                        agent = PlaytesterAgent(
                            api_base_url=self._api_base_url,
                            llm_client=self._llm,
                            api_key=self._api_key,
                        )
                        agent.setup(
                            scenario_seed_id=p.scenario_seed_id,
                            persona_id=p.persona_id,
                            run_seed=p.run_seed,
                            persona_jitter_seed=p.persona_jitter_seed,
                        )
                        report = await agent.run()
                        if report.status != "complete":
                            raise RuntimeError(f"Non-complete status: {report.status}")
                        return RunResult(
                            run_id=p.run_id,
                            scenario_seed_id=p.scenario_seed_id,
                            persona_id=p.persona_id,
                            status="complete",
                            playtest_report=report,
                        )
                    except Exception as exc:
                        if attempt == 0:
                            log.warning(
                                "playtest_run_retry",
                                run_id=p.run_id,
                                error=str(exc),
                            )
                            continue
                        log.error(
                            "playtest_run_failed",
                            run_id=p.run_id,
                            error=str(exc),
                        )
                        return RunResult(
                            run_id=p.run_id,
                            scenario_seed_id=p.scenario_seed_id,
                            persona_id=p.persona_id,
                            status="error",
                            error=str(exc),
                        )
                # unreachable, but satisfies type checker
                return RunResult(  # pragma: no cover
                    run_id=p.run_id,
                    scenario_seed_id=p.scenario_seed_id,
                    persona_id=p.persona_id,
                    status="error",
                )

        return list(await asyncio.gather(*[_run_one(p) for p in planned]))

    # ------------------------------------------------------------------
    # Step 3 — load human feedback

    def load_human_feedback(self) -> dict[str, HumanFeedbackRecord]:
        """Load HumanFeedbackRecord JSON files from human_feedback_dir."""
        feedback: dict[str, HumanFeedbackRecord] = {}
        feedback_dir = self._config.human_feedback_dir
        if not feedback_dir or not os.path.isdir(feedback_dir):
            return feedback

        for fname in os.listdir(feedback_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(feedback_dir, fname)
            try:
                with open(fpath) as fh:
                    data = json.load(fh)
                record = HumanFeedbackRecord.from_dict(data)
                try:
                    granted = check_consent_gate(record)
                except ConsentDeniedError:
                    log.info("human_feedback_consent_denied", file=fname)
                    continue
                if not granted:
                    log.info("human_feedback_consent_withdrawn", file=fname)
                    continue
                feedback[record.session_id] = record
            except Exception as exc:
                log.warning("human_feedback_load_error", file=fname, error=str(exc))

        return feedback

    # ------------------------------------------------------------------
    # Step 4 — evaluate sessions

    async def evaluate_sessions(
        self,
        run_results: list[RunResult],
        human_feedback: dict[str, HumanFeedbackRecord] | None = None,
    ) -> list[NarrativeQualityReport]:
        """Run NarrativeQualityEvaluator on each completed session."""
        from tta.quality.evaluator import NarrativeQualityEvaluator
        from tta.quality.feedback import FeedbackRecord

        evaluator = NarrativeQualityEvaluator(llm_client=self._llm)
        reports: list[NarrativeQualityReport] = []

        for result in run_results:
            if result.status != "complete" or result.playtest_report is None:
                continue

            feedback: FeedbackRecord | None = None
            if human_feedback and result.playtest_report.run_id in human_feedback:
                feedback = human_feedback[
                    result.playtest_report.run_id
                ].to_feedback_record()

            try:
                quality_report = await evaluator.evaluate(
                    result.playtest_report,
                    feedback=feedback,
                    # seed=None: SeedRegistry is not injected into the pipeline.
                    # QC-05 will be not_evaluated; compute_batch_medians omits
                    # empty categories so this propagates correctly downstream.
                    seed=None,
                )
                reports.append(quality_report)
            except Exception as exc:
                log.error(
                    "evaluate_session_failed",
                    run_id=result.run_id,
                    error=str(exc),
                )

        return reports

    # ------------------------------------------------------------------
    # Step 5 — compute batch medians

    def compute_batch_medians(
        self, quality_reports: list[NarrativeQualityReport]
    ) -> dict[str, float]:
        """Compute per-category median composite scores across all reports."""
        by_cat: dict[str, list[float]] = {cat: [] for cat in ALL_CATEGORIES}

        for report in quality_reports:
            for cat_score in report.categories:
                if cat_score.status == "scored" and cat_score.score is not None:
                    by_cat[cat_score.category_id].append(cat_score.score)

        medians: dict[str, float] = {}
        for cat, scores in by_cat.items():
            if scores:
                medians[cat] = statistics.median(scores)
        return medians

    # ------------------------------------------------------------------
    # Step 6 — load baseline

    def load_baseline(self) -> dict[str, float]:
        """Load the baseline scores from the configured JSON file."""
        path = self._config.baseline_path
        if not os.path.exists(path):
            log.warning("baseline_not_found", path=path)
            return {}
        with open(path) as fh:
            return json.load(fh)

    # ------------------------------------------------------------------
    # Step 7 — detect regressions

    def detect_regressions(
        self,
        batch_medians: dict[str, float],
        baseline: dict[str, float],
    ) -> list[RegressionResult]:
        """Flag categories where batch median is more than 0.10 below baseline."""
        regressions: list[RegressionResult] = []
        for cat, base_score in baseline.items():
            batch_score = batch_medians.get(cat, 0.0)
            delta = round(batch_score - base_score, 10)
            if delta < -_REGRESSION_DELTA:
                regressions.append(
                    RegressionResult(
                        category_id=cat,
                        baseline_score=base_score,
                        batch_median=batch_score,
                        delta=delta,
                    )
                )
        return regressions

    # ------------------------------------------------------------------
    # Step 8 — ship to Langfuse

    def ship_to_langfuse(self, quality_reports: list[NarrativeQualityReport]) -> None:
        """Log per-category scores to Langfuse (best-effort, never fatal)."""
        try:
            client = get_langfuse()
            if client is None:
                return
            for report in quality_reports:
                for cat_score in report.categories:
                    if cat_score.score is None or cat_score.status != "scored":
                        continue
                    score_name = (
                        "narrative_quality_"
                        + cat_score.category_id.lower().replace("-", "_")
                    )
                    try:
                        client.score(  # type: ignore[attr-defined]
                            name=score_name,
                            value=cat_score.score,
                            trace_id=report.session_id,
                        )
                    except Exception as exc:
                        log.warning(
                            "langfuse_score_failed",
                            score=score_name,
                            error=str(exc),
                        )
        except Exception as exc:
            log.warning("langfuse_ship_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Step 9 — emit verdict + write outputs

    def emit_verdict(self, result: BatchEvalResult) -> int:
        """Determine exit code and log final verdict.

        Returns:
            2 — error rate > 25 %
            1 — batch fail or regressions detected
            0 — pass
        """
        error_rate = result.error_runs / result.total_runs if result.total_runs else 0.0
        if error_rate > _ERROR_RATE_ABORT_THRESHOLD:
            log.critical(
                "eval_pipeline_run_error_rate_too_high",
                error_runs=result.error_runs,
                total_runs=result.total_runs,
                error_rate=error_rate,
            )
            return 2

        if result.batch_verdict == "fail" or result.regressions:
            return 1

        return 0

    def write_outputs(self, result: BatchEvalResult) -> None:
        """Write batch JSON and summary CSV to the configured output_dir."""
        os.makedirs(self._config.output_dir, exist_ok=True)

        # Full JSON
        json_path = os.path.join(
            self._config.output_dir, f"batch_{result.batch_id}.json"
        )
        with open(json_path, "w") as fh:
            json.dump(_batch_to_dict(result), fh, indent=2)

        # Summary CSV
        csv_path = os.path.join(
            self._config.output_dir, f"batch_{result.batch_id}_summary.csv"
        )
        with open(csv_path, "w", newline="") as fh:
            writer = csv.writer(fh)
            header = [
                "session_id",
                "scenario_seed_id",
                "composite_score",
                "verdict",
            ] + ALL_CATEGORIES
            writer.writerow(header)
            for qr in result.quality_reports:
                cat_scores = {cs.category_id: cs.score for cs in qr.categories}
                row = [
                    qr.session_id,
                    qr.scenario_seed_id,
                    qr.composite_score,
                    qr.verdict,
                ] + [cat_scores.get(cat) for cat in ALL_CATEGORIES]
                writer.writerow(row)

    # ------------------------------------------------------------------
    # Orchestrator

    async def run(self) -> tuple[BatchEvalResult, int]:
        """Execute all 9 pipeline steps and return (result, exit_code)."""
        batch_id = str(uuid.uuid4())

        # 1 — plan
        planned = self.plan_runs()

        # 2 — execute
        run_results = await self.run_llm_playtesters(planned)

        # 3 — human feedback
        human_feedback = self.load_human_feedback()

        # 4 — evaluate
        quality_reports = await self.evaluate_sessions(run_results, human_feedback)

        # 5 — medians
        batch_medians = self.compute_batch_medians(quality_reports)

        # 6 — baseline
        baseline = self.load_baseline()

        # 7 — regressions
        regressions = self.detect_regressions(batch_medians, baseline)

        # 8 — Langfuse
        self.ship_to_langfuse(quality_reports)

        total = len(run_results)
        error_runs = sum(1 for r in run_results if r.status == "error")
        complete_runs = sum(1 for r in run_results if r.status == "complete")

        fail_cats = sum(1 for qr in quality_reports if qr.verdict == "fail")
        batch_verdict: str
        if not quality_reports:
            batch_verdict = "inconclusive"
        elif fail_cats > 0 or regressions:
            batch_verdict = "fail"
        else:
            batch_verdict = "pass"

        result = BatchEvalResult(
            batch_id=batch_id,
            total_runs=total,
            complete_runs=complete_runs,
            error_runs=error_runs,
            quality_reports=quality_reports,
            batch_category_medians=batch_medians,
            baseline=baseline,
            regressions=regressions,
            batch_verdict=batch_verdict,  # type: ignore[arg-type]
            human_feedback_count=len(human_feedback),
        )

        # 9 — outputs
        self.write_outputs(result)
        exit_code = self.emit_verdict(result)

        return result, exit_code


# ---------------------------------------------------------------------------
# Serialisation helpers


def _batch_to_dict(result: BatchEvalResult) -> dict:
    import dataclasses

    d = dataclasses.asdict(result)
    # quality_reports are not plain dataclasses — convert manually
    d["quality_reports"] = [
        {
            "session_id": qr.session_id,
            "scenario_seed_id": qr.scenario_seed_id,
            "composite_score": qr.composite_score,
            "verdict": qr.verdict,
            "fail_reasons": qr.fail_reasons,
            "categories": [
                {
                    "category_id": cs.category_id,
                    "score": cs.score,
                    "status": cs.status,
                }
                for cs in qr.categories
            ],
        }
        for qr in result.quality_reports
    ]
    return d
