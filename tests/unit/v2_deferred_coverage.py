# v2_deferred_coverage.py
# This file covers ACs that are not yet implemented but cited in tests.
# Format: one skipped test function per line, using the AC number as the only content.

import pytest


@pytest.mark.spec("AC-66.04")
@pytest.mark.skip(
    reason=(
        "S66 approved target: provider-preference needs a provider-utilization "
        "signal spike before implementation."
    )
)
def test_ac66_04_deferred_provider_preference() -> None:
    """AC-66.04 requires routing LOW calls away from NEAR_LIMIT providers."""


@pytest.mark.spec("AC-03.07")
@pytest.mark.skip(
    reason="V2 deferred: coherence checker/regeneration is not built yet."
)
def test_ac_3_7_deferred_coherence_checker() -> None:
    """AC-03.07 requires detecting coherence violations and regenerating output."""


@pytest.mark.spec("AC-05.05")
@pytest.mark.skip(
    reason="V2 deferred: multi-turn foreshadowing requires eval/sim lane."
)
def test_ac_5_5_deferred_foreshadowing_over_five_turns() -> None:
    """AC-05.05 requires detecting foreshadowing across a 5+ turn chain."""


@pytest.mark.spec("AC-06.02")
@pytest.mark.skip(reason="V2 deferred: trait mutation subsystem is not built yet.")
def test_ac_6_2_deferred_trait_evolution() -> None:
    """AC-06.02 requires trait shifts after 10+ contrary actions."""


@pytest.mark.spec("AC-06.10")
@pytest.mark.skip(
    reason="V2 deferred: NPC death-state redistribution is not built yet."
)
def test_ac_6_10_deferred_npc_death_redistribution() -> None:
    """AC-06.10 requires dead NPC filtering and narrative-role redistribution."""
