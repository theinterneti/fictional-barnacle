"""Unit tests for ContextSummaryService (S27 FR-27.20–FR-27.22)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tta.game.summary import ContextSummaryService


def _mock_response(content: str) -> SimpleNamespace:
    """Build a minimal object mimicking litellm.acompletion() return."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


@pytest.fixture
def svc() -> ContextSummaryService:
    return ContextSummaryService(model="test-model")


class TestGenerateTitle:
    @pytest.mark.asyncio
    async def test_returns_trimmed_title(self, svc: ContextSummaryService) -> None:
        with patch("tta.game.summary.litellm.acompletion", new_callable=AsyncMock) as m:
            m.return_value = _mock_response("  The Dark Forest  ")
            title = await svc.generate_title("You awaken in a dark forest.")
        assert title == "The Dark Forest"

    @pytest.mark.asyncio
    async def test_uses_configured_model(self, svc: ContextSummaryService) -> None:
        with patch("tta.game.summary.litellm.acompletion", new_callable=AsyncMock) as m:
            m.return_value = _mock_response("Title")
            await svc.generate_title("narrative")
        assert m.call_args.kwargs["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_truncates_long_narrative(self, svc: ContextSummaryService) -> None:
        long_text = "x" * 5000
        with patch("tta.game.summary.litellm.acompletion", new_callable=AsyncMock) as m:
            m.return_value = _mock_response("Title")
            await svc.generate_title(long_text)
        user_msg = m.call_args.kwargs["messages"][1]["content"]
        assert len(user_msg) == 2000

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty(
        self, svc: ContextSummaryService
    ) -> None:
        with patch("tta.game.summary.litellm.acompletion", new_callable=AsyncMock) as m:
            m.return_value = _mock_response("")
            title = await svc.generate_title("narrative")
        assert title == ""

    @pytest.mark.asyncio
    async def test_none_content_returns_empty(self, svc: ContextSummaryService) -> None:
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        )
        with patch("tta.game.summary.litellm.acompletion", new_callable=AsyncMock) as m:
            m.return_value = resp
            title = await svc.generate_title("narrative")
        assert title == ""

    @pytest.mark.asyncio
    async def test_default_model_fallback(self) -> None:
        svc = ContextSummaryService(model="")
        with patch("tta.game.summary.litellm.acompletion", new_callable=AsyncMock) as m:
            m.return_value = _mock_response("T")
            await svc.generate_title("x")
        assert m.call_args.kwargs["model"] == "openai/gpt-4o-mini"


class TestGenerateContextSummary:
    @pytest.mark.asyncio
    async def test_returns_summary(self, svc: ContextSummaryService) -> None:
        turns = [
            {"player_input": "go north", "narrative_output": "You head north."},
            {"player_input": "look", "narrative_output": "A dark cave."},
        ]
        with patch("tta.game.summary.litellm.acompletion", new_callable=AsyncMock) as m:
            m.return_value = _mock_response("Player explored north to a cave.")
            summary = await svc.generate_context_summary(turns)
        assert summary == "Player explored north to a cave."

    @pytest.mark.asyncio
    async def test_truncates_summary_to_200_chars(
        self, svc: ContextSummaryService
    ) -> None:
        with patch("tta.game.summary.litellm.acompletion", new_callable=AsyncMock) as m:
            m.return_value = _mock_response("x" * 300)
            summary = await svc.generate_context_summary([{"player_input": "hi"}])
        assert len(summary) == 200

    @pytest.mark.asyncio
    async def test_uses_last_10_turns(self, svc: ContextSummaryService) -> None:
        turns = [
            {"player_input": f"t{i}", "narrative_output": f"n{i}"} for i in range(20)
        ]
        with patch("tta.game.summary.litellm.acompletion", new_callable=AsyncMock) as m:
            m.return_value = _mock_response("summary")
            await svc.generate_context_summary(turns)
        transcript = m.call_args.kwargs["messages"][1]["content"]
        assert "t10" in transcript
        assert "t0" not in transcript

    @pytest.mark.asyncio
    async def test_handles_missing_keys(self, svc: ContextSummaryService) -> None:
        turns = [{"other_key": "val"}]
        with patch("tta.game.summary.litellm.acompletion", new_callable=AsyncMock) as m:
            m.return_value = _mock_response("ok")
            summary = await svc.generate_context_summary(turns)
        assert summary == "ok"

    @pytest.mark.asyncio
    async def test_llm_error_propagates(self, svc: ContextSummaryService) -> None:
        """Callers handle errors — service lets them propagate."""
        with patch("tta.game.summary.litellm.acompletion", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("LLM down")
            with pytest.raises(RuntimeError, match="LLM down"):
                await svc.generate_context_summary([{"player_input": "hi"}])
