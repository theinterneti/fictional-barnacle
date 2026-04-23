"""Tests for S34 — Diegetic Time (WorldTimeService + deliver integration).

AC coverage: AC-34.01 through AC-34.10
"""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tta.models.turn import TurnState, TurnStatus
from tta.pipeline.stages.deliver import deliver_stage
from tta.pipeline.types import PipelineDeps
from tta.simulation.types import TimeConfig, WorldTime
from tta.simulation.world_time import (
    DEFAULT_TOD_BOUNDARIES,
    WorldTimeService,
    compute_world_time,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides: object) -> TurnState:
    defaults: dict = {
        "session_id": uuid4(),
        "turn_number": 1,
        "player_input": "look around",
        "game_state": {},
    }
    defaults.update(overrides)
    return TurnState(**defaults)


def _make_deps(**overrides: object) -> PipelineDeps:
    base: dict = {
        "llm": AsyncMock(),
        "world": AsyncMock(),
        "session_repo": AsyncMock(),
        "turn_repo": AsyncMock(),
        "safety_pre_input": AsyncMock(),
        "safety_pre_gen": AsyncMock(),
        "safety_post_gen": AsyncMock(),
    }
    base.update(overrides)
    return PipelineDeps(**base)  # type: ignore[arg-type]


def _wt_dict(svc: WorldTimeService, ticks: int, cfg: TimeConfig | None = None) -> dict:
    """Helper: compute a world_time dict as stored in game_state."""
    wt = compute_world_time(ticks, cfg or TimeConfig())
    return dataclasses.asdict(wt)


# ---------------------------------------------------------------------------
# AC-34.01: Time advances by one tick per normal turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.spec("AC-34.01")
async def test_deliver_advances_world_time_one_tick() -> None:
    """Successful deliver increments total_ticks by ticks_per_turn (default=1)."""
    svc = WorldTimeService()
    initial_wt = _wt_dict(svc, 10)
    state = _make_state(
        narrative_output="The forest rustles.",
        game_state={"world_time": initial_wt},
    )
    deps = _make_deps(world_time_service=svc)

    result = await deliver_stage(state, deps)

    assert result.game_state["world_time"]["total_ticks"] == 11
    assert result.status == TurnStatus.complete


# ---------------------------------------------------------------------------
# AC-34.02: WorldTime initialised from universe config on first session
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-34.02")
def test_initial_world_time_starting_hour_8() -> None:
    """initial_world_time() at tick=0 with starting_hour=8 → hour=8, day=0, morning."""
    svc = WorldTimeService()
    cfg = TimeConfig(starting_hour=8, starting_day=0)
    wt = svc.initial_world_time(cfg)

    assert wt.total_ticks == 0
    assert wt.day_count == 0
    assert wt.hour == 8
    assert wt.minute == 0
    assert wt.time_of_day_label == "morning"


@pytest.mark.spec("AC-34.02")
def test_initial_world_time_returns_WorldTime_instance() -> None:
    """initial_world_time always returns a WorldTime dataclass."""
    svc = WorldTimeService()
    wt = svc.initial_world_time()
    assert isinstance(wt, WorldTime)
    assert wt.total_ticks == 0


# ---------------------------------------------------------------------------
# AC-34.03: New session inherits canonical universe time
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-34.03")
def test_tick_from_inherited_tick_5() -> None:
    """tick(5) treats 5 as the starting point; delta.from_tick=5, to_tick=6."""
    svc = WorldTimeService()
    delta = svc.tick(current_ticks=5)

    assert delta.from_tick == 5
    assert delta.to_tick == 6
    assert delta.world_time.total_ticks == 6
    assert not delta.was_capped


# ---------------------------------------------------------------------------
# AC-34.04: compute_world_time is deterministic
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-34.04")
def test_compute_world_time_deterministic() -> None:
    """Calling compute_world_time with identical inputs yields identical WorldTime."""
    cfg = TimeConfig(starting_hour=6)
    wt_a = compute_world_time(36, cfg)
    wt_b = compute_world_time(36, cfg)

    assert wt_a == wt_b


@pytest.mark.spec("AC-34.04")
def test_compute_world_time_different_ticks_differ() -> None:
    """Different tick counts produce different WorldTime values."""
    cfg = TimeConfig()
    assert compute_world_time(10, cfg) != compute_world_time(11, cfg)


# ---------------------------------------------------------------------------
# AC-34.05: Skip-ahead advances by exact ticks to next dawn boundary
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-34.05")
def test_skip_ahead_reaches_dawn() -> None:
    """skip_ahead(10, 11) with default config lands at hour=5 label='dawn'.

    At tick=10 with starting_hour=8: total_minutes=1080, hour=18 (dusk).
    Next dawn (05:00) is 11 ticks later (11 hours @ 60 min/tick).
    """
    svc = WorldTimeService()
    delta = svc.skip_ahead(10, 11)

    assert delta.from_tick == 10
    assert delta.to_tick == 21
    assert delta.world_time.hour == 5
    assert delta.world_time.time_of_day_label == "dawn"
    assert not delta.was_capped


# ---------------------------------------------------------------------------
# AC-34.06: Skip-ahead capped at max_skip_ticks
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-34.06")
def test_skip_ahead_capped_at_max() -> None:
    """Requesting 100 ticks when max_skip_ticks=48 → advances only 48, capped."""
    svc = WorldTimeService()
    cfg = TimeConfig(max_skip_ticks=48)
    delta = svc.skip_ahead(0, 100, config=cfg)

    assert delta.to_tick == 48
    assert delta.was_capped is True


