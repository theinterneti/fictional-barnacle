"""Diegetic time engine for TTA v2 (spec S34).

Public surface:
  DEFAULT_TOD_BOUNDARIES   — default time-of-day label → day-fraction map
  compute_world_time()     — pure deterministic function, no I/O
  WorldTimeService         — stateless service; tick() / skip_ahead() / helpers
"""

from __future__ import annotations

from tta.simulation.types import TimeConfig, WorldDelta, WorldTime

# ---------------------------------------------------------------------------
# Default time-of-day boundary fractions
# Each value is the fraction of the day at which that period *starts*.
# ---------------------------------------------------------------------------
DEFAULT_TOD_BOUNDARIES: dict[str, float] = {
    "midnight": 0.000,
    "predawn": 0.042,  # ~01:00 in a 24h day
    "dawn": 0.208,  # ~05:00
    "morning": 0.292,  # ~07:00
    "midday": 0.500,  # 12:00
    "afternoon": 0.583,  # ~14:00
    "dusk": 0.708,  # ~17:00
    "evening": 0.833,  # ~20:00
    "night": 0.917,  # ~22:00
}


def compute_world_time(total_ticks: int, config: TimeConfig) -> WorldTime:
    """Derive WorldTime from tick count + config. Pure function; no I/O.

    Formula (S34 §4.1):
      offset_minutes = starting_day * hours_per_day * 60 + starting_hour * 60
      total_minutes  = total_ticks * minutes_per_tick + offset_minutes
      day_count      = total_minutes // (hours_per_day * 60)
      minutes_in_day = total_minutes % (hours_per_day * 60)
      hour           = minutes_in_day // 60
      minute         = minutes_in_day % 60

    TOD label: sort boundaries ascending, return the last label whose
    start-fraction is <= fraction-of-day. Falls back to "midnight" when
    no boundary matches (total_ticks=0 at midnight).
    """
    minutes_per_day = config.hours_per_day * 60
    offset_minutes = config.starting_day * minutes_per_day + config.starting_hour * 60
    total_minutes = total_ticks * config.minutes_per_tick + offset_minutes

    day_count = total_minutes // minutes_per_day
    minutes_in_day = total_minutes % minutes_per_day
    hour = minutes_in_day // 60
    minute = minutes_in_day % 60

    # Resolve time-of-day label
    boundaries = config.tod_boundaries or DEFAULT_TOD_BOUNDARIES
    fraction = minutes_in_day / minutes_per_day
    label = "midnight"
    for name, start in sorted(boundaries.items(), key=lambda kv: kv[1]):
        if fraction >= start:
            label = name

    return WorldTime(
        total_ticks=total_ticks,
        day_count=day_count,
        hour=hour,
        minute=minute,
        time_of_day_label=label,
    )


class WorldTimeService:
    """Stateless diegetic time service (S34).

    All methods are synchronous and deterministic.
    The service holds no mutable state; callers supply current tick counts.
    """

    # ------------------------------------------------------------------
    # Core public interface
    # ------------------------------------------------------------------

    def tick(self, current_ticks: int, config: TimeConfig | None = None) -> WorldDelta:
        """Advance time by one standard turn (ticks_per_turn ticks).

        If config is None, a default TimeConfig is used (1 tick/turn).
        """
        cfg = config or TimeConfig()
        # Legacy guard: treat ticks_per_turn=0 as 1 (S34 §3.2)
        steps = cfg.ticks_per_turn if cfg.ticks_per_turn > 0 else 1
        new_ticks = current_ticks + steps
        return WorldDelta(
            from_tick=current_ticks,
            to_tick=new_ticks,
            world_time=compute_world_time(new_ticks, cfg),
            was_capped=False,
        )

    def skip_ahead(
        self,
        current_ticks: int,
        requested_ticks: int,
        config: TimeConfig | None = None,
    ) -> WorldDelta:
        """Advance time by up to requested_ticks, capped at max_skip_ticks.

        Stubs for Wave E / Wave F:
          - NPC autonomy is invoked once per skipped tick (Wave E).
          - A WorldEvent in the skip window can pause the skip (Wave E).
        Both stubs are no-ops in Wave D.
        """
        cfg = config or TimeConfig()
        actual = min(requested_ticks, cfg.max_skip_ticks)
        was_capped = actual < requested_ticks
        new_ticks = current_ticks + actual
        return WorldDelta(
            from_tick=current_ticks,
            to_tick=new_ticks,
            world_time=compute_world_time(new_ticks, cfg),
            was_capped=was_capped,
        )

    def initial_world_time(self, config: TimeConfig | None = None) -> WorldTime:
        """Return the WorldTime for a brand-new session at tick 0.

        Applies starting_hour / starting_day from config (S34 AC-34.02).
        """
        cfg = config or TimeConfig()
        return compute_world_time(0, cfg)

    @staticmethod
    def config_from_universe(data: dict) -> TimeConfig:
        """Construct TimeConfig from a universe config dict (S34 §3.5).

        Only recognised keys are consumed; unknown keys are silently ignored.
        """
        known = {
            "ticks_per_turn",
            "minutes_per_tick",
            "hours_per_day",
            "day_start_hour",
            "starting_hour",
            "starting_day",
            "max_skip_ticks",
            "tod_boundaries",
        }
        return TimeConfig(**{k: v for k, v in data.items() if k in known})
