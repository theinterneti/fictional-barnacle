"""Choice classifier — maps parsed intent + player input to choice types.

Intent is mechanical (what the player is doing), choice type is semantic
(what category of decision this represents). Uses a deterministic mapping
for common cases, with LLM fallback for ambiguous/multi-label inputs.
(S05 FR-2)
"""

from __future__ import annotations

import re

import structlog

from tta.llm.client import LLMClient, Message, MessageRole
from tta.llm.roles import ModelRole
from tta.models.choice import (
    ChoiceClassification,
    ChoiceType,
    ImpactLevel,
    Reversibility,
)

log = structlog.get_logger()

# Deterministic intent → primary choice type mapping.
# Intent is mechanical (what verb), choice type is semantic (what kind of decision).
INTENT_CHOICE_MAP: dict[str, ChoiceType] = {
    "move": ChoiceType.MOVEMENT,
    "examine": ChoiceType.ACTION,
    "talk": ChoiceType.DIALOGUE,
    "use": ChoiceType.ACTION,
    "meta": ChoiceType.ACTION,
    "other": ChoiceType.ACTION,
}

# Secondary patterns that hint at additional/override choice types.
# These enrich beyond the primary intent mapping.
_MORAL_PATTERNS = re.compile(
    r"\b(steal|betray|lie|sacrifice|mercy|forgive|kill|spare|deceive"
    r"|help|protect|abandon|save)\b",
    re.IGNORECASE,
)
_STRATEGIC_PATTERNS = re.compile(
    r"\b(plan|prepare|set\s+up|ambush|negotiate|trade|bargain"
    r"|alliance|agree|deal|strategy)\b",
    re.IGNORECASE,
)
_REFUSAL_PATTERNS = re.compile(
    r"\b(refuse|reject|decline|no|won't|can't|don't|ignore"
    r"|walk\s+away|do\s+nothing|stay\s+silent)\b",
    re.IGNORECASE,
)

# Impact hints from input language (rough heuristic, not definitive).
_HIGH_IMPACT_PATTERNS = re.compile(
    r"\b(kill|destroy|betray|sacrifice|permanent|forever"
    r"|swear|vow|promise)\b",
    re.IGNORECASE,
)

_CLASSIFICATION_SYSTEM_PROMPT = (
    "Given a player's input in a text adventure game, classify the choice types. "
    "Respond with one or more comma-separated types from: "
    "action, dialogue, movement, strategic, moral, refusal. "
    "No explanation. Just the types."
)


def classify_choice(
    player_input: str,
    intent: str,
    confidence: float = 0.9,
) -> ChoiceClassification:
    """Classify a player's input into choice type(s) using rules.

    Returns a ChoiceClassification with types, impact, and reversibility.
    Uses intent→type mapping as primary, regex patterns for enrichment.
    """
    types: list[ChoiceType] = []

    # 1. Primary type from intent mapping
    primary = INTENT_CHOICE_MAP.get(intent, ChoiceType.ACTION)
    types.append(primary)

    # 2. Enrichment: detect moral/strategic/refusal overtones
    if _REFUSAL_PATTERNS.search(player_input) and ChoiceType.REFUSAL not in types:
        types.append(ChoiceType.REFUSAL)
    if _MORAL_PATTERNS.search(player_input) and ChoiceType.MORAL not in types:
        types.append(ChoiceType.MORAL)
    if _STRATEGIC_PATTERNS.search(player_input):
        if ChoiceType.STRATEGIC not in types:
            types.append(ChoiceType.STRATEGIC)

    # 3. Impact heuristic
    impact = ImpactLevel.ATMOSPHERIC
    if _HIGH_IMPACT_PATTERNS.search(player_input):
        impact = ImpactLevel.CONSEQUENTIAL

    # 4. Reversibility heuristic (moral/strategic choices are less reversible)
    reversibility = Reversibility.MODERATE
    if ChoiceType.MORAL in types:
        reversibility = Reversibility.SIGNIFICANT
    if _HIGH_IMPACT_PATTERNS.search(player_input):
        reversibility = Reversibility.PERMANENT

    return ChoiceClassification(
        types=types,
        impact=impact,
        reversibility=reversibility,
        confidence=confidence,
    )


async def classify_choice_with_llm(
    player_input: str,
    intent: str,
    llm: LLMClient,
) -> ChoiceClassification:
    """LLM-based classification for ambiguous inputs.

    Falls back to rules-based classification on LLM failure.
    """
    messages = [
        Message(
            role=MessageRole.SYSTEM,
            content=_CLASSIFICATION_SYSTEM_PROMPT,
        ),
        Message(role=MessageRole.USER, content=player_input),
    ]
    try:
        response = await llm.generate(role=ModelRole.CLASSIFICATION, messages=messages)
        raw_types = [t.strip().lower() for t in response.content.split(",")]
        valid_types = []
        for raw in raw_types:
            try:
                valid_types.append(ChoiceType(raw))
            except ValueError:
                continue
        if not valid_types:
            return classify_choice(player_input, intent, confidence=0.5)

        return ChoiceClassification(
            types=valid_types,
            confidence=0.7,
        )
    except Exception:
        log.warning(
            "choice_classification_llm_failed",
            exc_info=True,
            fallback="rules",
        )
        return classify_choice(player_input, intent, confidence=0.5)
