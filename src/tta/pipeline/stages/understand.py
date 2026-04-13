"""Understand stage — intent classification and input safety.

Rules-first classification with LLM fallback for ambiguous input.
Runs safety_pre_input hook before classification.
(plans/llm-and-pipeline.md §3)
"""

from __future__ import annotations

import re

import structlog

from tta.api.errors import AppError
from tta.choices.classifier import classify_choice
from tta.llm.client import Message, MessageRole
from tta.llm.roles import ModelRole
from tta.models.turn import ParsedIntent, TurnState, TurnStatus
from tta.pipeline.llm_guard import guarded_llm_call
from tta.pipeline.types import PipelineDeps
from tta.prompts.loader import log_injection_signals

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

# Inline classification prompt removed in Wave 28 (S09 AC-09.1).
# System prompt managed via FilePromptRegistry: classification.intent


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
        # When a redirect narrative is available, deliver it to the
        # player instead of failing the turn outright (AC-24.2).
        # Status is `moderated` so the SSE emits a ModerationEvent
        # and the orchestrator early-exits (FR-24.06).
        if safety_result.modified_content:
            return state.model_copy(
                update={
                    "status": TurnStatus.moderated,
                    "narrative_output": safety_result.modified_content,
                    "safety_flags": safety_result.flags,
                }
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
        # Use prompt registry for system content (AC-09.1).
        # Keep SYSTEM message free of user input to reduce prompt-injection risk.
        if not deps.prompt_registry or not deps.prompt_registry.has(
            "classification.intent"
        ):
            log.error("classification_template_missing")
            return state.model_copy(
                update={
                    "parsed_intent": ParsedIntent(intent="other", confidence=0.3),
                }
            )
        try:
            rendered = deps.prompt_registry.render("classification.intent", {})
        except Exception:
            log.error(
                "classification_template_render_failed",
                template_id="classification.intent",
                exc_info=True,
            )
            return state.model_copy(
                update={
                    "parsed_intent": ParsedIntent(intent="other", confidence=0.3),
                }
            )
        system_content = rendered.text

        # Observe-only injection scan on player input (AC-09.8).
        log_injection_signals(state.player_input, context="understand_player_input")

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=system_content,
            ),
            Message(role=MessageRole.USER, content=state.player_input),
        ]
        try:
            response = await guarded_llm_call(deps, ModelRole.CLASSIFICATION, messages)
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
        except AppError:
            raise
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
    classified_state = _enrich_choice_classification(intent_state)

    # 5. Consequence evaluation (S05 FR-3) — evaluate pending consequences
    classified_state = await _evaluate_consequences(classified_state, deps)

    # 6. Prune dormant/excess chains (S05 AC-5.8)
    classified_state = await _prune_consequence_chains(classified_state, deps)

    return classified_state


async def _evaluate_consequences(state: TurnState, deps: PipelineDeps) -> TurnState:
    """Evaluate pending consequences for this turn. Non-blocking."""
    consequence_svc = getattr(deps, "consequence_service", None)
    if consequence_svc is None:
        return state
    try:
        result = await consequence_svc.evaluate(
            state.session_id, state.turn_number, state.player_input
        )
        updates: dict[str, object] = {}
        if result.hints:
            updates["consequence_hints"] = result.hints
        if result.chain_updates:
            updates["active_consequences"] = result.chain_updates
        if result.world_changes:
            existing = list(state.world_state_updates or [])
            existing.extend(
                {
                    "entity": wc.entity_id,
                    "attribute": str(wc.type),
                    "new_value": wc.payload.get("value", ""),
                    "reason": wc.payload.get("reason", "consequence"),
                }
                for wc in result.world_changes
            )
            updates["world_state_updates"] = existing
        if updates:
            return state.model_copy(update=updates)
    except Exception:
        log.warning("consequence_evaluation_failed", exc_info=True)
    return state


async def _prune_consequence_chains(state: TurnState, deps: PipelineDeps) -> TurnState:
    """Prune dormant/excess chains and capture closure descriptions (S05 AC-5.8)."""
    consequence_svc = getattr(deps, "consequence_service", None)
    if consequence_svc is None:
        return state
    try:
        _pruned_ids, closures = await consequence_svc.prune_chains(
            state.session_id, state.turn_number
        )
        if closures:
            return state.model_copy(update={"pruned_chain_closures": closures})
    except Exception:
        log.warning("consequence_pruning_failed", exc_info=True)
    return state


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
