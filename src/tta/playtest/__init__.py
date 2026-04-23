"""S42 — LLM Playtester Agent Harness.

Automated playtesting using LLM agents with semi-randomized taste profiles.
"""

from tta.playtest.agent import PlaytesterAgent
from tta.playtest.profile import BUILTIN_PERSONAS, TasteProfile
from tta.playtest.report import Commentary, PlaytestReport, TurnRecord

__all__ = [
    "PlaytesterAgent",
    "TasteProfile",
    "BUILTIN_PERSONAS",
    "PlaytestReport",
    "TurnRecord",
    "Commentary",
]
