"""AC compliance reference for S38 NPC Memory and Social Model (AC-38.01–38.08).

All 8 ACs are fully covered in:
    tests/unit/simulation/test_npc_memory.py

AC-38.01  NPCMemory stores observed events per NPC
AC-38.02  NPCMemory records faction relationships
AC-38.03  NPCMemory expires events beyond retention window
AC-38.04  SocialGraph tracks relationship strength between NPCs
AC-38.05  SocialGraph.update_relationship() clamps strength to [-1.0, 1.0]
AC-38.06  NPCMemoryService.write() persists NPCMemory for a given NPC id
AC-38.07  NPCMemoryService.read() retrieves memories filtered by universe_id
AC-38.08  InMemoryNPCMemoryService satisfies the NPCMemoryService Protocol

No additional test functions are needed in this file.
"""
