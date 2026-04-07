"""Tests for SSE event models."""

import json
from datetime import datetime

from tta.models.events import (
    ErrorEvent,
    EventType,
    KeepaliveEvent,
    NarrativeBlockEvent,
    NarrativeTokenEvent,
    TurnCompleteEvent,
    TurnStartEvent,
    WorldUpdateEvent,
)
from tta.models.world import WorldChange, WorldChangeType


class TestEventTypeEnum:
    """EventType enum coverage."""

    def test_has_all_nine_values(self) -> None:
        assert len(EventType) == 9

    def test_values(self) -> None:
        expected = {
            "turn_start",
            "narrative_token",
            "narrative_block",
            "world_update",
            "turn_complete",
            "error",
            "keepalive",
            "thinking",
            "still_thinking",
        }
        assert {e.value for e in EventType} == expected


class TestTurnStartEvent:
    """TurnStartEvent instantiation and defaults."""

    def test_instantiation(self) -> None:
        evt = TurnStartEvent(turn_number=1)
        assert evt.event_type == EventType.TURN_START
        assert evt.turn_number == 1

    def test_auto_generated_timestamp(self) -> None:
        evt = TurnStartEvent(turn_number=1)
        assert isinstance(evt.timestamp, datetime)
        assert evt.timestamp.tzinfo is not None


class TestNarrativeTokenEvent:
    """NarrativeTokenEvent instantiation."""

    def test_instantiation(self) -> None:
        evt = NarrativeTokenEvent(token="Hello")
        assert evt.event_type == EventType.NARRATIVE_TOKEN
        assert evt.token == "Hello"


class TestNarrativeBlockEvent:
    """NarrativeBlockEvent instantiation."""

    def test_instantiation(self) -> None:
        evt = NarrativeBlockEvent(full_text="A dark forest.")
        assert evt.event_type == EventType.NARRATIVE_BLOCK
        assert evt.full_text == "A dark forest."


class TestWorldUpdateEvent:
    """WorldUpdateEvent with WorldChange list."""

    def test_instantiation_with_changes(self) -> None:
        changes = [
            WorldChange(
                type=WorldChangeType.location_entered,
                entity_id="loc-1",
                payload={"name": "Cave"},
            ),
            WorldChange(
                type=WorldChangeType.item_picked_up,
                entity_id="item-42",
            ),
        ]
        evt = WorldUpdateEvent(changes=changes)
        assert evt.event_type == EventType.WORLD_UPDATE
        assert len(evt.changes) == 2
        assert evt.changes[0].entity_id == "loc-1"

    def test_empty_changes(self) -> None:
        evt = WorldUpdateEvent(changes=[])
        assert evt.changes == []


class TestTurnCompleteEvent:
    """TurnCompleteEvent instantiation."""

    def test_instantiation(self) -> None:
        evt = TurnCompleteEvent(
            turn_number=3,
            model_used="gpt-4o",
            latency_ms=142.5,
        )
        assert evt.event_type == EventType.TURN_COMPLETE
        assert evt.turn_number == 3
        assert evt.model_used == "gpt-4o"
        assert evt.latency_ms == 142.5


class TestErrorEvent:
    """ErrorEvent instantiation."""

    def test_instantiation(self) -> None:
        evt = ErrorEvent(code="RATE_LIMITED", message="slow down")
        assert evt.event_type == EventType.ERROR
        assert evt.code == "RATE_LIMITED"
        assert evt.message == "slow down"


class TestKeepaliveEvent:
    """KeepaliveEvent has empty payload."""

    def test_instantiation(self) -> None:
        evt = KeepaliveEvent()
        assert evt.event_type == EventType.KEEPALIVE

    def test_empty_payload(self) -> None:
        evt = KeepaliveEvent()
        data = evt.model_dump(exclude={"event_type"})
        assert data == {}


class TestFormatSSE:
    """format_sse() produces valid SSE wire format."""

    def test_wire_format_structure(self) -> None:
        evt = NarrativeTokenEvent(token="Hi")
        sse = evt.format_sse()
        assert sse.startswith("event: narrative_token\n")
        assert "data: " in sse
        assert sse.endswith("\n\n")

    def test_data_is_valid_json(self) -> None:
        evt = TurnCompleteEvent(
            turn_number=1,
            model_used="gpt-4o",
            latency_ms=100.0,
        )
        sse = evt.format_sse()
        data_line = sse.split("data: ", 1)[1].rstrip("\n")
        parsed = json.loads(data_line)
        assert parsed["turn_number"] == 1
        assert parsed["model_used"] == "gpt-4o"

    def test_event_type_excluded_from_data(self) -> None:
        evt = KeepaliveEvent()
        sse = evt.format_sse()
        data_line = sse.split("data: ", 1)[1].rstrip("\n")
        parsed = json.loads(data_line)
        assert "event_type" not in parsed

    def test_keepalive_sse_format(self) -> None:
        evt = KeepaliveEvent()
        sse = evt.format_sse()
        assert sse == "event: keepalive\ndata: {}\n\n"

    def test_world_update_serializes_changes(self) -> None:
        changes = [
            WorldChange(
                type=WorldChangeType.npc_moved,
                entity_id="npc-7",
            )
        ]
        evt = WorldUpdateEvent(changes=changes)
        sse = evt.format_sse()
        data_line = sse.split("data: ", 1)[1].rstrip("\n")
        parsed = json.loads(data_line)
        assert len(parsed["changes"]) == 1
        assert parsed["changes"][0]["entity_id"] == "npc-7"
