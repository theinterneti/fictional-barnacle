"""v2.1 playtester bundle contract tests for S68/S69/S70."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tta.models.game import SubmitTurnRequest
from tta.models.v21_playtester import (
    CorrelationIds,
    DeathPreference,
    LocalMapResponse,
    MechanicsConsequence,
    MechanicsRequest,
    MechanicsResolution,
    MechanicsResolutionResult,
    MechanicsResolverProtocol,
    PlayMode,
    RouteDiscoveryState,
    RouteNode,
    RouteVisibility,
    TravelTimeEstimate,
    TurnInputSource,
    TurnMetadata,
    sanitize_correlation_ids,
)


@pytest.mark.spec("AC-68.02")
@pytest.mark.spec("AC-68.03")
def test_turn_metadata_pins_input_source_values_and_sanitizes_correlation_ids():
    metadata = TurnMetadata(
        input_source=TurnInputSource.suggested_choice,
        correlation_ids=sanitize_correlation_ids(
            {
                "trace_id": "trace-123",
                "evaluation_id": "eval_456",
                "provider_api_key": "secret",
                "raw_prompt": "do not leak this",
                "bad spaces": "bad",
            }
        ),
    )

    dumped = metadata.model_dump(mode="json")

    assert dumped["input_source"] == "suggested_choice"
    correlation_ids = dumped["correlation_ids"]
    assert isinstance(correlation_ids, dict)
    assert correlation_ids == {
        "trace_id": "trace-123",
        "evaluation_id": "eval_456",
    }
    assert "provider_api_key" not in correlation_ids
    assert "raw_prompt" not in correlation_ids


@pytest.mark.spec("AC-68.02")
@pytest.mark.spec("AC-68.03")
def test_submit_turn_request_accepts_optional_s68_metadata_object():
    request = SubmitTurnRequest(
        input="Take the north road",
        idempotency_key=None,
        traffic_class=None,
        metadata=TurnMetadata(input_source=TurnInputSource.free_text).model_dump(),
    )

    assert request.metadata == {
        "input_source": "free_text",
        "correlation_ids": {},
    }


@pytest.mark.spec("AC-69.01")
@pytest.mark.spec("AC-69.02")
@pytest.mark.spec("AC-69.03")
@pytest.mark.spec("AC-69.06")
def test_mechanics_resolution_contract_serializes_without_final_prose():
    resolution = MechanicsResolution(
        resolution_id="mech-001",
        request=MechanicsRequest(
            game_id="game-1",
            session_id="session-1",
            turn_id="turn-1",
            player_input="Leap across the broken bridge",
            play_mode=PlayMode.world_based,
            death_preference=DeathPreference.no_death,
            available_domains=["physical", "survival"],
        ),
        risk_level="risky",
        domain="physical",
        result=MechanicsResolutionResult.failure_with_consequence,
        consequence=MechanicsConsequence(
            summary="The jump fails but becomes a survivable setback.",
            narrative_constraint=(
                "Do not kill the player; turn failure into injury or loss."
            ),
            player_explanation=(
                "You fail the jump, but your no-death preference changes the outcome."
            ),
        ),
        stakes=["injury", "lost_gear"],
        influenced_by_preferences=["play_mode", "death_preference"],
    )

    dumped = resolution.model_dump(mode="json")

    assert dumped["resolution_id"] == "mech-001"
    assert dumped["request"]["play_mode"] == "world_based"
    assert dumped["request"]["death_preference"] == "no_death"
    assert dumped["risk_level"] == "risky"
    assert dumped["result"] == "failure_with_consequence"
    assert "narrative_output" not in dumped
    assert "final_prose" not in dumped


@pytest.mark.spec("AC-69.02")
def test_mechanics_resolver_protocol_accepts_structural_implementations():
    class StubResolver:
        def resolve(self, request: MechanicsRequest) -> MechanicsResolution:
            return MechanicsResolution(
                resolution_id="mech-002",
                request=request,
                risk_level="trivial",
                domain="physical",
                result=MechanicsResolutionResult.success,
                consequence=MechanicsConsequence(
                    summary="The action succeeds cleanly.",
                    narrative_constraint="Allow straightforward success.",
                ),
            )

    resolver: MechanicsResolverProtocol = StubResolver()
    request = MechanicsRequest(
        game_id="game-1",
        session_id="session-1",
        turn_id="turn-2",
        player_input="Open the unlocked door",
    )

    assert resolver.resolve(request).result == MechanicsResolutionResult.success


@pytest.mark.spec("AC-70.01")
@pytest.mark.spec("AC-70.02")
@pytest.mark.spec("AC-70.03")
def test_local_map_response_excludes_hidden_routes_from_player_facing_dump():
    known = RouteNode(
        route_id="route-known",
        from_location_id="town-square",
        to_location_id="forest-gate",
        label="North road",
        terrain_type="road",
        distance_value=2,
        distance_unit="km",
        travel_modes=["walk"],
        discovery_state=RouteDiscoveryState.known,
        estimated_travel_time=TravelTimeEstimate(value=24, unit="minutes"),
    )
    hidden = RouteNode(
        route_id="route-hidden",
        from_location_id="town-square",
        to_location_id="smuggler-tunnel",
        label="Loose cellar stones",
        terrain_type="underground",
        distance_value=0.2,
        distance_unit="km",
        travel_modes=["crawl"],
        discovery_state=RouteDiscoveryState.hidden,
        visibility=RouteVisibility.hidden,
        estimated_travel_time=TravelTimeEstimate(value=10, unit="minutes"),
        secret_metadata={"reveal_condition": "pull-library-sconce"},
    )

    response = LocalMapResponse(
        current_location_id="town-square",
        current_location_name="Town Square",
        routes=[known, hidden],
    )

    dumped = response.player_facing_dump()

    assert dumped == {
        "current_location_id": "town-square",
        "current_location_name": "Town Square",
        "routes": [known.player_facing_dump()],
    }
    assert "route-hidden" not in str(dumped)
    assert "pull-library-sconce" not in str(dumped)


@pytest.mark.spec("AC-70.02")
def test_route_contract_rejects_invalid_distance_and_empty_travel_modes():
    with pytest.raises(ValidationError):
        RouteNode(
            route_id="bad-route",
            from_location_id="a",
            to_location_id="b",
            label="Broken",
            terrain_type="road",
            distance_value=-1,
            distance_unit="km",
            travel_modes=[],
            discovery_state=RouteDiscoveryState.known,
            estimated_travel_time=TravelTimeEstimate(value=0, unit="minutes"),
        )


@pytest.mark.spec("AC-68.04")
def test_correlation_ids_do_not_accept_secret_like_keys():
    with pytest.raises(ValidationError):
        CorrelationIds(ids={"api_token": "should-fail"})
