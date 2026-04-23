"""NarrativeQualityEvaluator — S44 narrative quality evaluation.

Scores a completed playtesting session across six quality categories
(QC-01 through QC-06) and produces a NarrativeQualityReport.

Usage:
    evaluator = NarrativeQualityEvaluator()
    report = await evaluator.evaluate(playtest_report, feedback=fb, seed=seed)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from statistics import mean
from typing import TYPE_CHECKING

from tta.playtest.report import PlaytestReport
from tta.quality.feedback import FeedbackRecord
from tta.quality.models import (
    CATEGORY_WEIGHTS,
    FAIL_INDIVIDUAL_THRESHOLD,
    INCONCLUSIVE_MIN_NOT_EVALUATED,
    PASS_COMPOSITE_THRESHOLD,
    QC_CHARACTER_DEPTH,
    QC_COHERENCE,
    QC_CONSEQUENCE_WEIGHT,
    QC_GENRE_FIDELITY,
    QC_TENSION,
    QC_WONDER,
    CategoryScore,
    NarrativeQualityReport,
    Verdict,
)

if TYPE_CHECKING:
    from tta.llm.client import LLMClient
    from tta.seeds.manifest import SeedManifest

log = logging.getLogger(__name__)


class NarrativeQualityEvaluator:
    """Evaluates a PlaytestReport against S44 quality categories.

    Args:
        llm_client: Optional LLM client for QC-05 genre fidelity scoring.
                    When None, QC-05 is marked not_evaluated.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        report: PlaytestReport,
        *,
        feedback: FeedbackRecord | None = None,
        seed: SeedManifest | None = None,
        genesis_character_name: str = "",
        genesis_traits: list[str] | None = None,
        consequence_count: int = 0,
        expected_consequence_turns: int | None = None,
    ) -> NarrativeQualityReport:
        """Produce a NarrativeQualityReport for a completed playtesting run.

        Args:
            report: S42 PlaytestReport for the session under evaluation.
            feedback: Optional S43 FeedbackRecord with human ratings.
            seed: S41 SeedManifest for QC-05 genre fidelity prompt context.
            genesis_character_name: Primary character name from genesis state.
            genesis_traits: List of declared character traits for QC-04.
            consequence_count: Number of ConsequenceEntry records in session.
            expected_consequence_turns: Denominator for QC-06 ratio; defaults
                                        to the number of gameplay turns.
        """
        categories: list[CategoryScore] = [
            self._score_qc01(report, genesis_character_name),
            self._score_qc02(report, feedback),
            self._score_qc03(report, feedback),
            self._score_qc04(report, feedback, genesis_character_name, genesis_traits),
            await self._score_qc05(report, seed),
            self._score_qc06(
                report,
                feedback,
                consequence_count,
                expected_consequence_turns,
            ),
        ]

        composite = _compute_composite(categories)
        verdict, fail_reasons = _compute_verdict(categories, composite)

        return NarrativeQualityReport(
            report_id=str(uuid.uuid4()),
            session_id=report.run_id,
            run_id=report.run_id,
            scenario_seed_id=report.scenario_seed_id,
            evaluated_at=datetime.now(UTC),
            categories=categories,
            composite_score=composite,
            verdict=verdict,
            fail_reasons=fail_reasons,
        )

    # ------------------------------------------------------------------
    # QC-01 — Coherence (automated)
    # ------------------------------------------------------------------

    def _score_qc01(
        self,
        report: PlaytestReport,
        genesis_character_name: str,
    ) -> CategoryScore:
        """Score narrative coherence from agent commentary and rule checks."""
        commentaries = [t.commentary for t in report.turns if t.commentary is not None]
        if not commentaries:
            return CategoryScore(
                category_id=QC_COHERENCE,
                score=None,
                status="not_evaluated",
                sources=["automated"],
                notes="No commentary turns available.",
            )

        base = mean(c.coherence_rating for c in commentaries)
        contradiction_count = _count_contradictions(report, genesis_character_name)
        raw = base * max(0.0, 1.0 - contradiction_count * 0.15)
        score = max(0.0, min(1.0, raw))
        notes = (
            f"{len(commentaries)} turns scored; "
            f"{contradiction_count} contradictions detected."
        )
        return CategoryScore(
            category_id=QC_COHERENCE,
            score=score,
            status="scored",
            sources=["automated"],
            notes=notes,
        )

    # ------------------------------------------------------------------
    # QC-02 — Tension arc (mixed)
    # ------------------------------------------------------------------

    def _score_qc02(
        self,
        report: PlaytestReport,
        feedback: FeedbackRecord | None,
    ) -> CategoryScore:
        """Score tension from surprise levels and latency penalty."""
        commentaries = [t.commentary for t in report.turns if t.commentary is not None]
        if not commentaries:
            return CategoryScore(
                category_id=QC_TENSION,
                score=None,
                status="not_evaluated",
                sources=["automated"],
                notes="No commentary turns available.",
            )

        auto_tension = mean(c.surprise_level for c in commentaries)
        # Latency penalty: if any turn timed out, apply 0.1 deduction
        timed_out_count = sum(1 for t in report.turns if t.timed_out)
        if timed_out_count > 0:
            auto_tension = max(0.0, auto_tension - 0.10 * timed_out_count)

        if feedback is not None:
            score = 0.6 * auto_tension + 0.4 * feedback.consequence_normalized
            sources = ["automated", "human"]
            notes = (
                f"auto={auto_tension:.3f}, human_q_consequence={feedback.q_consequence}"
            )
        else:
            score = auto_tension
            sources = ["automated"]
            notes = f"auto={auto_tension:.3f}; no human data."

        return CategoryScore(
            category_id=QC_TENSION,
            score=max(0.0, min(1.0, score)),
            status="scored",
            sources=sources,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # QC-03 — Wonder / surprise (human primary, AC-44.02)
    # ------------------------------------------------------------------

    def _score_qc03(
        self,
        report: PlaytestReport,
        feedback: FeedbackRecord | None,
    ) -> CategoryScore:
        """Score wonder — not_evaluated when S43 data is absent (AC-44.02)."""
        if feedback is None:
            # AC-44.02: QC-03 must be not_evaluated when no human data
            return CategoryScore(
                category_id=QC_WONDER,
                score=None,
                status="not_evaluated",
                sources=["human"],
                notes="No human feedback available; QC-03 not evaluated (AC-44.02).",
            )

        commentaries = [t.commentary for t in report.turns if t.commentary is not None]
        human_wonder = feedback.wonder_normalized

        if commentaries:
            auto_wonder = mean(c.surprise_level for c in commentaries)
            score = 0.7 * human_wonder + 0.3 * auto_wonder
            notes = f"human_q_wonder={feedback.q_wonder}, auto={auto_wonder:.3f}"
        else:
            score = human_wonder
            notes = f"human_q_wonder={feedback.q_wonder}; no agent commentary."

        return CategoryScore(
            category_id=QC_WONDER,
            score=max(0.0, min(1.0, score)),
            status="scored",
            sources=["human", "automated"] if commentaries else ["human"],
            notes=notes,
        )

    # ------------------------------------------------------------------
    # QC-04 — Character depth (mixed, AC-44.03)
    # ------------------------------------------------------------------

    def _score_qc04(
        self,
        report: PlaytestReport,
        feedback: FeedbackRecord | None,
        genesis_character_name: str,
        genesis_traits: list[str] | None,
    ) -> CategoryScore:
        """Score character depth. Auto = 0.0 if first-turn enforcement miss."""
        traits = genesis_traits or []
        auto_score, auto_notes = _check_first_turn_character(
            report, genesis_character_name, traits
        )

        if feedback is not None:
            human_score = feedback.character_normalized
            score = 0.5 * auto_score + 0.5 * human_score
            sources = ["automated", "human"]
            notes = (
                f"auto={auto_score:.3f} ({auto_notes}), "
                f"human_q_character={feedback.q_character}"
            )
        else:
            score = auto_score
            sources = ["automated"]
            notes = auto_notes

        return CategoryScore(
            category_id=QC_CHARACTER_DEPTH,
            score=max(0.0, min(1.0, score)),
            status="scored",
            sources=sources,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # QC-05 — Genre fidelity (LLM scorer, AC-44.05 fallback)
    # ------------------------------------------------------------------

    async def _score_qc05(
        self,
        report: PlaytestReport,
        seed: SeedManifest | None,
    ) -> CategoryScore:
        """Score genre fidelity via LLM call at temperature=0."""
        if self._llm is None or seed is None:
            reason = "no LLM client" if self._llm is None else "no seed manifest"
            return CategoryScore(
                category_id=QC_GENRE_FIDELITY,
                score=None,
                status="not_evaluated",
                sources=["automated"],
                notes=f"QC-05 not evaluated: {reason}.",
            )

        narrative_fragments = _sample_narratives(report, n=5)
        if not narrative_fragments:
            return CategoryScore(
                category_id=QC_GENRE_FIDELITY,
                score=None,
                status="not_evaluated",
                sources=["automated"],
                notes="QC-05 not evaluated: no narrative turns.",
            )

        comp = seed.composition
        theme_names = [t.name for t in comp.themes] if comp.themes else []
        tone_str = comp.tone.primary
        if comp.tone.secondary:
            tone_str += f" / {comp.tone.secondary}"

        for attempt in range(2):
            try:
                result = await self._call_genre_scorer(
                    primary_genre=comp.primary_genre,
                    themes=theme_names,
                    tone=tone_str,
                    fragments=narrative_fragments,
                )
                score_raw = result["score"]  # 1–5 int
                rationale = result.get("rationale", "")
                score_normalized = (score_raw - 1) / 4.0
                return CategoryScore(
                    category_id=QC_GENRE_FIDELITY,
                    score=max(0.0, min(1.0, score_normalized)),
                    status="scored",
                    sources=["automated"],
                    notes=f"LLM score {score_raw}/5: {rationale}",
                )
            except Exception as exc:
                log.warning(
                    "QC-05 genre scorer attempt %d failed: %s",
                    attempt + 1,
                    exc,
                )

        return CategoryScore(
            category_id=QC_GENRE_FIDELITY,
            score=None,
            status="failed",
            sources=["automated"],
            notes="QC-05 LLM scorer failed after 2 attempts.",
        )

    async def _call_genre_scorer(
        self,
        primary_genre: str,
        themes: list[str],
        tone: str,
        fragments: list[str],
    ) -> dict:
        """Issue the genre-fidelity LLM call and parse JSON response."""
        from tta.llm.client import GenerationParams, Message, MessageRole
        from tta.llm.roles import ModelRole

        fragments_text = "\n\n".join(
            f"[Fragment {i + 1}]\n{f}" for i, f in enumerate(fragments)
        )
        themes_str = ", ".join(themes) if themes else "(none specified)"

        prompt = (
            "You are evaluating a text adventure narrative for genre fidelity.\n"
            f"The declared genre is: {primary_genre}\n"
            f"The declared themes are: {themes_str}\n"
            f"The declared tone is: {tone}\n\n"
            f"{fragments_text}\n\n"
            "Score 1–5. Respond in JSON: "
            '{"score": <int>, "rationale": "<one sentence>"}'
        )

        assert self._llm is not None, "_call_genre_scorer requires LLM client"
        params = GenerationParams(temperature=0.0, max_tokens=128)
        response = await self._llm.generate(
            role=ModelRole.GENERATION,
            messages=[Message(role=MessageRole.USER, content=prompt)],
            params=params,
        )

        payload = json.loads(response.content)
        score = int(payload["score"])
        if not (1 <= score <= 5):
            raise ValueError(f"genre scorer returned out-of-range score: {score}")
        return payload

    # ------------------------------------------------------------------
    # QC-06 — Consequence weight (mixed)
    # ------------------------------------------------------------------

    def _score_qc06(
        self,
        report: PlaytestReport,
        feedback: FeedbackRecord | None,
        consequence_count: int,
        expected_consequence_turns: int | None,
    ) -> CategoryScore:
        """Score consequence weight from records count and human feedback."""
        expected = (
            expected_consequence_turns
            if expected_consequence_turns is not None
            else max(1, report.gameplay_turns_completed)
        )
        auto_ratio = min(1.0, consequence_count / expected) if expected > 0 else 0.0

        if feedback is not None:
            score = 0.6 * auto_ratio + 0.4 * feedback.consequence_normalized
            sources = ["automated", "human"]
            notes = (
                f"consequence_count={consequence_count}/{expected} "
                f"(ratio={auto_ratio:.3f}), "
                f"human_q_consequence={feedback.q_consequence}"
            )
        else:
            score = auto_ratio
            sources = ["automated"]
            notes = (
                f"consequence_count={consequence_count}/{expected} "
                f"(ratio={auto_ratio:.3f}); no human data."
            )

        return CategoryScore(
            category_id=QC_CONSEQUENCE_WEIGHT,
            score=max(0.0, min(1.0, score)),
            status="scored",
            sources=sources,
            notes=notes,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _count_contradictions(report: PlaytestReport, character_name: str) -> int:
    """Count narrative contradictions via rule-based checks.

    Rules:
    1. If character_name is supplied, check for turns where narrative is
       non-empty but character name is absent after the first two turns.
    2. Count turns where the agent marked coherence < 0.4 (strong signal
       of detected inconsistency beyond the scoring already done in QC-01).
    """
    count = 0

    # Rule 1: character name disappears from gameplay narratives
    if character_name:
        gameplay_turns = [
            t for t in report.turns if t.phase == "gameplay" and t.narrative.strip()
        ]
        if len(gameplay_turns) > 2:
            later_turns = gameplay_turns[2:]
            absent = sum(
                1
                for t in later_turns
                if character_name.lower() not in t.narrative.lower()
            )
            if absent > len(later_turns) // 2:
                count += 1

    # Rule 2: agent-assessed incoherence (turns rated below threshold)
    incoherent_turns = sum(
        1
        for t in report.turns
        if t.commentary is not None and t.commentary.coherence_rating < 0.4
    )
    count += incoherent_turns // 2  # Every 2 flagged turns counts as 1 contradiction

    return count


def _check_first_turn_character(
    report: PlaytestReport,
    character_name: str,
    traits: list[str],
) -> tuple[float, str]:
    """Check if the first gameplay turn narrative establishes character.

    Returns (score 0.0 or 1.0, notes).
    AC-44.03: auto = 0.0 if character name absent; notes mention enforcement miss.
    """
    gameplay_turns = [t for t in report.turns if t.phase == "gameplay"]
    if not gameplay_turns:
        return 0.5, "No gameplay turns; cannot assess character depth."

    first_narrative = gameplay_turns[0].narrative.lower()

    if not character_name:
        return 0.5, "No genesis_character_name supplied; skipping name check."

    has_name = character_name.lower() in first_narrative

    if traits:
        trait_hits = sum(1 for tr in traits if tr.lower() in first_narrative)
        has_trait = trait_hits > 0
    else:
        has_trait = True  # No traits to check

    if not has_name:
        # AC-44.03: auto component is 0.0 and notes mention enforcement miss
        return (
            0.0,
            "AC-2.3 enforcement miss: character name absent from first gameplay turn.",
        )

    if not has_trait:
        return 0.5, "Character name present but no trait phrases found in first turn."

    return 1.0, "Character name and trait phrase confirmed in first gameplay turn."


def _sample_narratives(report: PlaytestReport, n: int = 5) -> list[str]:
    """Sample up to n narrative fragments spread across the run."""
    gameplay = [
        t for t in report.turns if t.phase == "gameplay" and t.narrative.strip()
    ]
    if not gameplay:
        return []
    if len(gameplay) <= n:
        return [t.narrative[:500] for t in gameplay]
    step = len(gameplay) / n
    indices = [int(i * step) for i in range(n)]
    return [gameplay[i].narrative[:500] for i in indices]


def _compute_composite(categories: list[CategoryScore]) -> float:
    """Compute weighted composite score, redistributing absent weights."""
    evaluated = {c.category_id: c for c in categories if c.is_evaluated()}
    if not evaluated:
        return 0.0

    total_weight = sum(CATEGORY_WEIGHTS[cid] for cid in evaluated)
    if total_weight == 0.0:
        return 0.0

    weighted_sum = sum(
        CATEGORY_WEIGHTS[cid] * (c.score if c.score is not None else 0.0)
        for cid, c in evaluated.items()
    )
    return round(weighted_sum / total_weight, 4)


def _compute_verdict(
    categories: list[CategoryScore],
    composite: float,
) -> tuple[Verdict, list[str]]:
    """Determine pass / fail / inconclusive and collect fail reasons."""
    not_evaluated_count = sum(1 for c in categories if not c.is_evaluated())

    if not_evaluated_count >= INCONCLUSIVE_MIN_NOT_EVALUATED:
        return "inconclusive", []

    fail_reasons: list[str] = []

    if composite < PASS_COMPOSITE_THRESHOLD:
        fail_reasons.append(
            f"Composite score {composite:.4f} below "
            f"threshold {PASS_COMPOSITE_THRESHOLD}."
        )

    for c in categories:
        if (
            c.is_evaluated()
            and c.score is not None
            and c.score < FAIL_INDIVIDUAL_THRESHOLD
        ):
            fail_reasons.append(
                f"{c.category_id} score {c.score:.4f} below "
                f"minimum {FAIL_INDIVIDUAL_THRESHOLD}."
            )

    if fail_reasons:
        return "fail", fail_reasons

    return "pass", []
