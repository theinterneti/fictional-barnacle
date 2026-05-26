"""Pure-function unit tests for tta.playtest module helpers.

These tests exercise edge cases of module-level functions without
needing async infrastructure or mocked HTTP/LLM.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tta.llm.serving_profiles import GenerationTrafficClass
from tta.playtest.agent import (
    DEFAULT_PLAYER_INPUT,
    MAX_PLAYER_INPUT_CHARS,
    _blank_commentary,
    _boldness_description,
    _normalize_player_input,
    _parse_commentary,
    _verbosity_description,
)
from tta.playtest.profile import get_taste_profile

# ---------------------------------------------------------------------------
# _parse_commentary — fallback on malformed JSON
# ---------------------------------------------------------------------------


def test_parse_commentary_malformed_json() -> None:
    """Invalid JSON falls back to safe defaults with coherence_rating=0.5."""
    c = _parse_commentary(0, "not valid json!!!")

    assert c.coherence_rating == 0.5
    assert c.surprise_level == 0.5
    assert c.coherence_note == "(commentary parse error)"
    assert c.agent_intent == "not valid json!!!"[:200]


def test_parse_commentary_empty_string() -> None:
    """Empty content falls back; agent_intent is empty string."""
    c = _parse_commentary(1, "")

    assert c.coherence_rating == 0.5
    assert c.agent_intent == ""


def test_normalize_player_input_empty_falls_back() -> None:
    """Whitespace-only LLM output becomes a safe default turn."""
    assert _normalize_player_input("   \n\t  ") == DEFAULT_PLAYER_INPUT


def test_normalize_player_input_truncates_to_api_limit() -> None:
    """Generated input is capped to the SubmitTurnRequest max_length."""
    normalized = _normalize_player_input("x" * (MAX_PLAYER_INPUT_CHARS + 25))

    assert len(normalized) == MAX_PLAYER_INPUT_CHARS
    assert normalized == "x" * MAX_PLAYER_INPUT_CHARS


def test_parse_commentary_fenced_json() -> None:
    """Markdown-fenced JSON block is stripped and parsed correctly."""
    data = {
        "agent_intent": "look around the room",
        "surprise_level": 0.3,
        "surprise_note": "nothing unusual",
        "coherence_rating": 0.9,
        "coherence_note": "consistent",
    }
    fenced = f"```json\n{json.dumps(data)}\n```"

    c = _parse_commentary(2, fenced)

    assert c.agent_intent == "look around the room"
    assert c.surprise_level == pytest.approx(0.3)
    assert c.coherence_rating == pytest.approx(0.9)


def test_parse_commentary_valid_json() -> None:
    """Bare valid JSON round-trips without alteration."""
    data = {
        "agent_intent": "open the door",
        "surprise_level": 0.7,
        "surprise_note": "unexpected outcome",
        "coherence_rating": 0.6,
        "coherence_note": "plausible",
    }
    c = _parse_commentary(3, json.dumps(data))

    assert c.agent_intent == "open the door"
    assert c.surprise_level == pytest.approx(0.7)
    assert c.coherence_rating == pytest.approx(0.6)
    assert c.turn_index == 3


def test_parse_commentary_long_content_truncated() -> None:
    """agent_intent from parse error is truncated at 200 chars."""
    long_content = "x" * 300
    c = _parse_commentary(0, long_content)

    assert len(c.agent_intent) == 200


# ---------------------------------------------------------------------------
# _blank_commentary — timeout sentinel
# ---------------------------------------------------------------------------


def test_blank_commentary_fields() -> None:
    """_blank_commentary returns correct sentinel values for timeout turns."""
    c = _blank_commentary(3)

    assert c.turn_index == 3
    assert c.agent_intent == "(turn timed out)"
    assert c.coherence_rating == 0.0
    assert c.surprise_level == 0.0


@pytest.mark.asyncio
async def test_run_reuses_created_game_without_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ANON_GAME_LIMIT recovery reuses an internal 'created' game directly."""
    from tta.llm.client import LLMResponse
    from tta.models.turn import TokenCount
    from tta.playtest.agent import PlaytesterAgent

    class _DummyLLM:
        async def generate(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            del args, kwargs
            return LLMResponse(
                content="look around",
                model_used="dummy",
                token_count=TokenCount(
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                ),
                latency_ms=0.0,
            )

    class _FakeResponse:
        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code = status_code
            self._payload = payload
            self.headers: dict[str, str] = {}

        def json(self) -> dict:
            return self._payload

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    agent = PlaytesterAgent("http://example.test", _DummyLLM())
    agent.setup("seed-1", "curious-explorer", 123)

    request_log: list[tuple[str, str]] = []
    request_payloads: dict[tuple[str, str], dict] = {}
    game_id = "11111111-1111-1111-1111-111111111111"

    async def _fake_request_with_backoff(self, client, method, url, **kwargs):  # type: ignore[no-untyped-def]
        del self, client
        request_log.append((method, url))
        request_payloads[(method, url)] = kwargs.get("json") or {}
        if (method, url) == ("POST", "/api/v1/auth/anonymous"):
            return _FakeResponse(200, {"data": {"access_token": "tok"}})
        if (method, url) == ("PATCH", "/api/v1/players/me/consent"):
            return _FakeResponse(200, {"data": {"ok": True}})
        if (method, url) == ("POST", "/api/v1/games"):
            return _FakeResponse(403, {"error": {"code": "ANON_GAME_LIMIT"}})
        if (method, url) == ("POST", f"/api/v1/games/{game_id}/turns"):
            return _FakeResponse(
                202,
                {
                    "data": {
                        "turn_id": "turn-1",
                        "stream_url": f"/api/v1/games/{game_id}/stream",
                    }
                },
            )
        raise AssertionError(f"unexpected request: {(method, url)!r}")

    async def _fake_consume_turn_stream(self, client, stream_url, turn_id):  # type: ignore[no-untyped-def]
        del self, client, stream_url, turn_id
        return "You see a quiet tavern."

    async def _fake_generate_player_input(self, narrative, turn_index, temperature):  # type: ignore[no-untyped-def]
        del self, narrative, turn_index, temperature
        return "Look around"

    async def _fake_generate_commentary(  # type: ignore[no-untyped-def]
        self, turn_index, prev_narrative, player_input, narrative_output
    ):
        del self, prev_narrative, player_input, narrative_output
        return SimpleNamespace(
            turn_index=turn_index,
            agent_intent="look around",
            surprise_level=0.1,
            surprise_note="steady",
            coherence_rating=0.9,
            coherence_note="coherent",
        )

    monkeypatch.setattr(
        "tta.playtest.agent.PLAYTEST_MIN_TURNS",
        1,
    )
    monkeypatch.setattr(
        "tta.playtest.agent.PlaytesterAgent._request_with_backoff",
        _fake_request_with_backoff,
    )
    monkeypatch.setattr(
        "tta.playtest.agent.PlaytesterAgent._consume_turn_stream",
        _fake_consume_turn_stream,
    )
    monkeypatch.setattr(
        "tta.playtest.agent.PlaytesterAgent._generate_player_input",
        _fake_generate_player_input,
    )
    monkeypatch.setattr(
        "tta.playtest.agent.PlaytesterAgent._generate_commentary",
        _fake_generate_commentary,
    )

    class _ListClient:
        headers: dict[str, str] = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str):
            request_log.append(("GET", url))
            if url == "/api/v1/games":
                return _FakeResponse(
                    200,
                    {
                        "data": [
                            {
                                "game_id": game_id,
                                "status": "active",
                            }
                        ]
                    },
                )
            if url == f"/api/v1/games/{game_id}":
                return _FakeResponse(
                    200,
                    {
                        "data": {
                            "game_id": game_id,
                            "status": "created",
                            "recent_turns": [],
                        }
                    },
                )
            raise AssertionError(f"unexpected GET: {url!r}")

    monkeypatch.setattr(
        "tta.playtest.agent.httpx.AsyncClient",
        lambda *a, **k: _ListClient(),
    )

    report = await agent.run()

    assert report.status == "complete"
    assert report.game_id == game_id
    assert ("GET", f"/api/v1/games/{game_id}") in request_log
    assert ("POST", f"/api/v1/games/{game_id}/resume") not in request_log
    turn_request = ("POST", f"/api/v1/games/{game_id}/turns")
    assert turn_request in request_log
    assert request_payloads[turn_request]["traffic_class"] == (
        GenerationTrafficClass.BULK_EVAL.value
    )


