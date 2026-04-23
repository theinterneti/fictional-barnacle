"""S45 — Evaluation Pipeline AC compliance tests.

AC-45.01  20-run batches: plan_runs() generates correct count
AC-45.02  Regression detection: delta < -0.10 triggers, -0.10 does NOT
AC-45.03  Langfuse logging: scores shipped; Langfuse failure never fatal
AC-45.04  Error-rate abort: > 25 % error runs returns exit code 2
AC-45.05  Human feedback ingestion: consent gate respected
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tta.eval.models import (
    BatchConfig,
    BatchEvalResult,
    RegressionResult,
)
from tta.eval.pipeline import EvaluationPipeline

# ---------------------------------------------------------------------------
# Helpers


def _make_pipeline(**cfg_kwargs) -> EvaluationPipeline:
    config = BatchConfig(**cfg_kwargs) if cfg_kwargs else BatchConfig()
    return EvaluationPipeline(config=config)


def _make_human_feedback(session_id: str, consent_status: str = "granted") -> dict:
    return {
        "session_id": session_id,
        "scenario_seed_id": "bus-stop-shimmer",
        "turns_played": 8,
        "genesis_completed": True,
        "submission_timestamp": "2025-01-01T00:00:00+00:00",
        "q_coherence": 4.0,
        "q_wonder": 3.5,
        "q_character": 4.0,
        "q_pacing": 3.0,
        "q_genesis_comfort": 4.0,
        "q_consequence": 3.5,
        "q_overall": 4.0,
        "q_recommend": "yes",
        "consent_status": consent_status,
    }


# ---------------------------------------------------------------------------
# AC-45.01 — 20-run batches


@pytest.mark.spec("AC-45.01")
def test_plan_runs_default_generates_20():
    pipeline = _make_pipeline()
    planned = pipeline.plan_runs()
    assert len(planned) == 20  # 4 seeds × 5 personas × 1 rep


@pytest.mark.spec("AC-45.01")
def test_plan_runs_covers_all_seeds_and_personas():
    pipeline = _make_pipeline()
    planned = pipeline.plan_runs()
    seeds = {p.scenario_seed_id for p in planned}
    personas = {p.persona_id for p in planned}
    assert seeds == {
        "bus-stop-shimmer",
        "cafe-with-strange-symbols",
        "dirty-frodo",
        "library-forbidden-book",
    }
    assert personas == {
        "curious-explorer",
        "verbose-narrator",
        "terse-minimalist",
        "impulsive-actor",
        "disengaged-skeptic",
    }


@pytest.mark.spec("AC-45.01")
def test_plan_runs_run_ids_are_unique():
    pipeline = _make_pipeline()
    planned = pipeline.plan_runs()
    ids = [p.run_id for p in planned]
    assert len(ids) == len(set(ids))


@pytest.mark.spec("AC-45.01")
def test_batch_config_total_planned():
    config = BatchConfig(
        scenario_seed_ids=["s1", "s2"],
        persona_ids=["p1", "p2", "p3"],
        runs_per_combination=2,
    )
    assert config.total_planned == 12


# ---------------------------------------------------------------------------
# AC-45.02 — Regression detection


@pytest.mark.spec("AC-45.02")
def test_regression_detected_when_delta_exceeds_threshold():
    pipeline = _make_pipeline()
    baseline = {"QC-01": 0.80}
    batch_medians = {"QC-01": 0.65}  # delta = -0.15 < -0.10
    regressions = pipeline.detect_regressions(batch_medians, baseline)
    assert len(regressions) == 1
    assert regressions[0].category_id == "QC-01"
    assert regressions[0].delta == pytest.approx(-0.15)


@pytest.mark.spec("AC-45.02")
def test_regression_not_detected_at_exact_threshold():
    pipeline = _make_pipeline()
    baseline = {"QC-01": 0.80}
    batch_medians = {"QC-01": 0.70}  # delta = -0.10 (not strictly less)
    regressions = pipeline.detect_regressions(batch_medians, baseline)
    assert len(regressions) == 0


@pytest.mark.spec("AC-45.02")
def test_no_regression_when_above_baseline():
    pipeline = _make_pipeline()
    baseline = {"QC-01": 0.80}
    batch_medians = {"QC-01": 0.85}
    regressions = pipeline.detect_regressions(batch_medians, baseline)
    assert len(regressions) == 0


@pytest.mark.spec("AC-45.02")
def test_regression_result_contains_correct_delta():
    pipeline = _make_pipeline()
    baseline = {"QC-02": 0.71}
    batch_medians = {"QC-02": 0.50}  # delta = -0.21
    regressions = pipeline.detect_regressions(batch_medians, baseline)
    assert regressions[0].baseline_score == pytest.approx(0.71)
    assert regressions[0].batch_median == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# AC-45.03 — Langfuse logging


@pytest.mark.spec("AC-45.03")
def test_langfuse_scores_shipped_for_scored_categories():
    mock_client = MagicMock()
    mock_cat = MagicMock()
    mock_cat.category_id = "QC-01"
    mock_cat.score = 0.85
    mock_cat.status = "scored"

    mock_report = MagicMock()
    mock_report.session_id = "sess-abc"
    mock_report.categories = [mock_cat]

    pipeline = _make_pipeline()
    with patch("tta.eval.pipeline.get_langfuse", return_value=mock_client):
        pipeline.ship_to_langfuse([mock_report])

    mock_client.score.assert_called_once_with(
        name="narrative_quality_qc_01",
        value=0.85,
        trace_id="sess-abc",
    )


@pytest.mark.spec("AC-45.03")
def test_langfuse_skips_none_score():
    mock_client = MagicMock()
    mock_cat = MagicMock()
    mock_cat.category_id = "QC-02"
    mock_cat.score = None
    mock_cat.status = "scored"

    mock_report = MagicMock()
    mock_report.session_id = "sess-abc"
    mock_report.categories = [mock_cat]

    pipeline = _make_pipeline()
    with patch("tta.eval.pipeline.get_langfuse", return_value=mock_client):
        pipeline.ship_to_langfuse([mock_report])

    mock_client.score.assert_not_called()


@pytest.mark.spec("AC-45.03")
def test_langfuse_skips_not_evaluated_status():
    mock_client = MagicMock()
    mock_cat = MagicMock()
    mock_cat.category_id = "QC-03"
    mock_cat.score = 0.75
    mock_cat.status = "not_evaluated"

    mock_report = MagicMock()
    mock_report.session_id = "sess-abc"
    mock_report.categories = [mock_cat]

    pipeline = _make_pipeline()
    with patch("tta.eval.pipeline.get_langfuse", return_value=mock_client):
        pipeline.ship_to_langfuse([mock_report])

    mock_client.score.assert_not_called()


@pytest.mark.spec("AC-45.03")
def test_langfuse_failure_does_not_abort_pipeline():
    mock_client = MagicMock()
    mock_client.score.side_effect = RuntimeError("Langfuse down")

    mock_cat = MagicMock()
    mock_cat.category_id = "QC-01"
    mock_cat.score = 0.8
    mock_cat.status = "scored"

    mock_report = MagicMock()
    mock_report.session_id = "sess-abc"
    mock_report.categories = [mock_cat]

    pipeline = _make_pipeline()
    # Should not raise
    with patch("tta.eval.pipeline.get_langfuse", return_value=mock_client):
        pipeline.ship_to_langfuse([mock_report])


@pytest.mark.spec("AC-45.03")
def test_langfuse_none_client_skips_shipping():
    pipeline = _make_pipeline()
    with patch("tta.eval.pipeline.get_langfuse", return_value=None):
        # Should not raise, nothing to ship
        pipeline.ship_to_langfuse([MagicMock()])


# ---------------------------------------------------------------------------
# AC-45.04 — Error rate abort


@pytest.mark.spec("AC-45.04")
def test_emit_verdict_exit_2_when_error_rate_exceeds_25_pct():
    pipeline = _make_pipeline()
    result = BatchEvalResult(
        batch_id="b1",
        total_runs=4,
        complete_runs=1,
        error_runs=3,  # 75 % error rate
        batch_verdict="pass",
    )
    assert pipeline.emit_verdict(result) == 2


@pytest.mark.spec("AC-45.04")
def test_emit_verdict_exit_2_at_exactly_26_pct():
    pipeline = _make_pipeline()
    result = BatchEvalResult(
        batch_id="b1",
        total_runs=100,
        complete_runs=74,
        error_runs=26,
        batch_verdict="pass",
    )
    assert pipeline.emit_verdict(result) == 2


@pytest.mark.spec("AC-45.04")
def test_emit_verdict_no_abort_at_25_pct_exactly():
    pipeline = _make_pipeline()
    result = BatchEvalResult(
        batch_id="b1",
        total_runs=4,
        complete_runs=3,
        error_runs=1,  # exactly 25 % — NOT strictly greater
        batch_verdict="pass",
    )
    assert pipeline.emit_verdict(result) != 2


@pytest.mark.spec("AC-45.04")
def test_emit_verdict_exit_1_on_regression():
    pipeline = _make_pipeline()
    result = BatchEvalResult(
        batch_id="b1",
        total_runs=20,
        complete_runs=20,
        error_runs=0,
        batch_verdict="pass",
        regressions=[RegressionResult("QC-01", 0.80, 0.65, -0.15)],
    )
    assert pipeline.emit_verdict(result) == 1


@pytest.mark.spec("AC-45.04")
def test_emit_verdict_exit_1_on_fail_verdict():
    pipeline = _make_pipeline()
    result = BatchEvalResult(
        batch_id="b1",
        total_runs=20,
        complete_runs=20,
        error_runs=0,
        batch_verdict="fail",
    )
    assert pipeline.emit_verdict(result) == 1


@pytest.mark.spec("AC-45.04")
def test_emit_verdict_exit_0_on_pass():
    pipeline = _make_pipeline()
    result = BatchEvalResult(
        batch_id="b1",
        total_runs=20,
        complete_runs=20,
        error_runs=0,
        batch_verdict="pass",
    )
    assert pipeline.emit_verdict(result) == 0


# ---------------------------------------------------------------------------
# AC-45.05 — Human feedback ingestion


@pytest.mark.spec("AC-45.05")
def test_load_human_feedback_loads_granted_records(tmp_path):
    data = _make_human_feedback("sess-001", consent_status="granted")
    (tmp_path / "feedback_1.json").write_text(json.dumps(data))

    pipeline = EvaluationPipeline(config=BatchConfig(human_feedback_dir=str(tmp_path)))
    loaded = pipeline.load_human_feedback()
    assert "sess-001" in loaded
    assert loaded["sess-001"].q_wonder == 3.5


@pytest.mark.spec("AC-45.05")
def test_load_human_feedback_skips_not_granted(tmp_path):
    data = _make_human_feedback("sess-002", consent_status="not_granted")
    (tmp_path / "feedback_2.json").write_text(json.dumps(data))

    pipeline = EvaluationPipeline(config=BatchConfig(human_feedback_dir=str(tmp_path)))
    loaded = pipeline.load_human_feedback()
    assert "sess-002" not in loaded


@pytest.mark.spec("AC-45.05")
def test_load_human_feedback_skips_withdrawn(tmp_path):
    data = _make_human_feedback("sess-003", consent_status="withdrawn")
    (tmp_path / "feedback_3.json").write_text(json.dumps(data))

    pipeline = EvaluationPipeline(config=BatchConfig(human_feedback_dir=str(tmp_path)))
    loaded = pipeline.load_human_feedback()
    assert "sess-003" not in loaded


@pytest.mark.spec("AC-45.05")
def test_load_human_feedback_empty_dir_returns_empty(tmp_path):
    pipeline = EvaluationPipeline(config=BatchConfig(human_feedback_dir=str(tmp_path)))
    assert pipeline.load_human_feedback() == {}


@pytest.mark.spec("AC-45.05")
def test_load_human_feedback_none_dir_returns_empty():
    pipeline = _make_pipeline()  # human_feedback_dir=None by default
    assert pipeline.load_human_feedback() == {}
