"""S70 route/text-map read-model tests."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from tta.models.v21_playtester import RouteVisibility
from tta.world.neo4j_service import Neo4jWorldService


class _FakeResult:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def __aiter__(self) -> _FakeResult:
        self._index = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._index >= len(self._records):
            raise StopAsyncIteration
        record = self._records[self._index]
        self._index += 1
        return record


class _FakeSession:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.queries: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def run(self, query: str, **params: Any) -> _FakeResult:
        self.queries.append((query, params))
        return _FakeResult(self.records)


class _FakeDriver:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.session_obj = _FakeSession(records)

    def session(self) -> _FakeSession:
        return self.session_obj


def _route_record(
    *,
    route_id: str,
    to_id: str,
    to_name: str,
    hidden: bool = False,
    locked: bool = False,
    blocked_reason: str | None = None,
    terrain_type: str = "forest",
    distance_value: float = 10.0,
    distance_unit: str = "km",
    travel_modes: list[str] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    return {
        "current_location_id": "crossroads",
        "current_location_name": "Old Crossroads",
        "route_id": route_id,
        "from_location_id": "crossroads",
        "to_location_id": to_id,
        "to_location_name": to_name,
        "label": label or f"Path to {to_name}",
        "terrain_type": terrain_type,
        "distance_value": distance_value,
        "distance_unit": distance_unit,
        "travel_modes": travel_modes or ["walking"],
        "directionality": "two_way",
        "is_hidden": hidden,
        "is_locked": locked,
        "blocked_reason": blocked_reason,
        "encounter_tags": ["ambush"] if hidden else ["forage"],
        "coordinates": {"x": 1.0, "y": 2.0},
        "secret_metadata": {"spoiler": "bandit camp"},
    }


@pytest.mark.spec("AC-70.01")
@pytest.mark.asyncio
async def test_known_routes_list_player_relevant_travel_metadata() -> None:
    session_id = uuid4()
    service = Neo4jWorldService(
        _FakeDriver(
            [
                _route_record(route_id="r-forest", to_id="woods", to_name="Whispering Woods"),
                _route_record(
                    route_id="r-bridge",
                    to_id="bridge",
                    to_name="Broken Bridge",
                    locked=True,
                    blocked_reason="The bridge has collapsed.",
                    terrain_type="road",
                    travel_modes=["walking", "cart"],
                ),
            ]
        )  # type: ignore[arg-type]
    )

    routes = await service.list_available_routes(session_id, "crossroads")

    assert [route.route_id for route in routes] == ["r-forest", "r-bridge"]
    assert routes[0].to_location_id == "woods"
    assert routes[0].terrain_type == "forest"
    assert routes[0].travel_modes == ["walking"]
    assert routes[0].estimated_travel_time.value > 0
    assert routes[1].blocked is True
    assert routes[1].blocked_reason == "The bridge has collapsed."


@pytest.mark.spec("AC-70.02")
@pytest.mark.asyncio
async def test_travel_time_estimate_is_deterministic() -> None:
    session_id = uuid4()
    service = Neo4jWorldService(
        _FakeDriver(
            [
                _route_record(
                    route_id="r-forest",
                    to_id="woods",
                    to_name="Whispering Woods",
                    distance_value=10,
                    distance_unit="km",
                    terrain_type="forest",
                    travel_modes=["walking"],
                )
            ]
        )  # type: ignore[arg-type]
    )

    first = await service.list_available_routes(session_id, "crossroads")
    second = await service.list_available_routes(session_id, "crossroads")

    assert first[0].estimated_travel_time == second[0].estimated_travel_time


@pytest.mark.spec("AC-70.03")
@pytest.mark.spec("AC-70.07")
@pytest.mark.asyncio
async def test_local_map_hides_undiscovered_routes_and_secret_metadata() -> None:
    session_id = uuid4()
    service = Neo4jWorldService(
        _FakeDriver(
            [
                _route_record(route_id="r-known", to_id="woods", to_name="Woods"),
                _route_record(
                    route_id="r-secret",
                    to_id="bandit-camp",
                    to_name="Bandit Camp",
                    hidden=True,
                    label="Secret smugglers' trail",
                ),
            ]
        )  # type: ignore[arg-type]
    )

    local_map = await service.get_local_map(session_id)
    payload = local_map.player_facing_dump()

    assert payload["current_location_id"] == "crossroads"
    assert [route["route_id"] for route in payload["routes"]] == ["r-known"]
    rendered = repr(payload)
    assert "r-secret" not in rendered
    assert "bandit-camp" not in rendered
    assert "Secret smugglers' trail" not in rendered
    assert "ambush" not in rendered
    assert "spoiler" not in rendered
    assert local_map.routes[1].visibility is RouteVisibility.hidden


@pytest.mark.asyncio
async def test_route_query_is_scoped_to_session_and_current_location() -> None:
    session_id = uuid4()
    driver = _FakeDriver([])
    service = Neo4jWorldService(driver)  # type: ignore[arg-type]

    await service.list_available_routes(session_id, "crossroads")

    query, params = driver.session_obj.queries[0]
    assert "CONNECTS_TO" in query
    assert params == {"sid": str(session_id), "location_id": "crossroads"}
