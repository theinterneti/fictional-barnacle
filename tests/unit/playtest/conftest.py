"""Shared fixtures for playtester unit tests."""

from __future__ import annotations

import json
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
        **kwargs: Any,
    ) -> LLMResponse:  # type: ignore[override]
        self._call_count += 1
        is_commentary = self._call_count % 2 == 0
        content = (
            _commentary_json(coherence_rating=self._coherence_rating)
            if is_commentary
            else self._player_response
        )
        self.call_history.append(
            {
                "method": "generate",
                "role": role,
                "messages": messages,
                "params": params,
                **{k: v for k, v in kwargs.items() if v is not None},
            }
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
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_history.append(
            {"method": "stream", "role": role, "messages": messages, "params": params}
        )
        return LLMResponse(
            content=self._player_response,
            model_used="mock",
            token_count=TokenCount(
                prompt_tokens=0, completion_tokens=0, total_tokens=0
            ),
            latency_ms=0.0,
        )


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
) -> MagicMock:
    """Build a MagicMock that mimics httpx.AsyncClient for playtester tests."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    post_turn_count: list[int] = [0]
    stream_payloads: dict[str, list[str]] = {}

    async def _mock_post(url: str, *, json: Any = None, **kwargs: Any) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.raise_for_status = MagicMock()
        url_str = str(url)
        if url_str.endswith("/api/v1/auth/anonymous"):
            resp.status_code = 201
            resp.json.return_value = {
                "data": {
                    "access_token": "test-token",
                    "player": {"player_id": "player-1", "handle": "eval-smoke"},
                }
            }
        elif "turns" in url_str:
            post_turn_count[0] += 1
            turn_number = post_turn_count[0]
            turn_id = f"turn-{turn_number}"
            stream_url = f"/api/v1/games/{game_id}/stream"
            narrative_event = (
                "event: narrative\n"
                f'data: {{"turn_id": "{turn_id}", '
                f'"text": "Narrative for turn {turn_number}."}}\n\n'
            )
            end_event = (
                "event: narrative_end\n"
                f'data: {{"turn_id": "{turn_id}", "total_chunks": 1}}\n\n'
            )
            stream_payloads[turn_id] = [narrative_event, end_event]
            resp.status_code = 202
            resp.json.return_value = {
                "data": {
                    "turn_id": turn_id,
                    "turn_number": turn_number,
                    "stream_url": stream_url,
                }
            }
        else:
            resp.status_code = 201
            resp.json.return_value = {
                "data": {
                    "game_id": game_id,
                    "narrative_intro": intro_narrative,
                    "status": "active",
                }
            }
        return resp

    async def _mock_request(method: str, url: str, **kwargs: Any) -> MagicMock:
        if method.upper() == "POST":
            return await _mock_post(url, **kwargs)
        if method.upper() == "PATCH":
            return await _mock_patch(url, **kwargs)
        raise AssertionError(f"Unexpected request method: {method} {url}")

    def _mock_stream(method: str, url: str, **kwargs: Any) -> MagicMock:
        del method, url, kwargs
        turn_id = sorted(stream_payloads)[-1] if stream_payloads else ""
        payloads = stream_payloads.get(turn_id, [])

        response = MagicMock()
        response.status_code = 200
        response.headers = {}
        response.raise_for_status = MagicMock()

        async def _aiter_lines():
            for raw_event in payloads:
                for line in raw_event.splitlines():
                    yield line
                yield ""

        response.aiter_lines = _aiter_lines

        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=response)
        stream_cm.__aexit__ = AsyncMock(return_value=None)
        return stream_cm

    async def _mock_get(url: str, **kwargs: Any) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"data": []}
        return resp

    async def _mock_patch(url: str, *, json: Any = None, **kwargs: Any) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "data": {
                "consent_version": "1.0",
                "consent_accepted_at": "2026-01-01T00:00:00Z",
                "consent_categories": {"core_gameplay": True, "llm_processing": True},
            }
        }
        return resp

    mock_client.post = AsyncMock(side_effect=_mock_post)
    mock_client.get = AsyncMock(side_effect=_mock_get)
    mock_client.patch = AsyncMock(side_effect=_mock_patch)
    mock_client.request = AsyncMock(side_effect=_mock_request)
    mock_client.stream = MagicMock(side_effect=_mock_stream)
    return mock_client


@pytest.fixture
def http_mock() -> MagicMock:
    return _make_http_mock()
