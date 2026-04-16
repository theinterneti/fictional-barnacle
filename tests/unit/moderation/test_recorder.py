"""Tests for ModerationRecorder — record persistence (FR-24.09)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tta.moderation.models import (
    ContentCategory,
    ModerationRecord,
    ModerationVerdict,
)
from tta.moderation.recorder import ModerationRecorder


def _make_record(**overrides) -> ModerationRecord:
    defaults = {
        "turn_id": "t1",
        "game_id": "g1",
        "player_id": "p1",
        "stage": "input",
        "content_hash": "abc123",
        "content": "test content",
        "verdict": ModerationVerdict.BLOCK,
        "category": ContentCategory.SELF_HARM,
        "confidence": 0.95,
        "reason": "keyword match",
        "timestamp": datetime(2025, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ModerationRecord(**defaults)


class TestModerationRecorder:
    """Unit tests for ModerationRecorder."""

    @pytest.mark.asyncio
    async def test_save_executes_insert(self) -> None:
        mock_session = AsyncMock()
        mock_sf = MagicMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        recorder = ModerationRecorder(mock_sf)
        record = _make_record()

        await recorder.save(record)

        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_awaited_once()
        # Verify the SQL text contains the table name
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "moderation_records" in sql_text

    @pytest.mark.asyncio
    async def test_save_passes_all_fields(self) -> None:
        mock_session = AsyncMock()
        mock_sf = MagicMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        recorder = ModerationRecorder(mock_sf)
        record = _make_record()

        await recorder.save(record)

        params = mock_session.execute.call_args[0][1]
        assert params["turn_id"] == "t1"
        assert params["game_id"] == "g1"
        assert params["player_id"] == "p1"
        assert params["stage"] == "input"
        assert params["content_hash"] == "abc123"
        assert params["content"] == "test content"
        assert params["verdict"] == "block"
        assert params["category"] == "self_harm"
        assert params["confidence"] == 0.95

    @pytest.mark.asyncio
    async def test_save_logs_error_on_failure(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute.side_effect = RuntimeError("db down")
        mock_sf = MagicMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        recorder = ModerationRecorder(mock_sf)
        record = _make_record()

        with patch("tta.moderation.recorder.log") as mock_log:
            await recorder.save(record)
            mock_log.error.assert_called_once()
            assert mock_log.error.call_args[0][0] == "moderation_record_save_failed"
