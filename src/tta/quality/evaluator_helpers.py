"""Narrative quality evaluator helpers — scoring, sampling, verdicts.

Extracted from evaluator.py during code health decomposition.
"""

from __future__ import annotations

from tta.playtest.report import PlaytestReport
from tta.quality.models import (
    CATEGORY_WEIGHTS,
    FAIL_INDIVIDUAL_THRESHOLD,
    INCONCLUSIVE_MIN_NOT_EVALUATED,
    PASS_COMPOSITE_THRESHOLD,
    CategoryScore,
    Verdict,
)

# Human-readable labels for quality category IDs
CATEGORY_LABELS: dict[str, str] = {
    "QC_COHERENCE": "Coherence",
    "QC_TENSION": "Tension",
    "QC_WONDER": "Wonder",
    "QC_CHARACTER_DEPTH": "Character Depth",
    "QC_GENRE_FIDELITY": "Genre Fidelity",
    "QC_CONSEQUENCE_WEIGHT": "Consequence Weight",
}


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
            label = CATEGORY_LABELS.get(c.category_id, c.category_id)
            fail_reasons.append(
                f"{c.category_id} {label} below threshold "
                f"(score {c.score:.4f} < {FAIL_INDIVIDUAL_THRESHOLD:.4f})"
            )

    if fail_reasons:
        return "fail", fail_reasons

    return "pass", []
