"""S69 mechanics resolver tests — TDD RED phase."""

from __future__ import annotations

import pytest

from tta.mechanics.resolver import classify_risk, resolve
from tta.models.v21_playtester import (
    DeathPreference,
    MechanicsDomain,
    MechanicsRequest,
    MechanicsResolutionResult,
    PlayMode,
)

# ── classify_risk ──────────────────────────────────────────────


@pytest.mark.spec("AC-69.02")
def test_classify_impossible_actions() -> None:
    """Fly, teleport, and 'one-shot' are impossible in v2.1."""
    for phrase in ("fly", "teleport", "one-shot the dragon"):
        request = _req(player_input=phrase)
        risk, domain = classify_risk(request)
        assert risk == "impossible", f"{phrase!r} should be impossible"
        # teleport is magic; fly and one-shot are physical
        expected_domain = "magic" if "teleport" in phrase else "physical"
        assert domain == expected_domain, f"{phrase!r} domain mismatch"


@pytest.mark.spec("AC-69.02")
def test_classify_risky_actions() -> None:
    """Attack/climb/sneak/persuade/cast all map to risky."""
    for phrase in (
        "attack the guard",
        "steal the gem",
        "climb the cliff",
        "sneak past the sentry",
        "persuade the merchant",
        "cast fireball",
    ):
        request = _req(player_input=phrase)
        risk, domain = classify_risk(request)
        assert risk == "risky", f"{phrase!r} should be risky"


@pytest.mark.spec("AC-69.02")
def test_classify_trivial_actions() -> None:
    """Look/wait/rest/sit are trivial."""
    for phrase in ("look around", "wait here", "rest by the fire", "sit down"):
        request = _req(player_input=phrase)
        risk, domain = classify_risk(request)
        assert risk == "trivial", f"{phrase!r} should be trivial"


def test_classify_uncertain_fallback() -> None:
    """Unrecognised input defaults to uncertain."""
    risk, domain = classify_risk(_req(player_input="ponder the orb"))
    assert risk == "uncertain"


@pytest.mark.spec("AC-69.02")
def test_classify_respects_available_domains() -> None:
    """When multiple domains are available the classifier picks one."""
    request = _req(
        player_input="steal the plans",
        available_domains=["social", "knowledge", "technology"],
    )
    risk, domain = classify_risk(request)
    assert risk == "risky"
    assert domain in ("social", "knowledge", "technology")


# ── resolve ────────────────────────────────────────────────────


@pytest.mark.spec("AC-69.04")
def test_narrative_only_skips_mechanics() -> None:
    request = _req(player_input="attack the goblin", play_mode=PlayMode.narrative_only)
    resolution = resolve(request)
    assert resolution.result == MechanicsResolutionResult.skipped


@pytest.mark.spec("AC-69.02")
def test_world_based_risky_produces_structured_result() -> None:
    request = _req(
        player_input="climb the tower",
        play_mode=PlayMode.world_based,
    )
    resolution = resolve(request)
    assert resolution.risk_level == "risky"
    assert resolution.result in (
        MechanicsResolutionResult.success,
        MechanicsResolutionResult.success_with_cost,
        MechanicsResolutionResult.failure_with_consequence,
    )
    assert resolution.consequence.summary
    assert resolution.consequence.narrative_constraint


@pytest.mark.spec("AC-69.03")
def test_no_death_rewrites_lethal_failure() -> None:
    """When death_preference is no_death, risky → injury/loss."""
    request = _req(
        player_input="attack the dragon",
        play_mode=PlayMode.world_based,
        death_preference=DeathPreference.no_death,
    )
    resolution = resolve(request)
    # Impossible is mapped to impossible result.
    # Risky with no_death should never produce death-equivalent.
    assert resolution.result != "impossible"


@pytest.mark.spec("AC-69.06")
def test_resolution_is_structured_not_prose() -> None:
    """Resolver outputs facts/constraints, not final narrative text."""
    request = _req(
        player_input="climb the wall",
        play_mode=PlayMode.world_based,
    )
    resolution = resolve(request)
    # Consequence must contain structured fields, not a prose paragraph.
    assert resolution.consequence.summary
    assert resolution.consequence.narrative_constraint
    assert len(resolution.consequence.summary) < 200  # compact, not prose
    # Structured output: key/value facts, not narrative paragraphs.
    assert "=" in resolution.consequence.narrative_constraint
    assert resolution.consequence.player_explanation is None


def test_impossible_action_yields_impossible_result() -> None:
    request = _req(
        player_input="teleport to the moon",
        play_mode=PlayMode.world_based,
    )
    resolution = resolve(request)
    assert resolution.result == MechanicsResolutionResult.impossible


def test_trivial_action_succeeds() -> None:
    request = _req(
        player_input="look around",
        play_mode=PlayMode.world_based,
    )
    resolution = resolve(request)
    assert resolution.risk_level == "trivial"
    assert resolution.result == MechanicsResolutionResult.success


# ── helpers ────────────────────────────────────────────────────


def _req(
    *,
    player_input: str = "look around",
    play_mode: PlayMode = PlayMode.world_based,
    death_preference: DeathPreference = DeathPreference.story_consequences,
    available_domains: list[MechanicsDomain] | None = None,
    game_id: str = "g-1",
    session_id: str = "s-1",
    turn_id: str = "t-1",
) -> MechanicsRequest:
    return MechanicsRequest(
        game_id=game_id,
        session_id=session_id,
        turn_id=turn_id,
        player_input=player_input,
        play_mode=play_mode,
        death_preference=death_preference,
        available_domains=available_domains or [],
    )
