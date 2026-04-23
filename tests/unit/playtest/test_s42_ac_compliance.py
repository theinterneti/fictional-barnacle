"""AC compliance tests for S42 — LLM Playtester Agent Harness.

AC markers follow the AC-NN.MM format required by the traceability standard.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tests.unit.playtest.conftest import _AlternatingMockLLM, _make_http_mock
from tta.playtest.agent import (
    MAX_CONSECUTIVE_TIMEOUTS,
    PLAYTEST_MIN_TURNS,
    PlaytesterAgent,
)
from tta.playtest.profile import TasteProfile

# ---------------------------------------------------------------------------
# AC-42.01 — Completes a minimum-turn session
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-42.01")
async def test_ac42_01_complete_session() -> None:
    """Agent runs curious-explorer/seed=42 to completion (>= PLAYTEST_MIN_TURNS)."""
    agent = PlaytesterAgent(
        api_base_url="http://test", llm_client=_AlternatingMockLLM()
    )
    agent.setup("seed-cosmos", "curious-explorer", run_seed=42)
    http_mock = _make_http_mock()

    with patch("tta.playtest.agent.httpx.AsyncClient", return_value=http_mock):
        report = await agent.run()

    assert report.status == "complete"
    assert report.gameplay_turns_completed >= PLAYTEST_MIN_TURNS


# ---------------------------------------------------------------------------
# AC-42.02 — Commentary fields within bounds on every completed turn
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-42.02")
async def test_ac42_02_turn_commentary_bounds() -> None:
    """Every non-timed-out turn has agent_intent != '' and coherence_rating in [0,1]."""
    agent = PlaytesterAgent(
        api_base_url="http://test", llm_client=_AlternatingMockLLM()
    )
    agent.setup("seed-cosmos", "curious-explorer", run_seed=42)
    http_mock = _make_http_mock()

    with patch("tta.playtest.agent.httpx.AsyncClient", return_value=http_mock):
        report = await agent.run()

    completed = [t for t in report.turns if not t.timed_out]
    assert len(completed) >= PLAYTEST_MIN_TURNS
    for turn in completed:
        assert turn.commentary.agent_intent != ""
        assert 0.0 <= turn.commentary.coherence_rating <= 1.0


# ---------------------------------------------------------------------------
# AC-42.03 — Same seeds → identical player inputs
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-42.03")
async def test_ac42_03_reproducibility() -> None:
    """Two runs with identical seeds produce the same player_input sequence."""
    agent1 = PlaytesterAgent(
        api_base_url="http://test", llm_client=_AlternatingMockLLM()
    )
    agent1.setup("seed-cosmos", "curious-explorer", run_seed=7, persona_jitter_seed=0)
    with patch("tta.playtest.agent.httpx.AsyncClient", return_value=_make_http_mock()):
        report1 = await agent1.run()

    agent2 = PlaytesterAgent(
        api_base_url="http://test", llm_client=_AlternatingMockLLM()
    )
    agent2.setup("seed-cosmos", "curious-explorer", run_seed=7, persona_jitter_seed=0)
    with patch("tta.playtest.agent.httpx.AsyncClient", return_value=_make_http_mock()):
        report2 = await agent2.run()

    inputs1 = [t.player_input for t in report1.turns if not t.timed_out]
    inputs2 = [t.player_input for t in report2.turns if not t.timed_out]
    assert inputs1 == inputs2
    assert len(inputs1) >= PLAYTEST_MIN_TURNS


# ---------------------------------------------------------------------------
# AC-42.04 — Low verbosity injects brevity constraint
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-42.04")
async def test_ac42_04_verbosity_brevity_constraint() -> None:
    """verbosity=0.05 → all player-input system prompts include '8 words'."""
    mock_llm = _AlternatingMockLLM()
    agent = PlaytesterAgent(api_base_url="http://test", llm_client=mock_llm)
    agent.setup("seed-cosmos", "curious-explorer", run_seed=42)
    # Override profile AFTER setup() to guarantee verbosity well below 0.1 threshold.
    agent._profile = TasteProfile(  # type: ignore[attr-defined]
        verbosity=0.05,
        boldness=0.3,
        curiosity=0.4,
        genre_affinity="any",
        tone_affinity="neutral",
    )
    http_mock = _make_http_mock()

    with patch("tta.playtest.agent.httpx.AsyncClient", return_value=http_mock):
        await agent.run()

    # Player-input LLM calls land at even indices (call_count odd ⇒ 0,2,4,…).
    player_input_calls = [
        mock_llm.call_history[i] for i in range(0, len(mock_llm.call_history), 2)
    ]
    assert len(player_input_calls) >= PLAYTEST_MIN_TURNS
    for call in player_input_calls:
        system_content = call["messages"][0].content
        assert "8 words" in system_content


# ---------------------------------------------------------------------------
# AC-42.05 — Three consecutive timeouts → abandoned
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-42.05")
async def test_ac42_05_consecutive_timeout_abandonment() -> None:
    """MAX_CONSECUTIVE_TIMEOUTS consecutive timeouts produce an abandoned report."""
    agent = PlaytesterAgent(
        api_base_url="http://test", llm_client=_AlternatingMockLLM()
    )
    agent.setup("seed-cosmos", "curious-explorer", run_seed=42)
    http_mock = _make_http_mock()

    # Patch the async method to always raise TimeoutError.
    execute_mock = AsyncMock(side_effect=asyncio.TimeoutError)

    with patch("tta.playtest.agent.httpx.AsyncClient", return_value=http_mock):
        with patch.object(agent, "_execute_turn", execute_mock):
            report = await agent.run()

    assert report.status == "abandoned"
    assert report.gameplay_turns_completed == 0
    assert execute_mock.call_count == MAX_CONSECUTIVE_TIMEOUTS
