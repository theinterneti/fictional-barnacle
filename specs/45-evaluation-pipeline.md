# S45 — Evaluation Pipeline

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.1
> **Implementation Fit**: ❌ Not Started
> **Level**: 4 — Operations
> **Dependencies**: S42 (LLM Playtester), S43 (Human Playtester Program), S44 (Narrative Quality Evaluation)
> **Related**: v1 S15 (Observability), v1 S16 (Testing Strategy)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

S45 defines the orchestration layer that ties the evaluation stack together:
- Launches S42 LLM playtester runs (in parallel)
- Ingests S43 human feedback records as they arrive
- Invokes S44 evaluators to score each session
- Aggregates scores across a release batch
- Produces verdicts that CI can act on
- Ships results to Langfuse for long-term trend visibility

The pipeline is designed to be runnable in two modes:
1. **CI mode**: triggered by a GitHub Actions workflow after a PR merges to `main`.
   Runs a fixed batch of automated playtests; fails the workflow if quality regresses.
2. **Release mode**: run manually by the program coordinator before a v2.1 milestone
   tag. Incorporates human playtester feedback and produces the release verdict.

---

## 2. Design Principles

### 2.1 Results Are Data, Not Opinions

Every verdict is backed by a `NarrativeQualityReport` (S44) with score,
sources, and fail_reasons. No black-box pass/fail. Engineers can always read
why a run failed.

### 2.2 CI Runs on LLM Signal Only

Human playtester data is not available in CI (humans are not standing by for
every PR). CI uses S42 automated runs only. S44 handles the missing S43 data
gracefully (Wonder marked `not_evaluated`; weight redistributed).

### 2.3 Regression Detection Via Baseline

Every CI run is compared against a **baseline** stored in `data/eval_baseline.json`.
If any category regresses by > 0.10 from baseline, CI fails. This catches
silent narrative degradation.

### 2.4 Langfuse as Long-Term Store

All `NarrativeQualityReport` values are logged as Langfuse scores, keyed by
`session_id`. This gives Langfuse-level visibility into narrative quality
trends across releases without a custom dashboard.

---

## 3. Pipeline Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │           EvaluationPipeline                  │
                    │                                              │
  Trigger ──────►  │  1. plan_runs(scenario_seeds, personas)       │
                    │  2. run_llm_playtesters()  ──────────────────►│── S42 (parallel)
  S43 feedback ──► │  3. ingest_human_feedback()                   │
                    │  4. evaluate_sessions()  ────────────────────►│── S44
                    │  5. aggregate()                               │
                    │  6. compare_to_baseline()                     │
                    │  7. emit_verdict()  ──────────────────────────►│── CI / release gate
                    │  8. ship_to_langfuse()  ─────────────────────►│── Langfuse
                    │  9. write_report(csv / json)                  │
                    └──────────────────────────────────────────────┘
```

---

## 4. Functional Requirements

### FR-45.01 — Run Planning

`EvaluationPipeline.plan_runs(batch_config: BatchConfig) -> list[PlannedRun]`

A `BatchConfig` specifies:
```python
@dataclass
class BatchConfig:
    scenario_seed_ids: list[str]       # seeds to test; default: all S41 seeds
    persona_ids: list[str]             # personas to use; default: all 5 S42 personas
    runs_per_combination: int = 1      # number of independent runs per (seed, persona) pair
    max_parallel_runs: int = 5         # concurrency ceiling
    mode: str = "ci"                   # "ci" or "release"
```

For CI mode: default 4 seeds × 5 personas × 1 = 20 runs.
For release mode: same batch + human feedback ingestion.

### FR-45.02 — Parallel LLM Playtester Execution

Planned runs are dispatched to a `asyncio.Semaphore(max_parallel_runs)` pool.
Each run is an independent `PlaytesterAgent` (S42) invocation. Completed
`PlaytestReport` objects are buffered in memory and immediately passed to S44.

Failed runs (agent status = `abandoned` or exception) are retried once. If
the retry also fails, the run is marked as `error` and excluded from scoring.
If more than 25% of runs end in `error`, the pipeline MUST abort and emit a
CRITICAL log: `eval_pipeline_run_error_rate_too_high`.

### FR-45.03 — Human Feedback Ingestion

In release mode, the pipeline reads S43 feedback JSON records from a
configured path (`EVAL_HUMAN_FEEDBACK_DIR`). Records are matched to sessions
by `session_id`. Unmatched records are logged as warnings.

### FR-45.04 — Session Evaluation

For each session with a completed playtester run (and optionally human
feedback), `NarrativeQualityEvaluator.evaluate(session_id)` (S44) is called.
Results are collected into a `BatchEvalResult`.

### FR-45.05 — Batch Aggregation

`BatchEvalResult` contains per-session reports and batch-level aggregates:

```python
@dataclass
class BatchEvalResult:
    batch_id: str
    mode: str
    total_runs: int
    evaluated_runs: int
    error_runs: int
    per_session: list[NarrativeQualityReport]  # S44
    batch_category_medians: dict[str, float]   # category_id -> median score
    batch_composite_median: float
    pass_count: int
    fail_count: int
    inconclusive_count: int
    batch_verdict: str  # "pass", "fail", "inconclusive"
