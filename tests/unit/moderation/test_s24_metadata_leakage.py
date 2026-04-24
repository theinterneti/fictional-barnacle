"""Tests for moderation metadata leakage prevention (S24 AC-24.6).

ModerationEvent sent to the client must contain only a player-safe
``reason`` field — no verdict, category, confidence, or other internal
moderation details may leak.
"""

from __future__ import annotations

import json

import pytest

from tta.models.events import EventType, ModerationEvent


class TestModerationEventNoMetadataLeakage:
    """AC-24.6: No internal moderation details in client SSE events."""

    pytestmark = [pytest.mark.spec("AC-24.06")]

    def test_only_reason_in_payload(self) -> None:
        """Serialized event contains only event_type and reason."""
        evt = ModerationEvent(reason="Content was redirected.")
        data = evt.model_dump(exclude={"event_type"}, mode="json")

        assert set(data.keys()) == {"reason"}

    def test_no_verdict_field(self) -> None:
        """No 'verdict' in the serialized payload."""
        evt = ModerationEvent(reason="test")
        data = evt.model_dump(mode="json")

        assert "verdict" not in data

    def test_no_category_field(self) -> None:
        """No 'category' in the serialized payload."""
        evt = ModerationEvent(reason="test")
        data = evt.model_dump(mode="json")

        assert "category" not in data

    def test_no_confidence_field(self) -> None:
        """No 'confidence' in the serialized payload."""
        evt = ModerationEvent(reason="test")
        data = evt.model_dump(mode="json")

        assert "confidence" not in data

    def test_no_content_hash_field(self) -> None:
        """No 'content_hash' in the serialized payload."""
        evt = ModerationEvent(reason="test")
        data = evt.model_dump(mode="json")

        assert "content_hash" not in data

    def test_sse_wire_format_clean(self) -> None:
        """SSE wire format has no internal fields in the data line."""
        evt = ModerationEvent(reason="Content redirected.")
        wire = evt.format_sse(event_id=42)

        assert "event: moderation" in wire
        assert "id: 42" in wire

        # Parse the data line
        for line in wire.strip().split("\n"):
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                assert set(payload.keys()) == {"reason"}
                assert payload["reason"] == "Content redirected."
                break
        else:
            pytest.fail("No data line found in SSE output")

    def test_event_type_is_moderation(self) -> None:
        """ModerationEvent has the correct event_type."""
        evt = ModerationEvent(reason="test")
        assert evt.event_type == EventType.MODERATION
