"""PlaytestReport and supporting data types for S42."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Commentary:
    """Agent-side commentary attached to a single turn.

    FR-42.03: structured JSON object alongside each turn.
    """

    turn_index: int
    agent_intent: str
    surprise_level: float  # 0.0–1.0
    surprise_note: str
    coherence_rating: float  # 0.0–1.0
    coherence_note: str

    def to_dict(self) -> dict:
        return {
            "turn_index": self.turn_index,
            "agent_intent": self.agent_intent,
            "surprise_level": self.surprise_level,
            "surprise_note": self.surprise_note,
            "coherence_rating": self.coherence_rating,
            "coherence_note": self.coherence_note,
        }


@dataclass
class TurnRecord:
    """Record of a single playtester turn."""

    turn_index: int
    phase: str
    player_input: str
    narrative: str
    commentary: Commentary
    timed_out: bool = False

    def to_dict(self) -> dict:
        return {
            "turn_index": self.turn_index,
            "phase": self.phase,
            "player_input": self.player_input,
            "narrative": self.narrative,
            "commentary": self.commentary.to_dict(),
            "timed_out": self.timed_out,
        }


RunStatus = Literal["complete", "abandoned", "error"]


@dataclass
class PlaytestReport:
    """Full output of a playtester run (FR-42.05)."""

    run_id: str
    run_seed: int
    scenario_seed_id: str
    persona_id: str
    persona_jitter_seed: int
    model: str
    status: RunStatus
    genesis_phases_completed: int
    gameplay_turns_completed: int
    turns: list[TurnRecord] = field(default_factory=list)
    overall_agent_rating: float = 0.0
    overall_agent_notes: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_seed": self.run_seed,
            "scenario_seed_id": self.scenario_seed_id,
            "persona_id": self.persona_id,
            "persona_jitter_seed": self.persona_jitter_seed,
            "model": self.model,
            "status": self.status,
            "genesis_phases_completed": self.genesis_phases_completed,
            "gameplay_turns_completed": self.gameplay_turns_completed,
            "turns": [t.to_dict() for t in self.turns],
            "overall_agent_rating": self.overall_agent_rating,
            "overall_agent_notes": self.overall_agent_notes,
        }
