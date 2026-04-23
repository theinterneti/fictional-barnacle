"""Unit tests for UniverseService (S29 AC-29.01–29.13)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tta.universe.exceptions import (
    UniverseAlreadyActiveError,
    UniverseArchivedError,
    UniverseNotFoundError,
    UniverseStatusTransitionError,
)
from tta.universe.models import Universe
from tta.universe.service import UniverseService


def _make_universe_row(
    uid: UUID | None = None,
    owner_id: UUID | None = None,
    status: str = "dormant",
) -> MagicMock:
    row = MagicMock()
    row.id = uid or uuid4()
    row.owner_id = owner_id or uuid4()
    row.name = "Test Universe"
    row.description = "A test universe"
    row.status = status
    row.config = {"theme": "fantasy"}
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


def _make_pg(row: MagicMock | None = None, *, no_active: bool = True) -> AsyncMock:
    """Return a mock AsyncSession whose execute returns the given row."""
    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = row
    result.fetchall.return_value = [row] if row else []
    pg.execute.return_value = result
    return pg


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-29.01", "AC-29.02")
@pytest.mark.asyncio
async def test_create_returns_dormant_universe() -> None:
    svc = UniverseService()
    pg = AsyncMock()
    pg.execute.return_value = MagicMock()

    universe = await svc.create(
        owner_id=uuid4(),
        name="My World",
        pg=pg,
        description="Desc",
        config={"key": "val"},
    )

    assert isinstance(universe, Universe)
    assert universe.status == "dormant"
    assert universe.name == "My World"
    assert universe.config == {"key": "val"}


@pytest.mark.spec("AC-29.01")
@pytest.mark.asyncio
async def test_create_defaults_empty_config() -> None:
    svc = UniverseService()
    pg = AsyncMock()
    pg.execute.return_value = MagicMock()

    universe = await svc.create(owner_id=uuid4(), name="X", pg=pg)
    assert universe.config == {}


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-29.07")
@pytest.mark.asyncio
async def test_get_raises_not_found_when_absent() -> None:
    svc = UniverseService()
    pg = _make_pg(row=None)

    with pytest.raises(UniverseNotFoundError):
        await svc.get(uuid4(), pg)


@pytest.mark.spec("AC-29.07")
@pytest.mark.asyncio
async def test_get_returns_universe() -> None:
    uid = uuid4()
    row = _make_universe_row(uid=uid)
    svc = UniverseService()
    pg = _make_pg(row=row)

    universe = await svc.get(uid, pg)
    assert universe.id == uid
    assert universe.status == "dormant"


# ---------------------------------------------------------------------------
# list_for_player()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-29.12")
@pytest.mark.asyncio
async def test_list_for_player_no_filter() -> None:
    player_id = uuid4()
    rows = [
        _make_universe_row(owner_id=player_id),
        _make_universe_row(owner_id=player_id),
    ]
    pg = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    pg.execute.return_value = result

    svc = UniverseService()
    universes = await svc.list_for_player(player_id, pg)
    assert len(universes) == 2


@pytest.mark.spec("AC-29.12")
@pytest.mark.asyncio
async def test_list_for_player_with_status_filter() -> None:
    player_id = uuid4()
    row = _make_universe_row(owner_id=player_id, status="active")
    pg = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = [row]
    pg.execute.return_value = result

    svc = UniverseService()
    universes = await svc.list_for_player(player_id, pg, status="active")
    assert len(universes) == 1
    assert universes[0].status == "active"


# ---------------------------------------------------------------------------
# activate()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-29.06", "AC-29.08")
@pytest.mark.asyncio
async def test_activate_transitions_dormant_to_active() -> None:
    uid = uuid4()
    dormant_row = _make_universe_row(uid=uid, status="dormant")
    active_row = _make_universe_row(uid=uid, status="active")

    pg = AsyncMock()
    call_count = 0

    async def side_effect(query, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        text = str(query)
        if "FOR UPDATE" in text:
            result.one_or_none.return_value = dormant_row
        elif "game_sessions" in text:
            result.one_or_none.return_value = None  # no active session
        elif call_count >= 3:
            # Final get() after _set_status
            result.one_or_none.return_value = active_row
        else:
            result.one_or_none.return_value = None
        return result

    pg.execute.side_effect = side_effect

    svc = UniverseService()
    universe = await svc.activate(uid, pg)
    assert universe.status == "active"


@pytest.mark.spec("AC-29.09")
@pytest.mark.asyncio
async def test_activate_raises_when_already_in_active_session() -> None:
    uid = uuid4()
    dormant_row = _make_universe_row(uid=uid, status="dormant")

    pg = AsyncMock()

    async def side_effect(query, params=None):  # type: ignore[no-untyped-def]
        result = MagicMock()
        text = str(query)
        if "FOR UPDATE" in text:
            result.one_or_none.return_value = dormant_row
        elif "game_sessions" in text:
            result.one_or_none.return_value = MagicMock()  # session found → blocked
        else:
            result.one_or_none.return_value = None
        return result

    pg.execute.side_effect = side_effect

    svc = UniverseService()
    with pytest.raises(UniverseAlreadyActiveError):
        await svc.activate(uid, pg)


@pytest.mark.spec("AC-29.08")
@pytest.mark.asyncio
async def test_activate_raises_for_archived_universe() -> None:
    uid = uuid4()
    archived_row = _make_universe_row(uid=uid, status="archived")
    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = archived_row
    pg.execute.return_value = result

    svc = UniverseService()
    with pytest.raises(UniverseArchivedError):
        await svc.activate(uid, pg)


@pytest.mark.spec("AC-29.08")
@pytest.mark.asyncio
async def test_activate_raises_for_already_active() -> None:
    uid = uuid4()
    active_row = _make_universe_row(uid=uid, status="active")
    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = active_row
    pg.execute.return_value = result

    svc = UniverseService()
    with pytest.raises(UniverseAlreadyActiveError):
        await svc.activate(uid, pg)


# ---------------------------------------------------------------------------
# pause()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-29.06", "AC-29.08")
@pytest.mark.asyncio
async def test_pause_transitions_active_to_paused() -> None:
    uid = uuid4()
    active_row = _make_universe_row(uid=uid, status="active")
    paused_row = _make_universe_row(uid=uid, status="paused")

    pg = AsyncMock()
    call_count = 0

    async def side_effect(query, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        text = str(query)
        if "FOR UPDATE" in text:
            result.one_or_none.return_value = active_row
        elif call_count >= 3:
            result.one_or_none.return_value = paused_row
        else:
            result.one_or_none.return_value = None
        return result

    pg.execute.side_effect = side_effect

    svc = UniverseService()
    universe = await svc.pause(uid, pg)
    assert universe.status == "paused"


@pytest.mark.spec("AC-29.08")
@pytest.mark.asyncio
async def test_pause_raises_for_invalid_transition() -> None:
    uid = uuid4()
    dormant_row = _make_universe_row(uid=uid, status="dormant")
    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = dormant_row
    pg.execute.return_value = result

    svc = UniverseService()
    with pytest.raises(UniverseStatusTransitionError):
        await svc.pause(uid, pg)


# ---------------------------------------------------------------------------
# archive()
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-29.08")
@pytest.mark.asyncio
async def test_archive_is_idempotent_when_already_archived() -> None:
    uid = uuid4()
    archived_row = _make_universe_row(uid=uid, status="archived")
    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = archived_row
    pg.execute.return_value = result

    svc = UniverseService()
    universe = await svc.archive(uid, pg)
    assert universe.status == "archived"


@pytest.mark.spec("AC-29.08")
@pytest.mark.asyncio
async def test_archive_from_paused_succeeds() -> None:
    uid = uuid4()
    paused_row = _make_universe_row(uid=uid, status="paused")
    archived_row = _make_universe_row(uid=uid, status="archived")

    pg = AsyncMock()
    call_count = 0

    async def side_effect(query, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if "FOR UPDATE" in str(query):
            result.one_or_none.return_value = paused_row
        elif call_count >= 3:
            result.one_or_none.return_value = archived_row
        else:
            result.one_or_none.return_value = None
        return result

    pg.execute.side_effect = side_effect

    svc = UniverseService()
    universe = await svc.archive(uid, pg)
    assert universe.status == "archived"
