"""AC compliance reference for S37 World Memory Model (AC-37.01–37.08).

All 8 ACs are fully covered in:
    tests/unit/simulation/test_world_memory.py

AC-37.01  MemoryRecord stores turn_number and world_time_tick
AC-37.02  WorldMemoryService.write() accepts a MemoryRecord and persists it
AC-37.03  WorldMemoryService.read() returns records filtered by universe_id
AC-37.04  WorldMemoryService supports RECENT / ARCHIVED / COMPRESSED tiers
AC-37.05  Compression reduces RECENT records into a COMPRESSED summary
AC-37.06  WorldMemoryService.compress() triggers at configured threshold
AC-37.07  InMemoryWorldMemoryService satisfies the WorldMemoryService Protocol
AC-37.08  MemoryRecord.tier defaults to RECENT

No additional test functions are needed in this file.
"""