```

### FR-45.06 — Baseline Comparison

The baseline file at `data/eval_baseline.json` stores the last-known-good
batch medians per category:

```json
{
  "QC-01": 0.82,
  "QC-02": 0.71,
  "QC-03": 0.78,
  "QC-04": 0.85,
  "QC-05": 0.80,
  "QC-06": 0.74
}
```

If any `batch_category_medians[cat] < baseline[cat] - 0.10`, the pipeline
marks the comparison as **regression** and includes the category and delta
in the verdict output.

The baseline MUST be updated manually after a human-reviewed release pass.
Automated CI runs MUST NOT update the baseline.

### FR-45.07 — Verdict Emission

In CI mode the pipeline exits with:
- **Exit code 0**: `batch_verdict == "pass"` AND no category regression
- **Exit code 1**: `batch_verdict == "fail"` OR category regression detected
- **Exit code 2**: pipeline error (> 25% runs errored, or unrecoverable failure)

The verdict is also written to `GITHUB_OUTPUT` (if in GitHub Actions) as
`eval_verdict` and `eval_batch_composite` for downstream use.

### FR-45.08 — Langfuse Export

Every `NarrativeQualityReport` is logged to Langfuse as a set of scores on
the session's trace:
- Score name: `narrative_quality_{category_id.lower()}` (e.g., `narrative_quality_qc_01`)
- Score value: category score (float)
- Score comment: category notes

Langfuse export is fire-and-forget: failure to export MUST NOT block the
pipeline verdict.

### FR-45.09 — Report Output

Two files are written at `EVAL_OUTPUT_DIR`:
1. `batch_{batch_id}.json` — full `BatchEvalResult` serialized
2. `batch_{batch_id}_summary.csv` — one row per session: session_id,
   scenario_seed_id, persona_id, composite_score, verdict, per-category scores

---

## 5. GitHub Actions Integration

A workflow file `.github/workflows/eval.yml` runs the pipeline in CI mode.

```yaml
name: Narrative Quality Evaluation
on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      mode:
        description: "ci or release"
        default: "ci"

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<SHA>
      - name: Run evaluation pipeline
        run: |
          uv run python -m tta.eval.pipeline --mode ${{ inputs.mode || 'ci' }}
        env:
          TTA_API_URL: ${{ secrets.TTA_STAGING_URL }}
          LANGFUSE_SECRET_KEY: ${{ secrets.LANGFUSE_SECRET_KEY }}
          LANGFUSE_PUBLIC_KEY: ${{ secrets.LANGFUSE_PUBLIC_KEY }}
      - name: Upload eval report
        if: always()
        uses: actions/upload-artifact@<SHA>
        with:
          name: eval-report
          path: eval_output/
```

---

## 6. Acceptance Criteria (Gherkin)

```gherkin
Feature: Evaluation Pipeline

  Scenario: AC-45.01 — CI pipeline runs 20 sessions and produces verdict
    Given BatchConfig with default seeds, personas, mode = "ci"
    When EvaluationPipeline.run(batch_config) completes
    Then BatchEvalResult.total_runs = 20
    And batch_verdict is one of: "pass", "fail", "inconclusive"
    And batch_*.json and batch_*_summary.csv are written

  Scenario: AC-45.02 — Category regression triggers CI failure
    Given baseline QC-01 = 0.82
    And batch QC-01 median = 0.70
    When compare_to_baseline is called
    Then verdict includes regression flag for QC-01
    And pipeline exits with code 1

  Scenario: AC-45.03 — All sessions logged to Langfuse
    Given a completed batch
    When the Langfuse export step runs
    Then each session has 6 scores logged (one per QC category)
    And Langfuse export failure does not abort the pipeline

  Scenario: AC-45.04 — Abort on >25% error runs
    Given 6 of 20 planned runs return status = "error" after retry
    When the pipeline checks error rate (6/20 = 30%)
    Then the pipeline aborts
    And CRITICAL log is emitted with eval_pipeline_run_error_rate_too_high
    And exit code 2 is returned

  Scenario: AC-45.05 — Release mode ingests human feedback
    Given EVAL_HUMAN_FEEDBACK_DIR contains 12 S43 feedback records
    And mode = "release"
    When the pipeline runs
    Then 12 sessions have Wonder (QC-03) scored from human data
    And unmatched feedback records are logged as warnings
```

---

## 7. Out of Scope

- A live dashboard UI for evaluation results (Langfuse serves this role).
- Automated baseline updates (manual gate to prevent silent standard degradation).
- Real-time evaluation during active gameplay sessions.
- Per-user personalized quality scoring.

---

## 8. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-45.01 | Results destination — dashboard, CSV, Langfuse? | ✅ Resolved | **All three**: CSV + JSON files as artifacts; Langfuse as long-term score store; no custom dashboard built. Langfuse's built-in score visualization is sufficient for v2.1. |
| OQ-45.02 | What is the CI trigger? Every commit or every PR merge to main? | ✅ Resolved | **Push to main** (post-merge). Running on every PR commit is too expensive (20 LLM sessions per run). `workflow_dispatch` allows manual runs in release mode. |
| OQ-45.03 | Should baseline updates be automated or manual? | ✅ Resolved | **Manual only**. Automated baseline updates would allow gradual quality regression to go undetected. A human must review and approve a baseline update after each release pass. |
