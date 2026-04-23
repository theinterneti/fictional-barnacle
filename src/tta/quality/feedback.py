"""S43 stub — FeedbackRecord for human playtester evaluations.

This module provides the FeedbackRecord data structure that S44 consumes.
S43 (Human Playtester Program) is not yet fully implemented; this stub
defines the interface contract that S43 must satisfy.

All rating fields use a 1–5 scale (float), normalized to 0.0–1.0 by S44.
"""

from __future__ import annotations

from dataclasses import dataclass


def _normalize(rating: float) -> float:
    """Normalize a 1–5 human rating to 0.0–1.0 (S44 score/5 rule)."""
    return max(0.0, min(1.0, rating / 5.0))


@dataclass
class FeedbackRecord:
    """Human playtester feedback for a single run (S43 stub).

    Fields:
        run_id: matches PlaytestReport.run_id
        q_wonder: "How wondrous / surprising was the story?" (1–5)
        q_consequence: "Did your choices feel impactful?" (1–5)
        q_character: "Did NPCs feel like distinct personalities?" (1–5)
    """

    run_id: str
    q_wonder: float  # 1–5 scale
    q_consequence: float  # 1–5 scale
    q_character: float  # 1–5 scale

    @property
    def wonder_normalized(self) -> float:
        return _normalize(self.q_wonder)

    @property
    def consequence_normalized(self) -> float:
        return _normalize(self.q_consequence)

    @property
    def character_normalized(self) -> float:
        return _normalize(self.q_character)
