"""Tests for content moderation models (S24 FR-24.02–FR-24.05)."""

import pytest

from tta.moderation.models import (
    ALWAYS_BLOCK,
    DEFAULT_CATEGORY_ACTIONS,
    ContentCategory,
    ModerationContext,
    ModerationResult,
    ModerationVerdict,
)


class TestModerationVerdict:
    def test_enum_values(self) -> None:
        assert ModerationVerdict.PASS == "pass"
        assert ModerationVerdict.FLAG == "flag"
        assert ModerationVerdict.BLOCK == "block"

    def test_all_values(self) -> None:
        assert len(ModerationVerdict) == 3


class TestContentCategory:
    def test_has_ten_categories(self) -> None:
        assert len(ContentCategory) == 10

    def test_all_expected_categories(self) -> None:
        expected = {
            "safe",
            "mild_violence",
            "graphic_violence",
            "sexual_content",
            "self_harm",
            "hate_speech",
            "dangerous_activity",
            "personal_info",
            "off_topic",
            "prompt_injection",
        }
        assert {c.value for c in ContentCategory} == expected


class TestAlwaysBlock:
    def test_always_block_is_frozenset(self) -> None:
        assert isinstance(ALWAYS_BLOCK, frozenset)

    def test_always_block_contains_required_categories(self) -> None:
        required = {
            ContentCategory.GRAPHIC_VIOLENCE,
            ContentCategory.SEXUAL_CONTENT,
            ContentCategory.SELF_HARM,
            ContentCategory.HATE_SPEECH,
            ContentCategory.DANGEROUS_ACTIVITY,
            ContentCategory.PROMPT_INJECTION,
        }
        assert required == ALWAYS_BLOCK

    def test_safe_not_in_always_block(self) -> None:
        assert ContentCategory.SAFE not in ALWAYS_BLOCK

    def test_overridable_not_in_always_block(self) -> None:
        assert ContentCategory.MILD_VIOLENCE not in ALWAYS_BLOCK
        assert ContentCategory.PERSONAL_INFO not in ALWAYS_BLOCK
        assert ContentCategory.OFF_TOPIC not in ALWAYS_BLOCK


class TestDefaultCategoryActions:
    def test_safe_defaults_to_pass(self) -> None:
        assert DEFAULT_CATEGORY_ACTIONS[ContentCategory.SAFE] == ModerationVerdict.PASS

    def test_mild_violence_defaults_to_pass(self) -> None:
        assert (
            DEFAULT_CATEGORY_ACTIONS[ContentCategory.MILD_VIOLENCE]
            == ModerationVerdict.PASS
        )

    def test_personal_info_defaults_to_flag(self) -> None:
        assert (
            DEFAULT_CATEGORY_ACTIONS[ContentCategory.PERSONAL_INFO]
            == ModerationVerdict.FLAG
        )

    def test_off_topic_defaults_to_flag(self) -> None:
        assert (
            DEFAULT_CATEGORY_ACTIONS[ContentCategory.OFF_TOPIC]
            == ModerationVerdict.FLAG
        )


class TestModerationResult:
    def test_basic_construction(self) -> None:
        r = ModerationResult(
            verdict=ModerationVerdict.PASS,
            category=ContentCategory.SAFE,
            confidence=1.0,
            reason="safe",
        )
        assert r.verdict == ModerationVerdict.PASS
        assert r.content_hash == ""

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValueError, match="greater than or equal to 0"):
            ModerationResult(
                verdict=ModerationVerdict.PASS,
                category=ContentCategory.SAFE,
                confidence=-0.1,
                reason="bad",
            )

    def test_confidence_upper_bound(self) -> None:
        with pytest.raises(ValueError, match="less than or equal to 1"):
            ModerationResult(
                verdict=ModerationVerdict.PASS,
                category=ContentCategory.SAFE,
                confidence=1.1,
                reason="bad",
            )


class TestModerationContext:
    def test_defaults(self) -> None:
        ctx = ModerationContext()
        assert ctx.game_id == ""
        assert ctx.player_id == ""
        assert ctx.turn_id == ""
        assert ctx.stage == ""

    def test_populated(self) -> None:
        ctx = ModerationContext(
            game_id="g1", player_id="p1", turn_id="3", stage="input"
        )
        assert ctx.stage == "input"
