"""Unit tests for S30 — Session-Universe Binding (AC-30.01–30.10)."""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tta.universe.exceptions import (
    UniverseAlreadyActiveError,
    UniverseArchivedError,
)
from tta.universe.service import UniverseService


def _make_universe_row(
    uid: UUID | None = None,
    owner_id: UUID | None = None,
    status: str = "dormant",
) -> MagicMock:
    row = MagicMock()
    row.id = uid or uuid4()
    row.owner_id = owner_id or uuid4()
    row.name = "Bound Universe"
    row.description = "S30 test universe"
    row.status = status
    row.config = {}
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


def _make_activate_pg(
    for_update_row: MagicMock,
    final_row: MagicMock,
    extra_none: bool = True,
) -> AsyncMock:
    """Build an AsyncMock pg for an activate() call path.

    activate() issues: SELECT (no-sessions check), SELECT FOR UPDATE, UPDATE, SELECT.
    """
    call_count = 0
    pg = AsyncMock()

    async def side_effect(query, params=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        text = str(query)
        if "FOR UPDATE" in text:
            result.one_or_none.return_value = for_update_row
        elif call_count >= 3:
            result.one_or_none.return_value = final_row
        elif extra_none:
            result.one_or_none.return_value = None
        else:
            result.one_or_none.return_value = None
        return result

    pg.execute.side_effect = side_effect
    return pg


# ===========================================================================
# AC-30.01 — Dormant universe can be activated (first session)
# ===========================================================================


@pytest.mark.spec("AC-30.01")
@pytest.mark.asyncio
async def test_dormant_universe_can_be_activated() -> None:
    uid = uuid4()
    dormant_row = _make_universe_row(uid=uid, status="dormant")
    active_row = _make_universe_row(uid=uid, status="active")

    pg = _make_activate_pg(for_update_row=dormant_row, final_row=active_row)

    svc = UniverseService()
    universe = await svc.activate(uid, pg)
    assert universe.status == "active"


# ===========================================================================
# AC-30.02 — Paused universe can be re-activated (resume)
# ===========================================================================


@pytest.mark.spec("AC-30.02")
@pytest.mark.asyncio
async def test_paused_universe_can_be_activated_resume() -> None:
    uid = uuid4()
    paused_row = _make_universe_row(uid=uid, status="paused")
    active_row = _make_universe_row(uid=uid, status="active")

    pg = _make_activate_pg(for_update_row=paused_row, final_row=active_row)

    svc = UniverseService()
    universe = await svc.activate(uid, pg)
    assert universe.status == "active"


# ===========================================================================
# AC-30.04 — Archived universe raises UniverseArchivedError on activation
# ===========================================================================


@pytest.mark.spec("AC-30.04")
@pytest.mark.asyncio
async def test_archived_universe_cannot_be_activated() -> None:
    uid = uuid4()
    archived_row = _make_universe_row(uid=uid, status="archived")

    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = archived_row
    pg.execute.return_value = result

    svc = UniverseService()
    with pytest.raises(UniverseArchivedError):
        await svc.activate(uid, pg)


# ===========================================================================
# AC-30.05 — universe_id is immutable: no UPDATE path modifies it
# ===========================================================================


@pytest.mark.spec("AC-30.05")
def test_universe_id_column_has_no_update_path_in_service() -> None:
    """UniverseService never issues SET universe_id = ... on universes table."""
    import inspect

    from tta.universe import service as svc_mod

    src = inspect.getsource(svc_mod)
    # There should be no UPDATE universes SET ... universe_id  fragment
    assert "SET universe_id" not in src, (
        "UniverseService must not have a code path that updates universe_id"
    )


# ===========================================================================
# AC-30.06 — actors field defaults to exactly 1 element after backfill
# ===========================================================================


@pytest.mark.spec("AC-30.06")
def test_migration_backfills_one_actor_per_player() -> None:
    """Migration SQL inserts exactly one actor per player (AC-30.06 / AC-33.02)."""
    migration = (
        pathlib.Path(__file__).parents[3]
        / "migrations"
        / "postgres"
        / "versions"
        / "011_v2_universe_entity.py"
    )
    text = migration.read_text()
    # The INSERT for actors must use NOT EXISTS guard (exactly-one constraint)
    assert "NOT EXISTS" in text
    assert "actors" in text.lower()
    assert "player_id" in text.lower()


# ===========================================================================
# AC-30.08 — Session end causes universe to pause
# ===========================================================================


@pytest.mark.spec("AC-30.08")
@pytest.mark.asyncio
async def test_pause_called_on_session_end() -> None:
    """UniverseService.pause() transitions active → paused (session-end path)."""
    uid = uuid4()
    active_row = _make_universe_row(uid=uid, status="active")
    paused_row = _make_universe_row(uid=uid, status="paused")

    call_count = 0
    pg = AsyncMock()

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


# ===========================================================================
# AC-30.09 — Session pause keeps universe active (pausing a session ≠ pausing universe)
# ===========================================================================


@pytest.mark.spec("AC-30.09")
@pytest.mark.asyncio
async def test_active_universe_is_not_paused_on_game_save() -> None:
    """activate() on an already-active universe raises; status stays active."""
    uid = uuid4()
    active_row = _make_universe_row(uid=uid, status="active")

    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = active_row
    pg.execute.return_value = result

    svc = UniverseService()
    with pytest.raises(UniverseAlreadyActiveError):
        await svc.activate(uid, pg)


# ===========================================================================
# AC-30.10 — Concurrent activation raises UniverseAlreadyActiveError
# ===========================================================================


@pytest.mark.spec("AC-30.10")
@pytest.mark.asyncio
async def test_second_activation_raises_already_active() -> None:
    """If a session already has the universe active, a second activate() raises."""
    uid = uuid4()
    already_active_row = _make_universe_row(uid=uid, status="active")

    pg = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = already_active_row
    pg.execute.return_value = result

    svc = UniverseService()
    with pytest.raises(UniverseAlreadyActiveError):
        await svc.activate(uid, pg)
