"""Tests for tta.api.sse — SSE formatting utilities."""

import json

from tta.api.sse import SSECounter, format_sse


class TestSSECounter:
    def test_first_id_is_one(self) -> None:
        counter = SSECounter()
        assert counter.next_id() == 1

    def test_increments(self) -> None:
        counter = SSECounter()
        ids = [counter.next_id() for _ in range(5)]
        assert ids == [1, 2, 3, 4, 5]


class TestFormatSSE:
    def test_basic_event(self) -> None:
        result = format_sse("connected", {"game_id": "abc"}, event_id=1)
        assert result.startswith("id: 1\n")
        assert "event: connected\n" in result
        assert result.endswith("\n\n")
        # Parse the data line
        data_line = [line for line in result.split("\n") if line.startswith("data:")][0]
        payload = json.loads(data_line[len("data: ") :])
        assert payload == {"game_id": "abc"}

    def test_without_event_id(self) -> None:
        result = format_sse("keepalive", {"ts": "2024-01-01"})
        assert not result.startswith("id:")
        assert "event: keepalive\n" in result

    def test_multiline_data(self) -> None:
        # JSON with newlines (unlikely but contractually supported)
        data = {"text": "line1"}
        result = format_sse("test", data, event_id=42)
        assert "id: 42\n" in result
        assert "event: test\n" in result
