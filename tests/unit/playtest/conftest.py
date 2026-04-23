"""Shared fixtures for playtester unit tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tta.llm.client import GenerationParams, LLMResponse, Message
from tta.llm.roles import ModelRole
from tta.models.turn import TokenCount

# ---------------------------------------------------------------------------
# LLM mock helpers
# ---------------------------------------------------------------------------


def _commentary_json(
    *,
    agent_intent: str = "explore the area",
    surprise_level: float = 0.4,
    surprise_note: str = "nothing unusual",
    coherence_rating: float = 0.7,
    coherence_note: str = "response fits narrative",
) -> str:
    return json.dumps(
        {
            "agent_intent": agent_intent,
            "surprise_level": surprise_level,
            "surprise_note": surprise_note,
            "coherence_rating": coherence_rating,
            "coherence_note": coherence_note,
        }
    )


class _AlternatingMockLLM:
    """Returns player-input response on odd calls, commentary JSON on even calls."""

    def __init__(
        self,
        player_response: str = "I look around carefully.",
        coherence_rating: float = 0.7,
    ) -> None:
        self._player_response = player_response
        self._coherence_rating = coherence_rating
        self.call_history: list[dict[str, Any]] = []
        self._call_count = 0

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:  # type: ignore[override]
        self._call_count += 1
        is_commentary = self._call_count % 2 == 0
        content = (
            _commentary_json(coherence_rating=self._coherence_rating)
            if is_commentary
            else self._player_response
        )
        self.call_history.append(
            {"method": "generate", "role": role, "messages": messages, "params": params}
        )
        return LLMResponse(
            content=content,
            model_used="mock",
            token_count=TokenCount(
                prompt_tokens=0, completion_tokens=0, total_tokens=0
            ),
            latency_ms=0.0,
        )

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> AsyncIterator[str]:
        raise NotImplementedError


@pytest.fixture
def mock_llm() -> _AlternatingMockLLM:
    return _AlternatingMockLLM()


# ---------------------------------------------------------------------------
# HTTP mock helpers
# ---------------------------------------------------------------------------

_GAME_ID = "game-abc-123"
_INTRO_NARRATIVE = "You stand at a misty bus stop. Rain taps the shelter roof."


def _make_http_mock(
    game_id: str = _GAME_ID,
    intro_narrative: str = _INTRO_NARRATIVE,
    turns_to_serve: int = 5,
    simulate_timeout_turns: set[int] | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics httpx.AsyncClient for playtester tests."""
    simulate_timeout_turns = simulate_timeout_turns or set()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    # Track turn submissions independently from GET polls
    post_turn_count: list[int] = [0]
    # Build a list of all turns submitted so GET can see them
    submitted_turns: list[dict[str, Any]] = []

    async def _mock_post(url: str, *, json: Any = None, **kwargs: Any) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "turns" in str(url):
            post_turn_count[0] += 1
            turn_number = post_turn_count[0]
            submitted_turns.append(
                {
                    "turn_number": turn_number,
                    "narrative_output": f"Narrative for turn {turn_number}.",
                    "status": "complete",
                }
            )
            resp.json.return_value = {
                "data": {
                    "turn_id": f"turn-{turn_number}",
                    "turn_number": turn_number,
                    "stream_url": "",
                }
            }
        else:
            # POST /games
            resp.json.return_value = {
                "data": {
                    "game_id": game_id,
                    "narrative_intro": intro_narrative,
                    "status": "active",
                }
            }
        return resp

    async def _mock_get(url: str, **kwargs: Any) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"data": list(submitted_turns)}
        return resp

    mock_client.post = AsyncMock(side_effect=_mock_post)
    mock_client.get = AsyncMock(side_effect=_mock_get)
    return mock_client


@pytest.fixture
def http_mock() -> MagicMock:
    return _make_http_mock()
