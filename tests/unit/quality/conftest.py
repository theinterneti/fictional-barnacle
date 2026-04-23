"""Shared fixtures for S44 quality evaluation tests."""

from __future__ import annotations

import pytest

from tta.playtest.report import Commentary, PlaytestReport, TurnRecord
from tta.quality.feedback import FeedbackRecord


def make_turn(
    *,
    turn_index: int,
    phase: str = "gameplay",
    player_input: str = "go north",
    narrative: str = "You walk north.",
    coherence_rating: float = 0.8,
    surprise_level: float = 0.5,
    timed_out: bool = False,
) -> TurnRecord:
    """Create a TurnRecord with synthetic values."""
    commentary = Commentary(
        turn_index=turn_index,
        agent_intent="explore",
        surprise_level=surprise_level,
        surprise_note="normal",
        coherence_rating=coherence_rating,
        coherence_note="consistent",
    )
    return TurnRecord(
        turn_index=turn_index,
        phase=phase,
        player_input=player_input,
        narrative=narrative,
        commentary=commentary,
        timed_out=timed_out,
    )


def make_report(
    *,
    run_id: str = "run-abc",
    scenario_seed_id: str = "seed-01",
    turns: list[TurnRecord] | None = None,
    status: str = "complete",
    gameplay_turns_completed: int = 5,
) -> PlaytestReport:
    """Create a PlaytestReport with synthetic values."""
    if turns is None:
        turns = [
            make_turn(turn_index=i, narrative=f"Arika walks. Turn {i}.")
            for i in range(gameplay_turns_completed)
        ]
    return PlaytestReport(
        run_id=run_id,
        run_seed=42,
        scenario_seed_id=scenario_seed_id,
        persona_id="persona-default",
        persona_jitter_seed=0,
        model="test-model",
        status=status,
        genesis_phases_completed=4,
        gameplay_turns_completed=gameplay_turns_completed,
        turns=turns,
    )


@pytest.fixture
def full_report() -> PlaytestReport:
    """A complete PlaytestReport with 5 gameplay turns."""
    return make_report(gameplay_turns_completed=5)


@pytest.fixture
def human_feedback() -> FeedbackRecord:
    """A mid-level FeedbackRecord."""
    return FeedbackRecord(
        run_id="run-abc",
        q_wonder=3.0,
        q_consequence=3.0,
        q_character=3.0,
    )
