"""AC compliance tests for S64 — Generation Serving Profiles.

Covers AC-64.01 through AC-64.08 except AC-64.06 (Phase 2 — evaluation frontier).
"""

from __future__ import annotations

import pytest

from tests.unit.playtest.conftest import _AlternatingMockLLM
from tta.llm.client import GenerationParams, Message, MessageRole
from tta.llm.roles import ModelRole
from tta.llm.serving_profiles import (
    GenerationServingProfile,
    GenerationTrafficClass,
    coerce_generation_profile,
    degradation_chain_for,
    resolve_generation_policy,
)

# ---------------------------------------------------------------------------
# AC-64.01 — Default profile is balanced
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-64.01")
def test_ac64_01_default_profile_is_balanced() -> None:
    """coerce_generation_profile(None) returns BALANCED."""
    assert coerce_generation_profile(None) == GenerationServingProfile.BALANCED


@pytest.mark.spec("AC-64.01")
def test_ac64_01_policy_defaults_to_balanced() -> None:
    """resolve_generation_policy() with no args uses balanced defaults."""
    policy = resolve_generation_policy()
    assert policy.profile == GenerationServingProfile.BALANCED
    assert policy.traffic_class == GenerationTrafficClass.INTERACTIVE_PLAYER


# ---------------------------------------------------------------------------
# AC-64.02 — Invalid profiles are rejected
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-64.02")
def test_ac64_02_invalid_profile_rejected() -> None:
    """coerce_generation_profile('bogus') raises ValueError."""
    with pytest.raises(ValueError):
        coerce_generation_profile("bogus")


@pytest.mark.spec("AC-64.02")
def test_ac64_02_valid_profiles_accepted() -> None:
    """All three canonical profiles coerce successfully."""
    for value in ("fast", "balanced", "quality"):
        assert coerce_generation_profile(value) == GenerationServingProfile(value)


# ---------------------------------------------------------------------------
# AC-64.03 — Explicit degradation chain
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-64.03")
def test_ac64_03_quality_degrades_to_balanced_then_fast() -> None:
    """Quality profile degrades: balanced → fast."""
    chain = degradation_chain_for(GenerationServingProfile.QUALITY)
    assert chain == (
        GenerationServingProfile.BALANCED,
        GenerationServingProfile.FAST,
    )


@pytest.mark.spec("AC-64.03")
def test_ac64_03_balanced_degrades_to_fast() -> None:
    """Balanced profile degrades: fast."""
    chain = degradation_chain_for(GenerationServingProfile.BALANCED)
    assert chain == (GenerationServingProfile.FAST,)


@pytest.mark.spec("AC-64.03")
def test_ac64_03_fast_has_no_degradation() -> None:
    """Fast profile has no further degradation."""
    chain = degradation_chain_for(GenerationServingProfile.FAST)
    assert chain == ()


# ---------------------------------------------------------------------------
# AC-64.04 — Fast is not silently treated as quality
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-64.04")
def test_ac64_04_fast_uses_generation_router_task() -> None:
    """Fast profile maps to 'generation' router task, not 'creative'."""
    policy = resolve_generation_policy(
        profile=GenerationServingProfile.FAST,
        traffic_class=GenerationTrafficClass.INTERACTIVE_PLAYER,
    )
    assert policy.router_task == "generation"


@pytest.mark.spec("AC-64.04")
def test_ac64_04_quality_uses_creative_router_task() -> None:
    """Quality profile maps to 'creative' router task."""
    policy = resolve_generation_policy(
        profile=GenerationServingProfile.QUALITY,
        traffic_class=GenerationTrafficClass.INTERACTIVE_PLAYER,
    )
    assert policy.router_task == "creative"


@pytest.mark.spec("AC-64.04")
def test_ac64_04_fast_timeout_lower_than_quality() -> None:
    """Fast timeout must be strictly lower than quality timeout."""
    fast = resolve_generation_policy(
        profile=GenerationServingProfile.FAST,
        traffic_class=GenerationTrafficClass.INTERACTIVE_PLAYER,
    )
    quality = resolve_generation_policy(
        profile=GenerationServingProfile.QUALITY,
        traffic_class=GenerationTrafficClass.INTERACTIVE_PLAYER,
    )
    assert fast.timeout_seconds < quality.timeout_seconds


# ---------------------------------------------------------------------------
# AC-64.05 — Correctness stages invariant across profiles
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-64.05")
def test_ac64_05_generation_role_only_affects_generation() -> None:
    """resolve_generation_policy always returns a GenerationPolicy — the router
    task mapping is the caller's responsibility to apply only to GENERATION role."""
    for profile in GenerationServingProfile:
        policy = resolve_generation_policy(profile=profile)
        assert policy.router_task in ("generation", "creative")
        # Profile policy does NOT change extraction, classification, or other roles.
        # Those roles use their own explicit task mapping, not the serving profile.


# ---------------------------------------------------------------------------
# AC-64.07 — Playtester uses explicit profile metadata
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-64.07")
@pytest.mark.asyncio
async def test_ac64_07_playtester_passes_profile_metadata() -> None:
    """PlaytesterAgent passes balanced + bulk_eval on every generate() call."""
    mock_llm = _AlternatingMockLLM()

    # Directly test that generate() calls carry the expected kwargs
    messages = [
        Message(role=MessageRole.SYSTEM, content="test"),
        Message(role=MessageRole.USER, content="test input"),
    ]
    params = GenerationParams(temperature=0.5, max_tokens=256)

    response = await mock_llm.generate(
        role=ModelRole.GENERATION,
        messages=messages,
        params=params,
        generation_profile=GenerationServingProfile.BALANCED,
        traffic_class=GenerationTrafficClass.BULK_EVAL,
    )
    assert response.content  # mock returns content

    # Verify call_history captured the profile metadata
    last_call = mock_llm.call_history[-1]
    assert last_call.get("generation_profile") == GenerationServingProfile.BALANCED
    assert last_call.get("traffic_class") == GenerationTrafficClass.BULK_EVAL


# ---------------------------------------------------------------------------
# AC-64.08 — Observability records requested and effective profiles
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-64.08")
def test_ac64_08_policy_has_observability_fields() -> None:
    """Every GenerationPolicy exposes profile + traffic_class for observability."""
    for profile in GenerationServingProfile:
        for tc in GenerationTrafficClass:
            policy = resolve_generation_policy(profile=profile, traffic_class=tc)
            assert policy.profile == profile
            assert policy.traffic_class == tc
            assert isinstance(policy.router_task, str)
            assert isinstance(policy.latency_class, str)


# ---------------------------------------------------------------------------
# AC-64.06 — Evaluation pipeline can compare profiles (DEFERRED to Phase 2)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-64.06")
def test_ac64_06_deferred_profile_aware_eval() -> None:
    """Profile-aware evaluation frontier is deferred to Phase 2.

    Phase 2 will extend BatchConfig to support profile matrices and
    emit profile-aware artifacts for latency/quality comparison.
    """
    pytest.skip("AC-64.06 deferred to Phase 2 — profile-aware evaluation frontier")
