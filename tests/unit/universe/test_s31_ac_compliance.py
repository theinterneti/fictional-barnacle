"""AC compliance tests for S31 Actor Identity Portability (AC-31.01–31.09).

All ACs are covered across this file and tests/unit/universe/test_actor_service.py.

AC coverage (see test_actor_service.py for AC-31.01–05/07–09):
- AC-31.01: get_or_create() returns existing actor by player_id
- AC-31.02: get_or_create() inserts when absent
- AC-31.03: get_character_state() returns state for (actor_id, universe_id)
- AC-31.04: get_or_create_character_state() creates when absent
- AC-31.05: get_or_create_character_state() returns existing
- AC-31.06: Deleting an actor cascades to character_states (FK ON DELETE CASCADE)
- AC-31.07: upsert_character_state() updates specified fields
- AC-31.08: get_by_player() returns all actors for a player
- AC-31.09: get_character_state() returns None when absent
"""

import pytest

# ---------------------------------------------------------------------------
# AC-31.06 — Deleting an actor cascades to character_states
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-31.06")
def test_migration_011_defines_cascade_delete_on_character_states_actor_fk() -> None:
    """migration 011 creates character_states with FK actor_id ON DELETE CASCADE.

    AC-31.06: Deleting an actor must automatically delete all character_states
    for that actor. This is enforced by the FK constraint with ON DELETE CASCADE
    in migration 011.
    """
    import pathlib
    import re

    migration = (
        pathlib.Path(__file__).parent.parent.parent.parent
        / "migrations"
        / "postgres"
        / "versions"
        / "011_v2_universe_entity.py"
    )
    src = migration.read_text()

    # The character_states table must have a FK on actor_id with CASCADE
    # Find the character_states FK definition block
    assert "character_states" in src, "migration must create character_states table"

    # Verify ondelete="CASCADE" appears in the context of character_states FK
    assert 'ondelete="CASCADE"' in src, (
        "migration must define ON DELETE CASCADE for character_states FKs"
    )

    # Specifically verify the fk_character_states_actor constraint
    assert "fk_character_states_actor" in src, (
        "migration must name the FK 'fk_character_states_actor'"
    )

    # Find the FK definition near the actor_id column in character_states
    match = re.search(
        r"fk_character_states_actor.*?ondelete.*?CASCADE",
        src,
        re.DOTALL,
    )
    assert match is not None, (
        "fk_character_states_actor must have ondelete='CASCADE' (AC-31.06)"
    )


@pytest.mark.spec("AC-31.06")
def test_migration_011_defines_cascade_delete_on_character_states_universe_fk() -> None:
    """migration 011 also cascades universe delete to character_states.

    AC-31.06: Deleting a universe must also cascade to character_states.
    This ensures orphaned states cannot exist.
    """
    import pathlib
    import re

    migration = (
        pathlib.Path(__file__).parent.parent.parent.parent
        / "migrations"
        / "postgres"
        / "versions"
        / "011_v2_universe_entity.py"
    )
    src = migration.read_text()

    # fk_character_states_universe must also be CASCADE
    assert "fk_character_states_universe" in src, (
        "migration must name the FK 'fk_character_states_universe'"
    )

    match = re.search(
        r"fk_character_states_universe.*?ondelete.*?CASCADE",
        src,
        re.DOTALL,
    )
    assert match is not None, (
        "fk_character_states_universe must have ondelete='CASCADE'"
    )
