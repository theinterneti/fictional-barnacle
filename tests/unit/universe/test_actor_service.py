"""Unit tests for ActorService (S31 AC-31.01–31.09)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tta.universe.actor_service import ActorService
from tta.universe.exceptions import ActorNotFoundError, CharacterStateNotFoundError
from tta.universe.models import Actor, CharacterState


def _make_actor_row(
    player_id=None,  # type: ignore[no-untyped-def]
) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.player_id = player_id or uuid4()
    row.display_name = "Hero"
    row.avatar_config = {}
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


def _make_state_row(actor_id=None, universe_id=None) -> MagicMock:  # type: ignore[no-untyped-def]
    row = MagicMock()
    row.id = uuid4()
    row.actor_id = actor_id or uuid4()
    row.universe_id = universe_id or uuid4()
    row.traits = ["brave"]
    row.inventory = []
    row.conditions = []
    row.reputation = {}
    row.relationships = {}
    row.custom = {}
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


# ---------------------------------------------------------------------------
# get_or_create_for_player()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-31.01")
@pytest.mark.asyncio
async def test_get_or_create_returns_existing_actor() -> None:
    player_id = uuid4()
    row = _make_actor_row(player_id=player_id)

    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = row
    pg.execute.return_value = result

    svc = ActorService()
    actor = await svc.get_or_create_for_player(player_id, "Hero", pg)

    assert isinstance(actor, Actor)
    assert actor.player_id == player_id
    pg.execute.assert_called_once()  # only the SELECT, no INSERT


@pytest.mark.spec("AC-31.01", "AC-31.02")
@pytest.mark.asyncio
async def test_get_or_create_inserts_when_absent() -> None:
    player_id = uuid4()

    call_count = 0

    pg = AsyncMock()

    async def side_effect(query, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        result.one_or_none.return_value = None  # first SELECT returns nothing
        return result

    pg.execute.side_effect = side_effect

    svc = ActorService()
    actor = await svc.get_or_create_for_player(player_id, "New Hero", pg)

    assert actor.player_id == player_id
    assert actor.display_name == "New Hero"
    assert pg.execute.call_count == 2  # SELECT + INSERT


# ---------------------------------------------------------------------------
# get_by_player()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-31.08")
@pytest.mark.asyncio
async def test_get_by_player_returns_all_actors() -> None:
    player_id = uuid4()
    rows = [_make_actor_row(player_id=player_id), _make_actor_row(player_id=player_id)]

    pg = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    pg.execute.return_value = result

    svc = ActorService()
    actors = await svc.get_by_player(player_id, pg)
    assert len(actors) == 2


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-31.01")
@pytest.mark.asyncio
async def test_get_raises_not_found() -> None:
    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = None
    pg.execute.return_value = result

    svc = ActorService()
    with pytest.raises(ActorNotFoundError):
        await svc.get(uuid4(), pg)


# ---------------------------------------------------------------------------
# get_character_state()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-31.09")
@pytest.mark.asyncio
async def test_get_character_state_returns_none_when_absent() -> None:
    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = None
    pg.execute.return_value = result

    svc = ActorService()
    state = await svc.get_character_state(uuid4(), uuid4(), pg)
    assert state is None


@pytest.mark.spec("AC-31.03")
@pytest.mark.asyncio
async def test_get_character_state_returns_state_when_present() -> None:
    actor_id = uuid4()
    universe_id = uuid4()
    row = _make_state_row(actor_id=actor_id, universe_id=universe_id)

    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = row
    pg.execute.return_value = result

    svc = ActorService()
    state = await svc.get_character_state(actor_id, universe_id, pg)
    assert state is not None
    assert state.actor_id == actor_id


# ---------------------------------------------------------------------------
# get_or_create_character_state()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-31.03", "AC-31.04")
@pytest.mark.asyncio
async def test_get_or_create_creates_state_when_absent() -> None:
    actor_id = uuid4()
    universe_id = uuid4()
    row = _make_state_row(actor_id=actor_id, universe_id=universe_id)

    call_count = 0

    pg = AsyncMock()

    async def side_effect(query, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        # First SELECT returns nothing, second (after INSERT) returns the row
        if call_count == 1:
            result.one_or_none.return_value = None
        else:
            result.one_or_none.return_value = row
        return result

    pg.execute.side_effect = side_effect

    svc = ActorService()
    state = await svc.get_or_create_character_state(actor_id, universe_id, pg)

    assert isinstance(state, CharacterState)
    assert state.actor_id == actor_id
    assert pg.execute.call_count == 3  # SELECT + INSERT (ON CONFLICT) + re-fetch SELECT


@pytest.mark.spec("AC-31.05")
@pytest.mark.asyncio
async def test_get_or_create_returns_existing_state() -> None:
    actor_id = uuid4()
    universe_id = uuid4()
    row = _make_state_row(actor_id=actor_id, universe_id=universe_id)

    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = row
    pg.execute.return_value = result

    svc = ActorService()
    state = await svc.get_or_create_character_state(actor_id, universe_id, pg)
    assert state.actor_id == actor_id
    pg.execute.assert_called_once()  # only the initial SELECT


# ---------------------------------------------------------------------------
# upsert_character_state()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-31.07")
@pytest.mark.asyncio
async def test_upsert_raises_when_state_absent() -> None:
    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = None
    pg.execute.return_value = result

    svc = ActorService()
    with pytest.raises(CharacterStateNotFoundError):
        await svc.upsert_character_state(uuid4(), uuid4(), pg, traits=["bold"])


@pytest.mark.spec("AC-31.07")
@pytest.mark.asyncio
async def test_upsert_updates_specified_fields() -> None:
    actor_id = uuid4()
    universe_id = uuid4()
    row = _make_state_row(actor_id=actor_id, universe_id=universe_id)

    call_count = 0

    pg = AsyncMock()

    async def side_effect(query, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        result.one_or_none.return_value = row
        return result

    pg.execute.side_effect = side_effect

    svc = ActorService()
    state = await svc.upsert_character_state(
        actor_id,
        universe_id,
        pg,
        traits=["brave", "wise"],
        custom={"level": 5},
    )
    assert isinstance(state, CharacterState)
    # Verify UPDATE was issued (3 calls: initial SELECT, UPDATE, re-fetch SELECT)
    assert pg.execute.call_count == 3
