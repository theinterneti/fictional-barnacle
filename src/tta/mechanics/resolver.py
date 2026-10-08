"""S69 deterministic mechanics resolver.

v2.1 classification and resolution without mandatory LLM calls.
Outputs structured facts/constraints consumed by the narrative
engine (S03/S08) — never final prose.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from tta.models.v21_playtester import (
    DeathPreference,
    MechanicsConsequence,
    MechanicsDomain,
    MechanicsRequest,
    MechanicsResolution,
    MechanicsResolutionResult,
    PlayMode,
    RiskLevel,
)

# ── keyword-driven classification ──────────────────────────────

_IMPOSSIBLE_WORDS = frozenset({"fly", "teleport", "one-shot"})
_RISKY_WORDS = frozenset({"attack", "steal", "climb", "sneak", "persuade", "cast"})
_TRIVIAL_WORDS = frozenset({"look", "wait", "rest", "sit"})

# Domain affinity: try to match from available domains, else physical.
_DOMAIN_AFFINITY: dict[str, MechanicsDomain] = {
    "attack": "physical",
    "steal": "social",
    "climb": "physical",
    "sneak": "physical",
    "persuade": "social",
    "cast": "magic",
    "fly": "physical",
    "teleport": "magic",
    "look": "knowledge",
    "wait": "survival",
    "rest": "survival",
    "sit": "social",
}


def classify_risk(
    request: MechanicsRequest,
) -> tuple[RiskLevel, MechanicsDomain]:
    """Deterministic v2.1 classification — no LLM call.

    Returns a ``(risk_level, domain)`` pair based on keyword
    matching against ``player_input``.
    """
    inp = request.player_input.lower()
    available = set(request.available_domains)

    # Impossible
    for word in _IMPOSSIBLE_WORDS:
        if word in inp:
            domain: MechanicsDomain = _DOMAIN_AFFINITY.get(word, "physical")
            return "impossible", domain

    # Risky
    for word in _RISKY_WORDS:
        if word in inp:
            domain = _pick_domain(word, available)
            return "risky", domain

    # Trivial
    for word in _TRIVIAL_WORDS:
        if word in inp:
            domain = _DOMAIN_AFFINITY.get(word, "knowledge")
            return "trivial", domain

    return "uncertain", "physical"


# ── resolution ─────────────────────────────────────────────────


def resolve(request: MechanicsRequest) -> MechanicsResolution:
    """Produce a structured ``MechanicsResolution`` for the request.

    In ``narrative_only`` mode the result is always ``skipped``.
    In ``world_based`` mode the resolver classifies risk and
    determines an outcome, respecting player death preference.
    """
    if request.play_mode == PlayMode.narrative_only:
        return _skipped(request)

    risk, domain = classify_risk(request)

    if risk == "impossible":
        result = MechanicsResolutionResult.impossible
    elif risk == "trivial":
        result = MechanicsResolutionResult.success
    else:
        result = _determine_outcome(risk, request.death_preference)

    return _build_resolution(request, risk=risk, domain=domain, result=result)


# ── internal helpers ───────────────────────────────────────────


def _pick_domain(word: str, available: set[MechanicsDomain]) -> MechanicsDomain:
    """Return the best domain for *word*, preferring available domains."""
    affinity: MechanicsDomain = _DOMAIN_AFFINITY.get(word, "physical")
    if available and affinity not in available:
        # Fall back to any available domain.
        return next(iter(available), "physical")
    return affinity


def _determine_outcome(
    risk: RiskLevel,
    death_preference: DeathPreference,
) -> MechanicsResolutionResult:
    """Pick an outcome, respecting the player's death preference.

    For demonstration v2.1 behaviour: risky actions default to
    ``failure_with_consequence`` unless death is disabled, in
    which case they map to ``injury`` or ``resource_loss``.
    """
    if risk != "risky":
        return MechanicsResolutionResult.success

    if death_preference == DeathPreference.no_death:
        return MechanicsResolutionResult.injury

    return MechanicsResolutionResult.failure_with_consequence


def _skipped(request: MechanicsRequest) -> MechanicsResolution:
    return _build_resolution(
        request,
        risk="trivial",
        domain="knowledge",
        result=MechanicsResolutionResult.skipped,
    )


def _build_resolution(
    request: MechanicsRequest,
    *,
    risk: RiskLevel,
    domain: MechanicsDomain,
    result: MechanicsResolutionResult,
) -> MechanicsResolution:
    return MechanicsResolution(
        resolution_id=str(uuid4()),
        request=request,
        risk_level=risk,
        domain=domain,
        result=result,
        consequence=MechanicsConsequence(
            summary=f"{risk} {domain} action resolved as {result.value}",
            narrative_constraint=f"outcome={result.value}",
        ),
        stakes=[],
        influenced_by_preferences=[],
        debug=_debug_payload(request, risk, domain, result),
    )


def _debug_payload(
    request: MechanicsRequest,
    risk: RiskLevel,
    domain: MechanicsDomain,
    result: MechanicsResolutionResult,
) -> dict[str, Any]:
    return {
        "play_mode": request.play_mode.value,
        "death_preference": request.death_preference.value,
        "risk": risk,
        "domain": domain,
        "result": result.value,
        "player_input": request.player_input[:100],
    }
