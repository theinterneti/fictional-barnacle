"""Tests for Wave 18: observability metrics, input validation, resume recap.

Covers:
  - Task 1: RATE_LIMIT_ENFORCED / ABUSE_DETECTED counters
  - Task 2: DB query duration / Redis operations helpers
  - Task 4: Zero-width character stripping in SubmitTurnRequest
  - Task 5: FR-5.4 resume contextual recap
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tta.observability.metrics import (
    ABUSE_DETECTED,
    DB_QUERY_DURATION,
    RATE_LIMIT_ENFORCED,
    REDIS_OPERATIONS,
    REGISTRY,
)


def _sample_value(
    sample_name: str,
    labels: dict[str, str],
) -> float:
    """Read a specific sample value from the custom REGISTRY by name + labels.

    Iterates all collected metrics and selects by exact sample name
    (e.g. ``tta_rate_limit_enforced_total``) rather than relying on
    sample ordering, which is not guaranteed across prometheus_client
    versions.
    """
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == sample_name and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# Task 1: Rate limit & abuse metric counters
# ---------------------------------------------------------------------------


class TestRateLimitEnforcedCounter:
    """RATE_LIMIT_ENFORCED increments when a request is rate-limited."""

    def test_counter_registered_with_route_label(self) -> None:
        assert RATE_LIMIT_ENFORCED._labelnames == ("route",)

    def test_counter_increments(self) -> None:
        labels = {"route": "/test"}
        before = _sample_value("tta_rate_limit_enforced_total", labels)
        RATE_LIMIT_ENFORCED.labels(route="/test").inc()
        after = _sample_value("tta_rate_limit_enforced_total", labels)
        assert after == before + 1


class TestAbuseDetectedCounter:
    """ABUSE_DETECTED increments when violations exceed threshold."""

    def test_counter_registered_with_pattern_label(self) -> None:
        assert ABUSE_DETECTED._labelnames == ("pattern",)

    def test_counter_increments_for_rapid_fire(self) -> None:
        labels = {"pattern": "rapid_fire"}
        before = _sample_value("tta_abuse_detected_total", labels)
        ABUSE_DETECTED.labels(pattern="rapid_fire").inc()
        after = _sample_value("tta_abuse_detected_total", labels)
        assert after == before + 1


class TestAbuseDetectorEmitsMetric:
    """InMemoryAbuseDetector.record_violation increments ABUSE_DETECTED."""

    @pytest.mark.asyncio
    async def test_counter_fires_on_threshold_breach(self) -> None:
        from tta.resilience.anti_abuse import AbusePattern, InMemoryAbuseDetector

        detector = InMemoryAbuseDetector(max_cooldown=86400)
        key = f"ip:{uuid4()}"

        labels = {"pattern": "rapid_fire"}
        before = _sample_value("tta_abuse_detected_total", labels)

        # Push past threshold (3)
        for _ in range(4):
            await detector.record_violation(key, AbusePattern.RAPID_FIRE)

        after = _sample_value("tta_abuse_detected_total", labels)
        assert after > before


# ---------------------------------------------------------------------------
# Task 2: DB query duration & Redis operations helpers
# ---------------------------------------------------------------------------


class TestObserveDbQuery:
    """observe_db_query records duration to histogram."""

    @pytest.mark.asyncio
    async def test_records_duration(self) -> None:
        from tta.observability.db_metrics import observe_db_query

        labels = {"database": "postgresql", "operation": "test_op"}
        before = _sample_value("tta_db_query_duration_seconds_sum", labels)

        async with observe_db_query("postgresql", "test_op"):
            await asyncio.sleep(0.01)

        after = _sample_value("tta_db_query_duration_seconds_sum", labels)
        assert after > before

    @pytest.mark.asyncio
    async def test_records_on_exception(self) -> None:
        from tta.observability.db_metrics import observe_db_query

        labels = {"database": "postgresql", "operation": "err_op"}
        before = _sample_value("tta_db_query_duration_seconds_sum", labels)

        with pytest.raises(ValueError, match="boom"):
            async with observe_db_query("postgresql", "err_op"):
                raise ValueError("boom")

        after = _sample_value("tta_db_query_duration_seconds_sum", labels)
        assert after > before


class TestCountRedisOp:
    """count_redis_op increments the Redis operations counter."""

    def test_increments_counter(self) -> None:
        from tta.observability.db_metrics import count_redis_op

        labels = {"operation": "get"}
        before = _sample_value("tta_redis_operations_total", labels)

        with count_redis_op("get"):
            pass

        after = _sample_value("tta_redis_operations_total", labels)
        assert after == before + 1


class TestDbQueryDurationMetric:
    """DB_QUERY_DURATION histogram has correct labels and buckets."""

    def test_labels(self) -> None:
        assert DB_QUERY_DURATION._labelnames == ("database", "operation")

    def test_uses_duration_buckets(self) -> None:
        from tta.observability.metrics import DURATION_BUCKETS

        # Upper bounds include +Inf; the user-defined ones match DURATION_BUCKETS
        assert tuple(DB_QUERY_DURATION._upper_bounds) == (
            *DURATION_BUCKETS,
            float("inf"),
        )


class TestRedisOperationsMetric:
    """REDIS_OPERATIONS counter has correct labels."""

    def test_labels(self) -> None:
        assert REDIS_OPERATIONS._labelnames == ("operation",)


# ---------------------------------------------------------------------------
# Task 4: Zero-width character stripping
# ---------------------------------------------------------------------------


class TestSubmitTurnRequestValidation:
    """SubmitTurnRequest strips zero-width Unicode characters."""

    def _make(self, text: str) -> Any:
        from tta.api.routes.games import SubmitTurnRequest

        return SubmitTurnRequest(input=text)

    def test_normal_text_unchanged(self) -> None:
        req = self._make("go north")
        assert req.input == "go north"

    def test_strips_zero_width_space(self) -> None:
        req = self._make("go\u200bnorth")
        assert req.input == "gonorth"

    def test_strips_bom(self) -> None:
        req = self._make("\ufeffhello")
        assert req.input == "hello"

    def test_strips_zero_width_joiner(self) -> None:
        req = self._make("a\u200db")
        assert req.input == "ab"

    def test_strips_zero_width_non_joiner(self) -> None:
        req = self._make("a\u200cb")
        assert req.input == "ab"

    def test_strips_word_joiner(self) -> None:
        req = self._make("a\u2060b")
        assert req.input == "ab"

    def test_strips_multiple_zero_width(self) -> None:
        req = self._make("\u200b\u200c\u200d\u2060\ufefftest\ufffe")
        assert req.input == "test"

    def test_empty_string_passes_model_validation(self) -> None:
        """Model accepts empty string; route handler enforces non-empty (AC-23.11)."""
        req = self._make("")
        assert req.input == ""

    def test_whitespace_only_passes_through(self) -> None:
        """Whitespace-only input is valid (triggers nudge, not LLM call)."""
        req = self._make("   ")
        assert req.input == "   "

    def test_only_zero_width_chars_becomes_empty(self) -> None:
        req = self._make("\u200b\u200c\u200d")
        assert req.input == ""


# ---------------------------------------------------------------------------
# Task 5: Resume contextual recap (FR-5.4)
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_GAME_ID = uuid4()


def _settings() -> Any:
    from tta.config import Settings

    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


def _make_result(
    rows: list[dict[str, Any]] | None = None,
    *,
    scalar: Any = None,
) -> MagicMock:
    result = MagicMock()
    if rows is not None:
        objs = [SimpleNamespace(**r) for r in rows]
        result.one_or_none.return_value = objs[0] if objs else None
        result.all.return_value = objs
    else:
        result.one_or_none.return_value = None
        result.all.return_value = []
    if scalar is not None:
        result.scalar_one.return_value = scalar
    return result


def _game_row(
    *,
    status: str = "active",
    title: str | None = None,
    summary: str | None = None,
    last_played_at: datetime | None = _NOW,
    world_seed: Any = "{}",
    turn_count: int = 0,
    needs_recovery: bool = False,
    summary_generated_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "id": _GAME_ID,
        "player_id": _PLAYER_ID,
        "status": status,
        "world_seed": world_seed,
        "title": title,
        "summary": summary,
        "turn_count": turn_count,
        "needs_recovery": needs_recovery,
        "summary_generated_at": summary_generated_at,
        "created_at": _NOW,
        "updated_at": _NOW,
        "last_played_at": last_played_at,
        "deleted_at": deleted_at,
    }


class TestResumeRecap:
    """FR-5.4: Resume provides contextual recap."""

    @pytest.fixture()
    def pg(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture()
    def app(self, pg: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> Any:

        from tta.api.app import create_app
        from tta.api.deps import get_current_player, get_pg
        from tta.models.player import Player

        settings = _settings()
        monkeypatch.setattr("tta.api.routes.games.get_settings", lambda: settings)
        a = create_app(settings=settings)

        player = Player(id=_PLAYER_ID, handle="Tester", created_at=_NOW)

        async def _pg():
            yield pg

        a.dependency_overrides[get_pg] = _pg
        a.dependency_overrides[get_current_player] = lambda: player
        return a

    @pytest.fixture()
    def client(self, app: Any) -> Any:
        from fastapi.testclient import TestClient

        return TestClient(app)

    def test_recap_with_summary_and_turns(self, client: Any, pg: AsyncMock) -> None:
        """Games with turns and summary get 'When we last left off:' recap."""
        recent = datetime.now(UTC)
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(
                    [
                        _game_row(
                            status="active",
                            summary="Lost in the woods",
                            last_played_at=recent,
                            summary_generated_at=recent,
                        )
                    ]
                ),
                _make_result([]),  # recent turns
                _make_result(scalar=5),  # turn count
            ]
        )

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["recap"] == "When we last left off: Lost in the woods"

    def test_recap_zero_turns_with_genesis(self, client: Any, pg: AsyncMock) -> None:
        """Zero-turn games derive recap from genesis narrative_intro."""
        ws = {
            "genesis": {
                "world_id": "w1",
                "narrative_intro": "You awaken in a dark forest.",
            }
        }
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="paused", world_seed=ws)]),
                _make_result(),  # UPDATE status
                _make_result([]),  # recent turns
                _make_result(scalar=0),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["recap"] == "You awaken in a dark forest."

    def test_recap_none_when_no_summary_and_turns(
        self, client: Any, pg: AsyncMock
    ) -> None:
        """Games with turns but no summary have no recap."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active", summary=None)]),
                _make_result([]),  # recent turns
                _make_result(scalar=3),  # turn count
            ]
        )

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["recap"] is None

    def test_recap_none_zero_turns_no_genesis(self, client: Any, pg: AsyncMock) -> None:
        """Zero-turn games without genesis have no recap."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="paused", world_seed="{}")]),
                _make_result(),  # UPDATE status
                _make_result([]),  # recent turns
                _make_result(scalar=0),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["recap"] is None

    def test_recap_field_present_in_response(self, client: Any, pg: AsyncMock) -> None:
        """The recap field always appears in the response dict."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active")]),
                _make_result([]),  # recent turns
                _make_result(scalar=0),  # turn count
            ]
        )

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        assert "recap" in resp.json()["data"]
