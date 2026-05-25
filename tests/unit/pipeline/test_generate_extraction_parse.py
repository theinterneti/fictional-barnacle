from __future__ import annotations

import json


class TestParseExtractionResponse:
    def test_parses_clean_json_payload(self) -> None:
        from tta.pipeline.stages.generate import _parse_extraction_response

        payload = json.dumps(
            {
                "world_changes": [
                    {
                        "entity": "door",
                        "attribute": "state",
                        "old_value": "closed",
                        "new_value": "open",
                        "reason": "Player turned the handle",
                    }
                ],
                "suggested_actions": ["Step through", "Listen carefully", "Look back"],
            }
        )

        parsed = _parse_extraction_response(payload)

        assert isinstance(parsed, dict)
        assert parsed["world_changes"][0]["entity"] == "door"
        assert parsed["suggested_actions"] == [
            "Step through",
            "Listen carefully",
            "Look back",
        ]

    def test_extracts_json_from_markdown_fence(self) -> None:
        from tta.pipeline.stages.generate import _parse_extraction_response

        payload = (
            "```json\n"
            "{\n"
            '  "world_changes": [{"entity": "passageway", "attribute": "visibility", '
            '"old_value": "hidden", "new_value": "visible", '
            '"reason": "A hidden latch released"}],\n'
            '  "suggested_actions": ['
            '"Enter the passage", "Inspect the latch", "Call out"]\n'
            "}\n"
            "```"
        )

        parsed = _parse_extraction_response(payload)

        assert isinstance(parsed, dict)
        assert parsed["world_changes"][0]["entity"] == "passageway"
        assert parsed["suggested_actions"][2] == "Call out"

    def test_extracts_json_object_from_surrounding_text(self) -> None:
        from tta.pipeline.stages.generate import _parse_extraction_response

        payload = (
            "I found the result below.\n"
            '{"world_changes": [{"entity": "torch", "attribute": "state", '
            '"old_value": "unlit", "new_value": "lit", '
            '"reason": "The player struck flint"}], '
            '"suggested_actions": ["Advance", "Study the room", "Put out the torch"]}'
            "\nUse it carefully."
        )

        parsed = _parse_extraction_response(payload)

        assert isinstance(parsed, dict)
        assert parsed["world_changes"][0]["new_value"] == "lit"
        assert parsed["suggested_actions"][0] == "Advance"

    def test_returns_none_for_unparseable_output(self) -> None:
        from tta.pipeline.stages.generate import _parse_extraction_response

        assert _parse_extraction_response("") is None
        assert _parse_extraction_response("not json at all") is None
        assert _parse_extraction_response("```json\n{broken\n```") is None
