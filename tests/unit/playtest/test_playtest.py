"""Pure-function unit tests for tta.playtest module helpers.

These tests exercise edge cases of module-level functions without
needing async infrastructure or mocked HTTP/LLM.
"""

from __future__ import annotations

import json

import pytest

from tta.playtest.agent import (
    _blank_commentary,
    _boldness_description,
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
