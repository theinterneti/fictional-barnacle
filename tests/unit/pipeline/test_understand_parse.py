"""Tests for structured JSON output parsing in classification pipeline.

Decision #5: prompt-based JSON + Pydantic model_validate + 1 retry.
"""

import json

import pytest

from tta.models.turn import ParsedIntent


class TestParseClassificationResponse:
    """JSON extraction and ParsedIntent validation from LLM raw output."""

    def test_parses_clean_json(self) -> None:
        """Well-formed JSON from cooperative model returns ParsedIntent."""
        from tta.pipeline.stages.understand import _parse_classification_response

        content = json.dumps(
            {
                "intent": "examine",
                "confidence": 0.85,
                "entities": ["rusty key", "locked door"],
                "emotional_tone": "curious",
                "summary": "Player wants to inspect items in the room",
            }
        )
        result = _parse_classification_response(content)
        assert result is not None
        assert result.intent == "examine"
        assert result.confidence == 0.85
        assert result.entities == ["rusty key", "locked door"]
        assert result.emotional_tone == "curious"
        assert result.summary == "Player wants to inspect items in the room"

    def test_extracts_json_from_markdown_fence(self) -> None:
        """JSON wrapped in ```json fences is extracted."""
        from tta.pipeline.stages.understand import _parse_classification_response

        content = (
            "Here is the classification:\n"
            "```json\n"
            '{"intent":"move","confidence":0.9,'
            '"entities":["north","cave"],'
            '"emotional_tone":"determined",'
            '"summary":"Player wants to travel north"}\n'
            "```"
        )
        result = _parse_classification_response(content)
        assert result is not None
        assert result.intent == "move"
        assert result.confidence == 0.9
        assert result.entities == ["north", "cave"]

    def test_extracts_json_from_bare_object_in_text(self) -> None:
        """JSON object floating in other text is extracted."""
        from tta.pipeline.stages.understand import _parse_classification_response

        content = (
            'I think the answer is {"intent":"talk",'
            '"confidence":0.7,"entities":["bartender"],'
            '"emotional_tone":"friendly","summary":"Chatting with NPC"}'
            " and that's my final answer."
        )
        result = _parse_classification_response(content)
        assert result is not None
        assert result.intent == "talk"
        assert result.entities == ["bartender"]

    def test_returns_none_for_unparseable_output(self) -> None:
        """Garbage output returns None (trigger retry)."""
        from tta.pipeline.stages.understand import _parse_classification_response

        assert _parse_classification_response("I'm not sure what you want") is None
        assert _parse_classification_response("") is None
        assert _parse_classification_response("{invalid json") is None

    def test_returns_none_for_missing_required_fields(self) -> None:
        """JSON without 'intent' field returns None."""
        from tta.pipeline.stages.understand import _parse_classification_response

        result = _parse_classification_response('{"confidence":0.5}')
        assert result is None

    def test_backward_compatible_old_fields(self) -> None:
        """Old ParsedIntent fields (entities=dict) are not accepted."""
        from tta.pipeline.stages.understand import _parse_classification_response

        # Old format with entities as dict should fail validation
        content = json.dumps(
            {
                "intent": "meta",
                "confidence": 0.8,
                "entities": {"type": "help"},
            }
        )
        result = _parse_classification_response(content)
        # entities should be list[str] — dict fails
        assert result is None
