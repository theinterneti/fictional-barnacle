"""AC compliance reference for S34 Diegetic Time (AC-34.01–34.10).

All 10 ACs are fully covered in:
    tests/unit/simulation/test_world_time.py

AC-34.01  WorldTime.from_ticks() derives day/hour/minute from total_ticks
AC-34.02  WorldTime is immutable (frozen dataclass)
AC-34.03  TimeConfig.ticks_per_turn defaults to 1
AC-34.04  WorldTimeService.advance() returns incremented WorldTime
AC-34.05  WorldTimeService.advance() accepts optional tick count override
AC-34.06  WorldTimeService.advance() clamps skip_ticks to max_skip_ticks
AC-34.07  WorldTimeService labels times-of-day correctly
AC-34.08  WorldTimeService.advance() emits WorldDelta with new WorldTime
AC-34.09  WorldTime equality is value-based
AC-34.10  WorldTimeService.reset() returns WorldTime at tick 0

No additional test functions are needed in this file.
"""
