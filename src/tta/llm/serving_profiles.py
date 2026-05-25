"""Canonical generation serving-profile policy resolution (S64 Phase 1)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GenerationServingProfile(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    QUALITY = "quality"


class GenerationTrafficClass(StrEnum):
    INTERACTIVE_PLAYER = "interactive_player"
    INTERACTIVE_SMOKE = "interactive_smoke"
    BULK_EVAL = "bulk_eval"
    QUALITY_BENCHMARK = "quality_benchmark"


@dataclass(frozen=True)
class GenerationPolicy:
    profile: GenerationServingProfile
    traffic_class: GenerationTrafficClass
    router_task: str
    latency_class: str
    dispatch_preference: str
    timeout_seconds: float
    max_tokens: int
    degradation_chain: tuple[GenerationServingProfile, ...]


_DEFAULT_PROFILE = GenerationServingProfile.BALANCED
_DEFAULT_TRAFFIC_CLASS = GenerationTrafficClass.INTERACTIVE_PLAYER


def default_generation_profile() -> GenerationServingProfile:
    return _DEFAULT_PROFILE


def default_generation_traffic_class() -> GenerationTrafficClass:
    return _DEFAULT_TRAFFIC_CLASS


def coerce_generation_profile(
    profile: GenerationServingProfile | str | None,
) -> GenerationServingProfile:
    if profile is None:
        return default_generation_profile()
    if isinstance(profile, GenerationServingProfile):
        return profile
    return GenerationServingProfile(profile)


def coerce_generation_traffic_class(
    traffic_class: GenerationTrafficClass | str | None,
) -> GenerationTrafficClass:
    if traffic_class is None:
        return default_generation_traffic_class()
    if isinstance(traffic_class, GenerationTrafficClass):
        return traffic_class
    return GenerationTrafficClass(traffic_class)


def degradation_chain_for(
    profile: GenerationServingProfile | str | None,
) -> tuple[GenerationServingProfile, ...]:
    resolved = coerce_generation_profile(profile)
    if resolved == GenerationServingProfile.QUALITY:
        return (
            GenerationServingProfile.BALANCED,
            GenerationServingProfile.FAST,
        )
    if resolved == GenerationServingProfile.BALANCED:
        return (GenerationServingProfile.FAST,)
    return ()


def resolve_generation_policy(
    profile: GenerationServingProfile | str | None = None,
    traffic_class: GenerationTrafficClass | str | None = None,
) -> GenerationPolicy:
    resolved_profile = coerce_generation_profile(profile)
    resolved_traffic = coerce_generation_traffic_class(traffic_class)

    if resolved_traffic in {
        GenerationTrafficClass.INTERACTIVE_PLAYER,
        GenerationTrafficClass.INTERACTIVE_SMOKE,
    }:
        if resolved_profile == GenerationServingProfile.FAST:
            router_task = "generation"
            latency_class = "interactive"
            dispatch_preference = "sync"
            timeout_seconds = 20.0
            max_tokens = 512
        elif resolved_profile == GenerationServingProfile.BALANCED:
            router_task = "generation"
            latency_class = "interactive"
            dispatch_preference = "sync"
            timeout_seconds = 35.0
            max_tokens = 768
        else:
            router_task = "creative"
            latency_class = "relaxed"
            dispatch_preference = "sync_or_compare"
            timeout_seconds = 60.0
            max_tokens = 1024
    elif resolved_traffic == GenerationTrafficClass.BULK_EVAL:
        if resolved_profile == GenerationServingProfile.FAST:
            router_task = "generation"
            latency_class = "batch"
            dispatch_preference = "queue_tolerant"
            timeout_seconds = 30.0
            max_tokens = 512
        elif resolved_profile == GenerationServingProfile.BALANCED:
            router_task = "generation"
            latency_class = "batch"
            dispatch_preference = "queue_tolerant"
            timeout_seconds = 45.0
            max_tokens = 768
        else:
            router_task = "creative"
            latency_class = "batch"
            dispatch_preference = "queue_tolerant_or_compare"
            timeout_seconds = 90.0
            max_tokens = 1024
    else:
        if resolved_profile == GenerationServingProfile.FAST:
            router_task = "generation"
            latency_class = "benchmark"
            dispatch_preference = "queue_tolerant"
            timeout_seconds = 45.0
            max_tokens = 512
        elif resolved_profile == GenerationServingProfile.BALANCED:
            router_task = "generation"
            latency_class = "benchmark"
            dispatch_preference = "queue_tolerant_or_compare"
            timeout_seconds = 75.0
            max_tokens = 768
        else:
            router_task = "creative"
            latency_class = "benchmark"
            dispatch_preference = "queue_tolerant_or_compare"
            timeout_seconds = 90.0
            max_tokens = 1024

    return GenerationPolicy(
        profile=resolved_profile,
        traffic_class=resolved_traffic,
        router_task=router_task,
        latency_class=latency_class,
        dispatch_preference=dispatch_preference,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        degradation_chain=degradation_chain_for(resolved_profile),
    )
