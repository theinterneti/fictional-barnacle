"""Understand stage — intent classification and input safety.

Rules-first classification with LLM fallback for ambiguous input.
Runs safety_pre_input hook before classification.
(plans/llm-and-pipeline.md §3)
"""

from __future__ import annotations

import re

import structlog

from tta.choices.classifier import classify_choice
from tta.llm.client import Message, MessageRole
from tta.llm.roles import ModelRole
from tta.models.turn import ParsedIntent, TurnState, TurnStatus
from tta.pipeline.types import PipelineDeps

log = structlog.get_logger()

VALID_INTENTS = frozenset({"move", "examine", "talk", "use", "meta", "other"})

# Ordered: meta first so "exit"/"quit" resolve to meta, not move.
INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "meta",
        re.compile(
            r"\b(help|save|quit|exit|menu|inventory|status)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "move",
        re.compile(
            r"\b(go|walk|move|run|head|travel|enter|leave)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "examine",
        re.compile(
            r"\b(look|examine|inspect|search|check|observe)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "talk",
        re.compile(
            r"\b(talk|say|ask|tell|speak|greet|whisper)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "use",
        re.compile(
            r"\b(use|take|grab|pick|drop|put|open|close|push|pull)\b",
            re.IGNORECASE,
        ),
    ),
]

_CLASSIFICATION_SYSTEM_PROMPT = (
    "Classify the player's intent into exactly one category. "
    "Respond with a single word: move, examine, talk, use, meta, or other. "
    "No explanation."
)


async def understand_stage(state: TurnState, deps: PipelineDeps) -> TurnState:
    """Classify player intent; block if safety check fails."""
    # 1. Safety check on player input
    safety_result = await deps.safety_pre_input.pre_generation_check(state)
    if not safety_result.safe:
        log.warning(
            "safety_blocked_input",
            session_id=str(state.session_id),
            flags=safety_result.flags,
        )
        return state.model_copy(
            update={
                "status": TurnStatus.failed,
                "safety_flags": safety_result.flags,
            }
        )

    # 2. Rules-first classification (ordered, meta has priority)
    player_input = state.player_input
    intent_state: TurnState | None = None

    for intent_name, pattern in INTENT_PATTERNS:
        if pattern.search(player_input):
            log.debug(
                "intent_classified_regex",
                intent=intent_name,
                input=player_input[:80],
            )
            intent_state = state.model_copy(
                update={
                    "parsed_intent": ParsedIntent(intent=intent_name, confidence=0.9),
                }
            )
            break

    # 3. LLM fallback for ambiguous input
    if intent_state is None:
        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=_CLASSIFICATION_SYSTEM_PROMPT,
            ),
            Message(role=MessageRole.USER, content=state.player_input),
        ]
        try:
            response = await deps.llm.generate(
                role=ModelRole.CLASSIFICATION, messages=messages
            )
            intent = response.content.strip().lower()
            if intent not in VALID_INTENTS:
                intent = "other"
            log.debug(
                "intent_classified_llm",
                intent=intent,
                input=player_input[:80],
            )
            intent_state = state.model_copy(
                update={
                    "parsed_intent": ParsedIntent(intent=intent, confidence=0.7),
                }
            )
        except Exception:
            log.warning(
                "llm_classification_failed",
                exc_info=True,
                fallback="other",
            )
            intent_state = state.model_copy(
                update={
                    "parsed_intent": ParsedIntent(intent="other", confidence=0.3),
                }
            )

    # 4. Choice classification (S05 FR-2) — non-blocking
    return _enrich_choice_classification(intent_state)


def _enrich_choice_classification(state: TurnState) -> TurnState:
    """Classify player input into choice type(s). Non-blocking."""
    try:
        intent = state.parsed_intent.intent if state.parsed_intent else "other"
        confidence = state.parsed_intent.confidence if state.parsed_intent else 0.3
        classification = classify_choice(
            player_input=state.player_input,
            intent=intent,
            confidence=confidence,
        )
        log.debug(
            "choice_classified",
            types=[str(t) for t in classification.types],
            primary=str(classification.primary_type),
        )
        return state.model_copy(update={"choice_classification": classification})
    except Exception:
        log.warning(
            "choice_classification_failed",
            exc_info=True,
        )
        return state
