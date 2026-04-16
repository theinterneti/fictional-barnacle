"""Unit tests for SSE replay groundwork utilities."""

from __future__ import annotations

from tta.api.sse_replay import SSEReplayBuffer, parse_last_event_id


class TestParseLastEventId:
    def test_none_returns_none(self) -> None:
        assert parse_last_event_id(None) is None

    def test_blank_returns_none(self) -> None:
        assert parse_last_event_id("   ") is None

    def test_invalid_returns_none(self) -> None:
        assert parse_last_event_id("abc") is None

    def test_non_positive_returns_none(self) -> None:
        assert parse_last_event_id("0") is None
        assert parse_last_event_id("-1") is None

    def test_valid_positive_int(self) -> None:
        assert parse_last_event_id("42") == 42
        assert parse_last_event_id(" 7 ") == 7


class TestSSEReplayBuffer:
    def test_replays_events_after_id(self) -> None:
        buf = SSEReplayBuffer(min_events=3, min_seconds=300.0)
        buf.append(1, "e1")
        buf.append(2, "e2")
        buf.append(3, "e3")

        status, payloads = buf.events_after(1)
        assert status == "hit"
        assert payloads == ["e2", "e3"]

    def test_returns_unavailable_when_id_older_than_buffer(
        self, monkeypatch
    ) -> None:
        ticks = iter([0.0, 10.0, 20.0])
        monkeypatch.setattr("tta.api.sse_replay.monotonic", lambda: next(ticks))
        buf = SSEReplayBuffer(min_events=2, min_seconds=0.0001)
        buf.append(1, "e1")
        buf.append(2, "e2")
        buf.append(3, "e3")

        status, payloads = buf.events_after(1)
        assert status == "unavailable"
        assert payloads == []

    def test_keeps_at_least_min_events_even_if_old(self, monkeypatch) -> None:
        ticks = iter([0.0, 10.0, 20.0, 30.0])
        monkeypatch.setattr("tta.api.sse_replay.monotonic", lambda: next(ticks))
        buf = SSEReplayBuffer(min_events=3, min_seconds=0.0001)
        buf.append(1, "e1")
        buf.append(2, "e2")
        buf.append(3, "e3")
        buf.append(4, "e4")

        # min_events=3 ensures at least 3 entries are retained.
        assert buf.size >= 3
        assert buf.newest_event_id == 4
