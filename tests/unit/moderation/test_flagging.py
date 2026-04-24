"""Tests for SessionFlagTracker — session-level auto-flagging (FR-24.11)."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from tta.moderation.flagging import SessionFlagTracker


class TestSessionFlagTracker:
    """Unit tests for SessionFlagTracker."""

    pytestmark = [pytest.mark.spec("AC-24.08")]

    def test_below_threshold_returns_false(self) -> None:
        tracker = SessionFlagTracker(threshold=3, window_minutes=5)
        for _ in range(2):
            assert tracker.record_block("g1", "p1") is False

    def test_at_threshold_returns_true(self) -> None:
        tracker = SessionFlagTracker(threshold=3, window_minutes=5)
        tracker.record_block("g1", "p1")
        tracker.record_block("g1", "p1")
        assert tracker.record_block("g1", "p1") is True

    def test_above_threshold_does_not_retrigger(self) -> None:
        tracker = SessionFlagTracker(threshold=3, window_minutes=5)
        for _ in range(3):
            tracker.record_block("g1", "p1")
        # 4th block should NOT re-flag
        assert tracker.record_block("g1", "p1") is False

    def test_expired_entries_pruned(self) -> None:
        tracker = SessionFlagTracker(threshold=3, window_minutes=5)

        # Inject 2 old entries via direct manipulation
        old_time = datetime(2020, 1, 1, tzinfo=UTC)
        tracker._blocks["g1"] = [old_time, old_time]

        # New block should prune the old ones — count = 1
        assert tracker.record_block("g1", "p1") is False

    def test_different_games_tracked_independently(self) -> None:
        tracker = SessionFlagTracker(threshold=2, window_minutes=5)
        tracker.record_block("g1", "p1")
        tracker.record_block("g2", "p1")
        # Neither hit threshold=2 yet
        assert tracker.record_block("g1", "p1") is True
        assert tracker.record_block("g2", "p1") is True

    def test_reset_clears_tracking(self) -> None:
        tracker = SessionFlagTracker(threshold=2, window_minutes=5)
        tracker.record_block("g1", "p1")
        tracker.reset("g1")
        # Should restart from 0
        assert tracker.record_block("g1", "p1") is False

    def test_default_thresholds(self) -> None:
        tracker = SessionFlagTracker()
        assert tracker._threshold == 5
        assert tracker._window_minutes == 10

    def test_flag_emits_warning_log(self) -> None:
        tracker = SessionFlagTracker(threshold=1, window_minutes=5)
        with patch("tta.moderation.flagging.log") as mock_log:
            tracker.record_block("g1", "p1")
            mock_log.warning.assert_called_once()
            call_args = mock_log.warning.call_args
            assert call_args[0][0] == "moderation_session_flagged"
            assert call_args[1]["game_id"] == "g1"
            assert call_args[1]["player_id"] == "p1"
