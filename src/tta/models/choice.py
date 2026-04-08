"""Choice classification domain models.

Covers choice types, impact levels, and reversibility spectrum
defined in spec S05 (Choice & Consequence) FR-2, FR-5, FR-6.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ChoiceType(StrEnum):
    """Player choice categories (S05 FR-2).

    Every player input is classified into one or more categories.
    Refusal (doing nothing) is a first-class choice type.
    """

    ACTION = "action"
    DIALOGUE = "dialogue"
    MOVEMENT = "movement"
    STRATEGIC = "strategic"
    MORAL = "moral"
    REFUSAL = "refusal"


class ImpactLevel(StrEnum):
    """How significantly a choice affects the world (S05 FR-6).

    Min 30% of choices per session should be CONSEQUENTIAL or above.
    Impact level is NOT revealed to the player.
    """

    COSMETIC = "cosmetic"
    ATMOSPHERIC = "atmospheric"
    CONSEQUENTIAL = "consequential"
    PIVOTAL = "pivotal"
    DEFINING = "defining"


class Reversibility(StrEnum):
    """How reversible a choice's effects are (S05 FR-5)."""

    TRIVIAL = "trivial"
    MODERATE = "moderate"
    SIGNIFICANT = "significant"
    PERMANENT = "permanent"


class ChoiceClassification(BaseModel):
    """Result of classifying a player's input as a choice.

    Attached to TurnState after the understand stage.
    A single input may map to multiple choice types.
    """

    types: list[ChoiceType] = Field(min_length=1)
    impact: ImpactLevel = ImpactLevel.ATMOSPHERIC
    reversibility: Reversibility = Reversibility.MODERATE
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @property
    def primary_type(self) -> ChoiceType:
        """First type in the list is the primary classification."""
        return self.types[0]
