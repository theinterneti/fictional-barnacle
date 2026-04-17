"""Tests for SSE event models."""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from tta.models.events import (
    ErrorEvent,
    EventType,
    HeartbeatEvent,
    KeepaliveEvent,
    LocationChangeEvent,
    NarrativeBlockEvent,
    NarrativeEndEvent,
    NarrativeEvent,
    NarrativeTokenEvent,
    StateUpdateEvent,
    TurnCompleteEvent,
    TurnStartEvent,
    WorldUpdateEvent,
)
from tta.models.world import WorldChange, WorldChangeType


class TestEventTypeEnum:
    """EventType enum coverage."""

    def test_has_all_fifteen_values(self) -> None:
        # 9 legacy-only + 1 shared (error) + 5 new S10 §6.2 = 15 total
        assert len(EventType) == 15

    def test_values(self) -> None:
        expected = {
            # Legacy (plans-based, kept for backwards compat)
            "turn_start",
            "narrative_token",
            "narrative_block",
            "world_update",
            "turn_complete",
            "keepalive",
            "thinking",
            "still_thinking",
            "moderation",
            # S10 §6.2 canonical
            "narrative",
            "narrative_end",
            "state_update",
            "location_change",
            "heartbeat",
            # Shared
            "error",
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
                type=WorldChangeType.PLAYER_MOVED,
                entity_id="loc-1",
                payload={"name": "Cave"},
            ),
            WorldChange(
                type=WorldChangeType.ITEM_TAKEN,
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
                type=WorldChangeType.NPC_STATE_CHANGED,
                entity_id="npc-7",
            )
        ]
        evt = WorldUpdateEvent(changes=changes)
        sse = evt.format_sse()
        data_line = sse.split("data: ", 1)[1].rstrip("\n")
        parsed = json.loads(data_line)
        assert len(parsed["changes"]) == 1
        assert parsed["changes"][0]["entity_id"] == "npc-7"


# ---------------------------------------------------------------------------
# S10 §6.2 canonical event types
# ---------------------------------------------------------------------------


class TestNarrativeEvent:
    """NarrativeEvent streams a sentence-aligned chunk with sequence counter."""

    def test_instantiation(self) -> None:
        evt = NarrativeEvent(text="The forest is dark.", turn_id="t-1", sequence=0)
        assert evt.event_type == EventType.NARRATIVE
        assert evt.text == "The forest is dark."
        assert evt.turn_id == "t-1"
        assert evt.sequence == 0

    def test_sequence_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            NarrativeEvent(text="x", turn_id="t-1", sequence=-1)

    def test_format_sse_wire_name(self) -> None:
        evt = NarrativeEvent(text="Hello.", turn_id="t-1", sequence=0)
        sse = evt.format_sse(1)
        assert sse.startswith("id: 1\nevent: narrative\n")

    def test_format_sse_data_excludes_event_type(self) -> None:
        evt = NarrativeEvent(text="Hello.", turn_id="t-1", sequence=0)
        sse = evt.format_sse()
        data_line = sse.split("data: ", 1)[1].rstrip("\n")
        parsed = json.loads(data_line)
        assert parsed["text"] == "Hello."
        assert parsed["turn_id"] == "t-1"
        assert parsed["sequence"] == 0
        assert "event_type" not in parsed


class TestNarrativeEndEvent:
    """NarrativeEndEvent signals all narrative chunks for a turn were sent."""

    def test_instantiation(self) -> None:
        evt = NarrativeEndEvent(turn_id="t-1", total_chunks=3)
        assert evt.event_type == EventType.NARRATIVE_END
        assert evt.turn_id == "t-1"
        assert evt.total_chunks == 3

    def test_zero_chunks_on_empty_narrative(self) -> None:
        evt = NarrativeEndEvent(turn_id="t-1", total_chunks=0)
        assert evt.total_chunks == 0

    def test_format_sse_wire_name(self) -> None:
        evt = NarrativeEndEvent(turn_id="t-1", total_chunks=0)
        sse = evt.format_sse()
        assert sse.startswith("event: narrative_end\n")

    def test_format_sse_data_excludes_event_type(self) -> None:
        evt = NarrativeEndEvent(turn_id="t-1", total_chunks=2)
        sse = evt.format_sse()
        data_line = sse.split("data: ", 1)[1].rstrip("\n")
        parsed = json.loads(data_line)
        assert parsed["turn_id"] == "t-1"
        assert parsed["total_chunks"] == 2
        assert "event_type" not in parsed


class TestStateUpdateEvent:
    """StateUpdateEvent is a spec-compliant rename of WorldUpdateEvent."""

    def test_event_type_is_state_update(self) -> None:
        evt = StateUpdateEvent(changes=[])
        assert evt.event_type == EventType.STATE_UPDATE

    def test_inherits_changes_field(self) -> None:
        changes = [WorldChange(type=WorldChangeType.PLAYER_MOVED, entity_id="loc-2")]
        evt = StateUpdateEvent(changes=changes)
        assert len(evt.changes) == 1
        assert evt.changes[0].entity_id == "loc-2"

    def test_format_sse_wire_name_and_excludes_event_type(self) -> None:
        evt = StateUpdateEvent(changes=[])
        sse = evt.format_sse()
        assert sse.startswith("event: state_update\n")
        data_line = sse.split("data: ", 1)[1].rstrip("\n")
        parsed = json.loads(data_line)
        assert parsed["changes"] == []
        assert "event_type" not in parsed


class TestLocationChangeEvent:
    """LocationChangeEvent carries the full destination location payload."""

    def test_instantiation(self) -> None:
        evt = LocationChangeEvent(
            location_id="loc-5",
            name="Dark Cave",
            description="A dark cave.",
            exits=["north", "south"],
        )
        assert evt.event_type == EventType.LOCATION_CHANGE
        assert evt.location_id == "loc-5"
        assert evt.name == "Dark Cave"
        assert evt.exits == ["north", "south"]

    def test_format_sse_wire_name(self) -> None:
        evt = LocationChangeEvent(
            location_id="loc-5",
            name="Cave",
            description="dark.",
            exits=[],
        )
        sse = evt.format_sse()
        assert sse.startswith("event: location_change\n")

    def test_format_sse_data_excludes_event_type(self) -> None:
        evt = LocationChangeEvent(
            location_id="loc-5",
            name="Cave",
            description="dark.",
            exits=["east"],
        )
        sse = evt.format_sse()
        data_line = sse.split("data: ", 1)[1].rstrip("\n")
        parsed = json.loads(data_line)
        assert parsed["location_id"] == "loc-5"
        assert parsed["exits"] == ["east"]
        assert "event_type" not in parsed


class TestHeartbeatEvent:
    """HeartbeatEvent keeps idle SSE connections alive (S10 §6.2, FR-10.38)."""

    def test_event_type(self) -> None:
        evt = HeartbeatEvent()
        assert evt.event_type == EventType.HEARTBEAT

    def test_auto_timestamp_is_utc_aware(self) -> None:
        evt = HeartbeatEvent()
        assert isinstance(evt.timestamp, datetime)
        assert evt.timestamp.tzinfo is not None

    def test_format_sse_wire_name(self) -> None:
        evt = HeartbeatEvent()
        sse = evt.format_sse()
        assert sse.startswith("event: heartbeat\n")

    def test_format_sse_data_excludes_event_type(self) -> None:
        evt = HeartbeatEvent()
        sse = evt.format_sse()
        data_line = sse.split("data: ", 1)[1].rstrip("\n")
        parsed = json.loads(data_line)
        assert "timestamp" in parsed
        assert "event_type" not in parsed
