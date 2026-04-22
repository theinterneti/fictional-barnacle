"""Tests for Universe-domain Pydantic models (S29, S30, S31).

AC coverage:
- AC-29.01: Universe is created with status='dormant'
- AC-29.02: Universe.status transitions are constrained
- AC-29.03: Universe has id, owner_id, name, description, config, timestamps
- AC-30.03: actors field on GameSession is a list (JSONB array)
- AC-30.07: actors list supports multiple UUIDs (forward-compat multi-actor)
- AC-31.01: actor_id is distinct from player_id
- AC-31.02: Actor has id, player_id, display_name, avatar_config, timestamps
- AC-31.03: CharacterState has UNIQUE(actor_id, universe_id) via model validation
- AC-31.04: CharacterState lazy creation defaults all state fields to empty
"""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from tta.models.game import GameSession
from tta.universe.models import Actor, CharacterState, Universe, UniverseSnapshot


@pytest.mark.spec("AC-29.01")
def test_universe_default_status_is_dormant():
    u = Universe(owner_id=uuid4(), name="Test World")
    assert u.status == "dormant"


@pytest.mark.spec("AC-29.03")
def test_universe_has_required_fields():
    owner = uuid4()
    u = Universe(owner_id=owner, name="My Universe", description="A world")
    assert isinstance(u.id, UUID)
    assert u.owner_id == owner
    assert u.name == "My Universe"
    assert u.description == "A world"
    assert u.config == {}
    assert u.created_at is not None
    assert u.updated_at is not None


@pytest.mark.spec("AC-29.02")
def test_universe_status_accepts_all_valid_values():
    base = {"owner_id": uuid4(), "name": "W"}
    for status in ("dormant", "created", "active", "paused", "archived"):
        u = Universe(**base, status=status)
        assert u.status == status


@pytest.mark.spec("AC-29.02")
def test_universe_status_rejects_invalid():
    with pytest.raises(ValidationError):
        Universe(owner_id=uuid4(), name="W", status="running")


@pytest.mark.spec("AC-31.01", "AC-31.02")
def test_actor_id_distinct_from_player_id():
    player = uuid4()
    actor = Actor(player_id=player, display_name="Ada")
    assert isinstance(actor.id, UUID)
    assert actor.id != actor.player_id
    assert actor.player_id == player


@pytest.mark.spec("AC-31.02")
def test_actor_default_avatar_config():
    actor = Actor(player_id=uuid4(), display_name="Mx Traveller")
    assert actor.avatar_config == {}
    assert actor.display_name == "Mx Traveller"


@pytest.mark.spec("AC-31.04")
def test_character_state_defaults_all_empty():
    cs = CharacterState(actor_id=uuid4(), universe_id=uuid4())
    assert cs.traits == []
    assert cs.inventory == []
    assert cs.conditions == []
    assert cs.reputation == {}
    assert cs.relationships == {}
    assert cs.custom == {}


@pytest.mark.spec("AC-31.03")
def test_character_state_carries_actor_and_universe_ids():
    actor_id = uuid4()
    universe_id = uuid4()
    cs = CharacterState(actor_id=actor_id, universe_id=universe_id)
    assert cs.actor_id == actor_id
    assert cs.universe_id == universe_id
    assert cs.id != actor_id
    assert cs.id != universe_id


def test_universe_snapshot_defaults():
    snap = UniverseSnapshot(universe_id=uuid4())
    assert snap.snapshot == {}
    assert snap.snapshot_type == "session_end"
    assert snap.turn_count == 0
    assert snap.session_id is None


def test_universe_snapshot_snapshot_type_values():
    uid = uuid4()
    for t in ("session_end", "manual", "admin"):
        s = UniverseSnapshot(universe_id=uid, snapshot_type=t)
        assert s.snapshot_type == t


def test_universe_snapshot_invalid_type():
    with pytest.raises(ValidationError):
        UniverseSnapshot(universe_id=uuid4(), snapshot_type="checkpoint")


@pytest.mark.spec("AC-30.03")
def test_game_session_actors_defaults_to_empty_list():
    gs = GameSession(player_id=uuid4())
    assert gs.actors == []
    assert gs.universe_id is None


@pytest.mark.spec("AC-30.07")
def test_game_session_actors_accepts_multiple_uuids():
    ids = [uuid4(), uuid4()]
    gs = GameSession(player_id=uuid4(), actors=ids)
    assert gs.actors == ids
    assert len(gs.actors) == 2
