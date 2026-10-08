"""Shared v2.1 playtester contracts for S68/S69/S70.

These models intentionally pin serialization contracts before UI, mechanics,
or graph-service implementation work begins. They are DTO-style contracts: no
Neo4j, FastAPI, or persistence dependencies belong here.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator, model_validator

_SAFE_CORRELATION_KEY = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "prompt",
    "provider",
    "model_config",
)
_ALLOWED_CORRELATION_KEYS = frozenset(
    {
        "trace_id",
        "evaluation_id",
        "eval_id",
        "run_id",
        "span_id",
        "turn_id",
        "route_id",
        "mechanics_result_id",
    }
)


class TurnInputSource(StrEnum):
    """S68 client turn input sources."""

    free_text = "free_text"
    suggested_choice = "suggested_choice"


class PlayMode(StrEnum):
    """S69 v2.1 selectable mechanics modes."""

    narrative_only = "narrative_only"
    world_based = "world_based"


class DeathPreference(StrEnum):
    """S69 v2.1 death/failure preferences."""

    no_death = "no_death"
    story_consequences = "story_consequences"


RiskLevel = Literal["trivial", "uncertain", "risky", "impossible"]
MechanicsDomain = Literal[
    "physical",
    "social",
    "knowledge",
    "survival",
    "magic",
    "technology",
    "mystery",
]
PreferenceInfluence = Literal["play_mode", "death_preference"]
TravelTimeUnit = Literal["minutes", "hours", "days"]
DistanceUnit = Literal["m", "km", "mi", "rooms", "steps"]
DiscoveryScope = Literal["game"]
Directionality = Literal["one_way", "two_way"]


class MechanicsResolutionResult(StrEnum):
    """Structured mechanics outcomes consumed by the narrative engine."""

    success = "success"
    success_with_cost = "success_with_cost"
    failure_with_consequence = "failure_with_consequence"
    impossible = "impossible"
    injury = "injury"
    resource_loss = "resource_loss"
    relationship_change = "relationship_change"
    location_change = "location_change"
    skipped = "skipped"


class RouteDiscoveryState(StrEnum):
    """S70 route discovery states."""

    known = "known"
    undiscovered = "undiscovered"
    hidden = "hidden"


class RouteVisibility(StrEnum):
    """Player-facing visibility derived from discovery state."""

    visible = "visible"
    hidden = "hidden"


class CorrelationIds(BaseModel):
    """Sanitized trace/evaluation identifiers safe for browser/export payloads."""

    ids: dict[str, str] = Field(default_factory=dict)

    @field_validator("ids")
    @classmethod
    def _validate_ids(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, raw in value.items():
            normalized = str(key).strip().lower()
            if normalized not in _ALLOWED_CORRELATION_KEYS:
                raise ValueError(f"unsupported correlation id key: {key}")
            if not _SAFE_CORRELATION_KEY.match(normalized):
                raise ValueError(f"unsafe correlation id key: {key}")
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                raise ValueError(f"secret-like correlation id key: {key}")
            text = str(raw).strip()
            if text:
                cleaned[normalized] = text[:128]
        return cleaned

    def model_dump(self, *args, **kwargs) -> dict[str, str]:  # type: ignore[override]
        """Serialize as the plain key/value map used in turn metadata."""

        return self.ids.copy()


class TurnMetadata(BaseModel):
    """Optional S68 metadata attached to a normal S10 turn request."""

    input_source: TurnInputSource
    correlation_ids: CorrelationIds = Field(default_factory=CorrelationIds)

    def model_dump(self, *args, **kwargs) -> dict[str, object]:  # type: ignore[override]
        return {
            "input_source": self.input_source.value,
            "correlation_ids": self.correlation_ids.model_dump(*args, **kwargs),
        }


class MechanicsRequest(BaseModel):
    """Input contract for world-based mechanics resolution."""

    game_id: str
    session_id: str
    turn_id: str
    player_input: str
    play_mode: PlayMode = PlayMode.narrative_only
    death_preference: DeathPreference = DeathPreference.story_consequences
    available_domains: list[MechanicsDomain] = Field(default_factory=list)
    current_location_id: str | None = None
    route_id: str | None = None


class MechanicsConsequence(BaseModel):
    """Narrative-engine constraints produced by mechanics, not final prose."""

    summary: str
    narrative_constraint: str
    player_explanation: str | None = None


class MechanicsResolution(BaseModel):
    """S69 structured result returned by a mechanics resolver."""

    resolution_id: str
    request: MechanicsRequest
    risk_level: RiskLevel
    domain: MechanicsDomain
    result: MechanicsResolutionResult
    consequence: MechanicsConsequence
    stakes: list[str] = Field(default_factory=list)
    influenced_by_preferences: list[PreferenceInfluence] = Field(default_factory=list)
    debug: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class MechanicsResolverProtocol(Protocol):
    """Replaceable S69 resolver seam for future OSS rules plugins."""

    def resolve(self, request: MechanicsRequest) -> MechanicsResolution: ...


class TravelTimeEstimate(BaseModel):
    """Deterministic travel estimate for a selected route/mode."""

    value: float = Field(gt=0)
    unit: TravelTimeUnit


class RouteNode(BaseModel):
    """S70 v2.1 route-node DTO independent of Neo4j storage details."""

    route_id: str
    from_location_id: str
    to_location_id: str
    label: str
    terrain_type: str
    distance_value: float = Field(gt=0)
    distance_unit: DistanceUnit
    travel_modes: list[str] = Field(min_length=1)
    directionality: Directionality = "two_way"
    discovery_scope: DiscoveryScope = "game"
    discovery_state: RouteDiscoveryState
    visibility: RouteVisibility = RouteVisibility.visible
    estimated_travel_time: TravelTimeEstimate
    blocked: bool = False
    blocked_reason: str | None = None
    encounter_tags: list[str] = Field(default_factory=list)
    coordinates: dict[str, float | str] | None = None
    secret_metadata: dict[str, object] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="after")
    def _derive_visibility(self) -> RouteNode:
        if self.discovery_state is not RouteDiscoveryState.known:
            self.visibility = RouteVisibility.hidden
        return self

    @property
    def is_player_visible(self) -> bool:
        return (
            self.discovery_state is RouteDiscoveryState.known
            and self.visibility is RouteVisibility.visible
        )

    def player_facing_dump(self) -> dict[str, object]:
        """Return the S70 local-map route shape with no hidden-route secrets."""

        return {
            "route_id": self.route_id,
            "from_location_id": self.from_location_id,
            "to_location_id": self.to_location_id,
            "label": self.label,
            "terrain_type": self.terrain_type,
            "travel_modes": list(self.travel_modes),
            "estimated_travel_time": self.estimated_travel_time.model_dump(mode="json"),
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "directionality": self.directionality,
            "discovery_scope": self.discovery_scope,
            "coordinates": self.coordinates,
        }


class LocalMapResponse(BaseModel):
    """S70 local-map JSON contract rendered by the S68 client."""

    current_location_id: str
    current_location_name: str
    routes: list[RouteNode] = Field(default_factory=list)

    def player_facing_dump(self) -> dict[str, object]:
        """Dump only visible routes; hidden/undiscovered routes never leak."""

        return {
            "current_location_id": self.current_location_id,
            "current_location_name": self.current_location_name,
            "routes": [
                route.player_facing_dump()
                for route in self.routes
                if route.is_player_visible
            ],
        }


def sanitize_correlation_ids(raw: dict[str, object]) -> CorrelationIds:
    """Drop unsafe trace/eval metadata keys and return a browser-safe map."""

    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        normalized = str(key).strip().lower()
        if normalized not in _ALLOWED_CORRELATION_KEYS:
            continue
        if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
            continue
        if not _SAFE_CORRELATION_KEY.match(normalized):
            continue
        text = str(value).strip()
        if text:
            cleaned[normalized] = text[:128]
    return CorrelationIds(ids=cleaned)
