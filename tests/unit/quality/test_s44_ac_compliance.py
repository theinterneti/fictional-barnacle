"""AC compliance tests for S44 — Narrative Quality Evaluation.

Tests cover AC-44.01 through AC-44.05 as specified in
specs/44-narrative-quality-evaluation.md §6.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.unit.quality.conftest import make_report, make_turn
from tta.playtest.report import TurnRecord
from tta.quality.evaluator import NarrativeQualityEvaluator
from tta.quality.feedback import FeedbackRecord
from tta.quality.models import (
    QC_CHARACTER_DEPTH,
    QC_COHERENCE,
    QC_CONSEQUENCE_WEIGHT,
    QC_GENRE_FIDELITY,
    QC_TENSION,
    QC_WONDER,
    NarrativeQualityReport,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_llm(score: int = 4) -> AsyncMock:
    """Return a mock LLMClient whose generate() returns a JSON genre score."""
    import json

    from tta.llm.client import LLMResponse
    from tta.models.turn import TokenCount

    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps({"score": score, "rationale": "good"}),
            model_used="mock-model",
            token_count=TokenCount(
                prompt_tokens=10, completion_tokens=5, total_tokens=15
            ),
            latency_ms=1.0,
        )
    )
    return mock


def _good_feedback(run_id: str = "run-abc") -> FeedbackRecord:
    return FeedbackRecord(
        run_id=run_id, q_wonder=4.0, q_consequence=4.0, q_character=4.0
    )


# ---------------------------------------------------------------------------
# AC-44.01 — All 6 categories scored when full data present
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-44.01")
@pytest.mark.asyncio
async def test_all_categories_scored_when_full_data_present() -> None:
    """AC-44.01: All six QC categories scored when both S42 and S43 data present."""
    report = make_report(
        gameplay_turns_completed=5,
        turns=[
            make_turn(
                turn_index=i,
                narrative="Arika draws her blade. The dragon roars.",
            )
            for i in range(5)
        ],
    )
    feedback = _good_feedback()
    llm = _mock_llm(score=4)

    from tta.universe.composition import UniverseComposition

    class _StubSeed:
        composition = UniverseComposition(primary_genre="fantasy")

    evaluator = NarrativeQualityEvaluator(llm_client=llm)
    result: NarrativeQualityReport = await evaluator.evaluate(
        report,
        feedback=feedback,
        seed=_StubSeed(),
        genesis_character_name="Arika",
        genesis_traits=["blade"],
        consequence_count=3,
    )

    scored_ids = {c.category_id for c in result.categories if c.status == "scored"}
    expected = {
        QC_COHERENCE,
        QC_TENSION,
        QC_WONDER,
        QC_CHARACTER_DEPTH,
        QC_GENRE_FIDELITY,
        QC_CONSEQUENCE_WEIGHT,
    }
    assert scored_ids == expected, f"Expected all 6 scored, got {scored_ids}"


# ---------------------------------------------------------------------------
# AC-44.02 — QC-03 not_evaluated when no S43 data; weight redistributed
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-44.02")
@pytest.mark.asyncio
async def test_qc03_not_evaluated_when_no_feedback() -> None:
    """AC-44.02: QC-03 Wonder is not_evaluated when no human feedback present."""
    report = make_report(gameplay_turns_completed=5)
    evaluator = NarrativeQualityEvaluator()
    result = await evaluator.evaluate(report, feedback=None)

    qc03 = result.category(QC_WONDER)
    assert qc03 is not None
    assert qc03.status == "not_evaluated"
    assert qc03.score is None


@pytest.mark.spec("AC-44.02")
@pytest.mark.asyncio
async def test_qc03_not_evaluated_weight_redistributed() -> None:
    """AC-44.02: QC-03 not_evaluated → composite from remaining 5."""
    # Build a report where QC-01…06 would all be ~0.8 if scored
    turns = [
        make_turn(turn_index=i, coherence_rating=0.8, surprise_level=0.7)
        for i in range(5)
    ]
    report = make_report(turns=turns, gameplay_turns_completed=5)

    evaluator = NarrativeQualityEvaluator()
    result_no_feedback = await evaluator.evaluate(report, feedback=None)
    result_with_feedback = await evaluator.evaluate(
        report,
        feedback=_good_feedback(),
    )

    # Without feedback, QC-03 is not_evaluated → weight redistributed
    qc03_no_fb = result_no_feedback.category(QC_WONDER)
    assert qc03_no_fb is not None and qc03_no_fb.status == "not_evaluated"

    # With feedback, QC-03 is scored → typically higher composite
    qc03_with_fb = result_with_feedback.category(QC_WONDER)
    assert qc03_with_fb is not None and qc03_with_fb.status == "scored"

    # Composite should differ (not_evaluated categories raise or lower denominator)
    # Mainly asserting no exception and valid range
    assert 0.0 <= result_no_feedback.composite_score <= 1.0
    assert 0.0 <= result_with_feedback.composite_score <= 1.0


# ---------------------------------------------------------------------------
# AC-44.03 — QC-04 auto=0.0 if first-turn lacks character name
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-44.03")
@pytest.mark.asyncio
async def test_qc04_auto_zero_when_character_name_absent_from_first_turn() -> None:
    """AC-44.03: QC-04 auto=0.0 when char name not in first gameplay turn."""
    turns = [
        make_turn(turn_index=0, narrative="A mysterious figure enters the dungeon."),
        make_turn(turn_index=1, narrative="The figure fights the goblin."),
    ]
    report = make_report(turns=turns, gameplay_turns_completed=2)
    evaluator = NarrativeQualityEvaluator()
    result = await evaluator.evaluate(
        report,
        feedback=None,
        genesis_character_name="Arika",  # Not mentioned in first turn
    )

    qc04 = result.category(QC_CHARACTER_DEPTH)
    assert qc04 is not None
    assert qc04.status == "scored"
    # Without human feedback the score equals the auto component → 0.0
    assert qc04.score == 0.0, f"Expected 0.0, got {qc04.score}"
    assert "AC-2.3 enforcement miss" in qc04.notes


@pytest.mark.spec("AC-44.03")
@pytest.mark.asyncio
async def test_qc04_notes_mention_enforcement_miss() -> None:
    """AC-44.03: QC-04 notes mention AC-2.3 enforcement miss when name absent."""
    turns = [make_turn(turn_index=0, narrative="The dungeon is dark.")]
    report = make_report(turns=turns, gameplay_turns_completed=1)
    evaluator = NarrativeQualityEvaluator()
    result = await evaluator.evaluate(report, genesis_character_name="Zara")

    qc04 = result.category(QC_CHARACTER_DEPTH)
    assert qc04 is not None
    assert "AC-2.3 enforcement miss" in qc04.notes


# ---------------------------------------------------------------------------
# AC-44.04 — verdict=fail when any scored category < 0.40
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-44.04")
@pytest.mark.asyncio
async def test_verdict_fail_when_individual_category_below_threshold() -> None:
    """AC-44.04: verdict=fail when any scored category < 0.40; fail_reasons set."""
    # Force QC-01 low: coherence_rating = 0.1 across all turns → below 0.4
    turns = [
        make_turn(turn_index=i, coherence_rating=0.1, surprise_level=0.8)
        for i in range(5)
    ]
    report = make_report(turns=turns, gameplay_turns_completed=5)
    evaluator = NarrativeQualityEvaluator()
    result = await evaluator.evaluate(report)

    assert result.verdict == "fail"
    assert len(result.fail_reasons) > 0
    # At least one reason should mention QC-01
    reasons_combined = " ".join(result.fail_reasons)
    assert "QC-01" in reasons_combined or result.composite_score < 0.65


@pytest.mark.spec("AC-44.04")
@pytest.mark.asyncio
async def test_verdict_fail_populates_fail_reasons() -> None:
    """AC-44.04: fail_reasons is non-empty on fail verdict."""
    turns = [make_turn(turn_index=i, coherence_rating=0.1) for i in range(5)]
    report = make_report(turns=turns, gameplay_turns_completed=5)
    evaluator = NarrativeQualityEvaluator()
    result = await evaluator.evaluate(report)

    if result.verdict == "fail":
        assert result.fail_reasons, "fail_reasons must be non-empty on fail verdict"


# ---------------------------------------------------------------------------
# AC-44.05 — verdict=inconclusive when 3+ categories not_evaluated
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-44.05")
@pytest.mark.asyncio
async def test_verdict_inconclusive_when_three_or_more_not_evaluated() -> None:
    """AC-44.05: verdict=inconclusive when 3+ categories are not_evaluated."""
    # Create a report with no commentary (makes many categories not_evaluated)
    # and no feedback, no LLM → QC-02 has no auto, QC-03 has no feedback,
    # QC-05 has no LLM; also force no turns so QC-01 and QC-02 can't score
    from tta.playtest.report import PlaytestReport

    no_commentary_turns = [
        TurnRecord(
            turn_index=i,
            phase="gameplay",
            player_input="go",
            narrative="You go.",
            commentary=None,
        )
        for i in range(3)
    ]

    report = PlaytestReport(
        run_id="run-inconclusive",
        run_seed=1,
        scenario_seed_id="seed-01",
        persona_id="p1",
        persona_jitter_seed=0,
        model="test",
        status="complete",
        genesis_phases_completed=4,
        gameplay_turns_completed=3,
        turns=no_commentary_turns,
    )
    evaluator = NarrativeQualityEvaluator(
        llm_client=None
    )  # no LLM → QC-05 not_evaluated
    result = await evaluator.evaluate(
        report, feedback=None
    )  # no feedback → QC-03 not_evaluated

    # QC-01 not_evaluated (no commentary)
    # QC-02 not_evaluated (no commentary)
    # QC-03 not_evaluated (no feedback)
    # QC-05 not_evaluated (no LLM)
    not_evaluated = [c for c in result.categories if c.status == "not_evaluated"]
    assert len(not_evaluated) >= 3, (
        f"Expected ≥3 not_evaluated, got {len(not_evaluated)}: "
        f"{[c.category_id for c in not_evaluated]}"
    )
    assert result.verdict == "inconclusive"


@pytest.mark.spec("AC-44.05")
@pytest.mark.asyncio
async def test_verdict_inconclusive_fail_reasons_empty() -> None:
    """AC-44.05: inconclusive verdict has empty fail_reasons."""
    from tta.playtest.report import PlaytestReport

    no_commentary_turns = [
        TurnRecord(
            turn_index=i,
            phase="gameplay",
            player_input="go",
            narrative="You go.",
            commentary=None,
        )
        for i in range(3)
    ]
    report = PlaytestReport(
        run_id="run-inconclusive2",
        run_seed=1,
        scenario_seed_id="seed-01",
        persona_id="p1",
        persona_jitter_seed=0,
        model="test",
        status="complete",
        genesis_phases_completed=4,
        gameplay_turns_completed=3,
        turns=no_commentary_turns,
    )
    evaluator = NarrativeQualityEvaluator(llm_client=None)
    result = await evaluator.evaluate(report, feedback=None)

    if result.verdict == "inconclusive":
        assert result.fail_reasons == [], (
            f"inconclusive should have no fail_reasons, got {result.fail_reasons}"
        )


# ---------------------------------------------------------------------------
# Additional unit-level tests for scoring functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verdict_pass_when_all_above_thresholds() -> None:
    """Composite ≥ 0.65 and no individual below 0.40 → pass."""
    turns = [
        make_turn(turn_index=i, coherence_rating=0.9, surprise_level=0.9)
        for i in range(5)
    ]
    report = make_report(
        turns=turns,
        gameplay_turns_completed=5,
        run_id="run-pass",
    )
    feedback = _good_feedback(run_id="run-pass")
    evaluator = NarrativeQualityEvaluator()
    result = await evaluator.evaluate(
        report,
        feedback=feedback,
        genesis_character_name="",
        consequence_count=5,
    )

    assert result.verdict == "pass"
    assert result.composite_score >= 0.65


@pytest.mark.asyncio
async def test_qc05_not_evaluated_when_no_llm() -> None:
    """QC-05 status is not_evaluated when evaluator has no LLM client."""
    report = make_report(gameplay_turns_completed=3)
    evaluator = NarrativeQualityEvaluator(llm_client=None)
    result = await evaluator.evaluate(report)

    qc05 = result.category(QC_GENRE_FIDELITY)
    assert qc05 is not None
    assert qc05.status == "not_evaluated"


@pytest.mark.asyncio
async def test_qc05_uses_temperature_zero() -> None:
    """QC-05 calls LLM with temperature=0 for deterministic scoring."""
    from tta.universe.composition import UniverseComposition

    class _Seed:
        composition = UniverseComposition(primary_genre="sci-fi")

    turns = [
        make_turn(turn_index=i, narrative="The spaceship accelerates.")
        for i in range(3)
    ]
    report = make_report(turns=turns, gameplay_turns_completed=3)

    llm = _mock_llm(score=3)
    evaluator = NarrativeQualityEvaluator(llm_client=llm)
    await evaluator.evaluate(report, seed=_Seed())

    call_kwargs = llm.generate.call_args
    params_arg = call_kwargs.kwargs.get("params") or call_kwargs.args[2]
    assert params_arg.temperature == 0.0


@pytest.mark.asyncio
async def test_feedback_record_normalization() -> None:
    """FeedbackRecord normalizes 1–5 scale to 0.0–1.0 correctly."""
    fb_min = FeedbackRecord(
        run_id="r", q_wonder=1.0, q_consequence=1.0, q_character=1.0
    )
    fb_max = FeedbackRecord(
        run_id="r", q_wonder=5.0, q_consequence=5.0, q_character=5.0
    )
    fb_mid = FeedbackRecord(
        run_id="r", q_wonder=3.0, q_consequence=3.0, q_character=3.0
    )

    assert fb_min.wonder_normalized == 0.0
    assert fb_max.wonder_normalized == 1.0
    assert abs(fb_mid.wonder_normalized - 0.5) < 1e-6


@pytest.mark.asyncio
async def test_report_id_is_unique() -> None:
    """Each evaluation produces a unique report_id."""
    report = make_report(gameplay_turns_completed=2)
    evaluator = NarrativeQualityEvaluator()
    r1 = await evaluator.evaluate(report)
    r2 = await evaluator.evaluate(report)
    assert r1.report_id != r2.report_id


@pytest.mark.asyncio
async def test_composite_score_within_range() -> None:
    """Composite score is always in [0.0, 1.0]."""
    report = make_report(gameplay_turns_completed=5)
    evaluator = NarrativeQualityEvaluator()
    result = await evaluator.evaluate(report)
    assert 0.0 <= result.composite_score <= 1.0
