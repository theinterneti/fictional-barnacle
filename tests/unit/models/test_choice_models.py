"""Tests for choice classification domain models."""

from tta.models.choice import (
    ChoiceClassification,
    ChoiceType,
    ImpactLevel,
    Reversibility,
)


class TestChoiceType:
    """S05 FR-2: Six choice categories."""

    def test_all_six_types_exist(self) -> None:
        expected = {
            "action",
            "dialogue",
            "movement",
            "strategic",
            "moral",
            "refusal",
        }
        assert {t.value for t in ChoiceType} == expected

    def test_refusal_is_first_class(self) -> None:
        assert ChoiceType.REFUSAL == "refusal"

    def test_strenum_comparison(self) -> None:
        assert ChoiceType.ACTION == "action"
        assert ChoiceType.DIALOGUE != "action"


class TestImpactLevel:
    """S05 FR-6: Five impact levels, not revealed to player."""

    def test_all_five_levels_exist(self) -> None:
        expected = {
            "cosmetic",
            "atmospheric",
            "consequential",
            "pivotal",
            "defining",
        }
        assert {i.value for i in ImpactLevel} == expected

    def test_ordering_by_value(self) -> None:
        levels = sorted(ImpactLevel, key=lambda x: list(ImpactLevel).index(x))
        assert levels[0] == ImpactLevel.COSMETIC
        assert levels[-1] == ImpactLevel.DEFINING


class TestReversibility:
    """S05 FR-5: Reversibility spectrum."""

    def test_all_four_levels_exist(self) -> None:
        expected = {"trivial", "moderate", "significant", "permanent"}
        assert {r.value for r in Reversibility} == expected


class TestChoiceClassification:
    """S05 FR-2: Classification result attached to TurnState."""

    def test_minimal_classification(self) -> None:
        cc = ChoiceClassification(types=[ChoiceType.ACTION])
        assert cc.types == [ChoiceType.ACTION]
        assert cc.impact == ImpactLevel.ATMOSPHERIC
        assert cc.reversibility == Reversibility.MODERATE
        assert cc.confidence == 0.5

    def test_multiple_types(self) -> None:
        cc = ChoiceClassification(
            types=[ChoiceType.DIALOGUE, ChoiceType.MORAL],
            impact=ImpactLevel.PIVOTAL,
        )
        assert len(cc.types) == 2
        assert ChoiceType.MORAL in cc.types

    def test_requires_at_least_one_type(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ChoiceClassification(types=[])

    def test_confidence_bounds(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ChoiceClassification(types=[ChoiceType.ACTION], confidence=1.5)
        with pytest.raises(ValidationError):
            ChoiceClassification(types=[ChoiceType.ACTION], confidence=-0.1)

    def test_full_classification(self) -> None:
        cc = ChoiceClassification(
            types=[ChoiceType.MORAL, ChoiceType.DIALOGUE],
            impact=ImpactLevel.DEFINING,
            reversibility=Reversibility.PERMANENT,
            confidence=0.95,
        )
        assert cc.impact == ImpactLevel.DEFINING
        assert cc.reversibility == Reversibility.PERMANENT
        assert cc.confidence == 0.95