# ---------------------------------------------------------------------------
# get_taste_profile — unknown persona raises KeyError
# ---------------------------------------------------------------------------


def test_get_taste_profile_unknown_id() -> None:
    with pytest.raises(KeyError):
        get_taste_profile("no-such-persona-xyz", 0)


# ---------------------------------------------------------------------------
# _verbosity_description — boundary parametrize
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verbosity,expected_fragment",
    [
        (0.0, "extremely terse"),
        (0.1, "extremely terse"),
        (0.11, "very brief"),
        (0.35, "very brief"),
        (0.36, "moderate"),
        (0.65, "moderate"),
        (0.66, "detailed"),
        (0.85, "detailed"),
        (0.86, "elaborate"),
        (1.0, "elaborate"),
    ],
)
def test_verbosity_description(verbosity: float, expected_fragment: str) -> None:
    desc = _verbosity_description(verbosity)
    assert expected_fragment in desc.lower()


# ---------------------------------------------------------------------------
# _boldness_description — boundary parametrize
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "boldness,expected_fragment",
    [
        (0.0, "cautious"),
        (0.25, "cautious"),
        (0.26, "somewhat cautious"),
        (0.5, "somewhat cautious"),
        (0.51, "boldly"),
        (0.75, "boldly"),
        (0.76, "impulsive"),
        (1.0, "impulsive"),
    ],
)
def test_boldness_description(boldness: float, expected_fragment: str) -> None:
    desc = _boldness_description(boldness)
    assert expected_fragment in desc.lower()