@pytest.mark.spec("AC-34.06")
def test_skip_ahead_not_capped_when_within_limit() -> None:
    """Skip of exactly max_skip_ticks is not capped."""
    svc = WorldTimeService()
    cfg = TimeConfig(max_skip_ticks=48)
    delta = svc.skip_ahead(0, 48, config=cfg)

    assert delta.to_tick == 48
    assert delta.was_capped is False


# ---------------------------------------------------------------------------
# AC-34.07: Skip-ahead invokes NPC autonomy per tick (Wave E stub)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-34.07")
def test_skip_ahead_npc_autonomy_stub_does_not_crash() -> None:
    """Wave D stub: NPC autonomy hooks are no-ops during skip_ahead.

    Full AC-34.07 compliance (per-tick NPC autonomy callbacks) is
    implemented in Wave E (NPCAutonomyProcessor).
    """
    svc = WorldTimeService()
    # Should complete without error; NPC hooks are no-ops in Wave D
    delta = svc.skip_ahead(0, 5)
    assert delta.to_tick == 5


# ---------------------------------------------------------------------------
# AC-34.08: Skip-ahead pauses at WorldEvent within window (Wave E stub)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-34.08")
def test_skip_ahead_world_event_pause_stub_does_not_crash() -> None:
    """Wave D stub: WorldEvent pause detection is a no-op.

    Full AC-34.08 compliance (pausing at WorldEvent nodes) is
    implemented in Wave E (ConsequencePropagator).
    """
    svc = WorldTimeService()
    delta = svc.skip_ahead(10, 20)
    # No WorldEvent pause in Wave D; all 20 ticks are advanced
    assert delta.to_tick == 30


# ---------------------------------------------------------------------------
# AC-34.09: Custom hours_per_day=16 scales TOD boundaries proportionally
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-34.09")
def test_custom_hours_per_day_midpoint_is_midday() -> None:
    """With hours_per_day=16, hour 8 is the proportional midpoint → 'midday'."""
    # starting_hour=0 so tick=8 → 8*60 = 480 minutes into the 16-hour day
    cfg = TimeConfig(hours_per_day=16, starting_hour=0)
    wt = compute_world_time(8, cfg)

    assert wt.hour == 8
    assert wt.time_of_day_label == "midday"


@pytest.mark.spec("AC-34.09")
def test_custom_tod_fraction_correct() -> None:
    """hours_per_day=16: minute 480 / 960 total = 0.5 fraction → midday boundary."""
    cfg = TimeConfig(hours_per_day=16, starting_hour=0)
    wt = compute_world_time(8, cfg)
    minutes_per_day = 16 * 60
    fraction = (wt.hour * 60 + wt.minute) / minutes_per_day
    assert abs(fraction - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# AC-34.10: Failed turn does not advance WorldTime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.spec("AC-34.10")
async def test_failed_turn_no_time_advance() -> None:
    """deliver_stage with no narrative output does not change total_ticks."""
    svc = WorldTimeService()
    initial_wt = _wt_dict(svc, 7)
    state = _make_state(
        narrative_output=None,
        game_state={"world_time": initial_wt},
    )
    deps = _make_deps(world_time_service=svc)

    result = await deliver_stage(state, deps)

    assert result.status == TurnStatus.failed
    assert result.game_state["world_time"]["total_ticks"] == 7


@pytest.mark.asyncio
@pytest.mark.spec("AC-34.10")
async def test_failed_turn_game_state_unchanged() -> None:
    """game_state dict is not mutated on a failed turn."""
    svc = WorldTimeService()
    initial_wt = _wt_dict(svc, 3)
    game_state = {"world_time": initial_wt, "extra_key": "stays"}
    state = _make_state(narrative_output=None, game_state=game_state)
    deps = _make_deps(world_time_service=svc)

    result = await deliver_stage(state, deps)

    assert result.game_state["world_time"]["total_ticks"] == 3
    assert result.game_state.get("extra_key") == "stays"


# ---------------------------------------------------------------------------
# DEFAULT_TOD_BOUNDARIES sanity checks (no spec AC — guards the pure function)
# ---------------------------------------------------------------------------


def test_default_boundaries_cover_full_day() -> None:
    """DEFAULT_TOD_BOUNDARIES spans from 0.0 to < 1.0 and has expected keys."""
    assert "midnight" in DEFAULT_TOD_BOUNDARIES
    assert DEFAULT_TOD_BOUNDARIES["midnight"] == 0.0
    assert all(0.0 <= v < 1.0 for v in DEFAULT_TOD_BOUNDARIES.values())


def test_compute_world_time_day_rollover() -> None:
    """Tick count beyond one day rolls over correctly to day 2."""
    cfg = TimeConfig(starting_hour=0, minutes_per_tick=60, hours_per_day=24)
    # 24 ticks = 24 hours = exactly 1 full day from midnight
    wt = compute_world_time(24, cfg)
    assert wt.day_count == 1
    assert wt.hour == 0
    assert wt.minute == 0


def test_config_from_universe_ignores_unknown_keys() -> None:
    """config_from_universe discards unrecognised fields without error."""
    data = {"ticks_per_turn": 2, "unknown_key": "ignored", "starting_hour": 6}
    cfg = WorldTimeService.config_from_universe(data)
    assert cfg.ticks_per_turn == 2
    assert cfg.starting_hour == 6


def test_config_from_universe_empty_dict() -> None:
    """Empty universe config dict returns default TimeConfig."""
    cfg = WorldTimeService.config_from_universe({})
    assert cfg == TimeConfig()
