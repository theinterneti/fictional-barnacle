"""Generate stage — LLM narrative generation and world extraction.

Builds a generation prompt, runs safety_pre_gen and safety_post_gen
hooks, calls the LLM for narrative, then extracts world changes.
(plans/llm-and-pipeline.md §5)
"""

from __future__ import annotations

import json

import structlog

from tta.api.errors import AppError
from tta.errors import ErrorCategory
from tta.llm.client import LLMResponse, Message, MessageRole
from tta.llm.errors import (
    AllTiersFailedError,
    BudgetExceededError,
    PermanentLLMError,
    TransientLLMError,
)
from tta.llm.roles import ModelRole
from tta.models.choice import Reversibility
from tta.models.turn import TurnState, TurnStatus
from tta.pipeline.llm_guard import guarded_llm_call
from tta.pipeline.types import PipelineDeps
from tta.prompts.loader import log_injection_signals

log = structlog.get_logger()

# Inline prompt constants removed in Wave 28 (S09 AC-09.1).
# All system prompts are now managed via FilePromptRegistry templates:
#   narrative.generate, classification.intent, extraction.world-changes

# --- Adaptive word counts by intent (S03 FR-4.2, AC-3.8) ---

INTENT_WORD_RANGES: dict[str, tuple[int, int]] = {
    "move": (80, 150),
    "examine": (150, 300),
    "talk": (100, 250),
    "use": (80, 200),
    "meta": (50, 100),
    "other": (100, 200),
}

_DEFAULT_WORD_RANGE = (100, 200)

# --- Graceful fallback narrative (S03 FR-8.1, FR-8.2) ---

_FALLBACK_NARRATIVE = (
    "A strange stillness settles over the world around you. "
    "The air shimmers briefly, as though reality itself drew a breath. "
    "After a moment, everything steadies — "
    "the world is still here, waiting for your next move."
)

_MAX_TRANSIENT_RETRIES = 2

_CONTEXT_META_KEYS = {
    "tone",
    "genre",
    "session_summary",
    "npc_dialogue_contexts",
    "active_companions",
}


def _build_npc_section(npc_contexts: list[dict]) -> str:
    """Render a dedicated NPC prompt section for dialogue salience (S06 AC-6.5)."""
    lines = ["NPCs in this scene:"]
    for ctx in npc_contexts:
        name = ctx.get("npc_name", "Unknown")
        parts = [f"- {name}"]
        if ctx.get("personality"):
            parts.append(f"  Personality: {ctx['personality']}")
        if ctx.get("voice"):
            parts.append(f"  Voice: {ctx['voice']}")
        if ctx.get("mannerisms"):
            parts.append(f"  Mannerisms: {ctx['mannerisms']}")
        if ctx.get("disposition"):
            parts.append(f"  Disposition: {ctx['disposition']}")
        if ctx.get("occupation"):
            parts.append(f"  Occupation: {ctx['occupation']}")
        # Revealed goals influence dialogue (S06 AC-6.6)
        if ctx.get("goals_short"):
            parts.append(
                f"  {name} subtly steers conversation toward: {ctx['goals_short']}"
            )
        lines.extend(parts)
    lines.append("Write each NPC's dialogue in their distinct voice and mannerisms.")
    return "\n".join(lines)


def _build_generation_prompt(state: TurnState) -> str:
    """Build the user prompt from pipeline state."""
    intent = state.parsed_intent.intent if state.parsed_intent else "unknown"

    # Exclude meta keys from JSON dump to avoid duplication
    wc = state.world_context or {}
    context_data = {k: v for k, v in wc.items() if k not in _CONTEXT_META_KEYS}
    context_str = json.dumps(context_data, default=str)

    # Adaptive word count from intent (S03 FR-4.2)
    word_min, word_max = INTENT_WORD_RANGES.get(intent, _DEFAULT_WORD_RANGE)

    parts = [
        f"Player action: {state.player_input}",
        f"Intent: {intent}",
        f"World context: {context_str}",
    ]

    # Tone/genre injection (S03 FR-6.1)
    tone = wc.get("tone")
    genre = wc.get("genre")
    if tone or genre:
        style_parts = []
        if tone:
            style_parts.append(f"tone: {tone}")
        if genre:
            style_parts.append(f"genre: {genre}")
        parts.append(f"\nNarrative style: {', '.join(style_parts)}")

    # Session summary for long-game continuity (S03 FR-3.2)
    summary = wc.get("session_summary")
    if summary:
        parts.append(f"\nStory so far: {summary}")

    if state.consequence_hints:
        hints = "; ".join(state.consequence_hints)
        parts.append(
            f"\nSubtle foreshadowing (weave naturally, do not state directly): {hints}"
        )

    # Consequence narrative surfacing (S05 AC-5.1)
    if state.active_consequences:
        descs = [c.root_trigger for c in state.active_consequences if not c.is_resolved]
        if descs:
            joined = "; ".join(descs[:5])
            parts.append(
                f"\nConsequences manifesting: {joined}. "
                "Weave these effects naturally into the scene — "
                "show their impact through environment and character reactions."
            )

    # Permanent choice signals (S05 AC-5.4)
    cc = state.choice_classification
    if cc and cc.reversibility == Reversibility.PERMANENT:
        parts.append(
            "\nThis is a PERMANENT, irreversible choice. "
            "Signal its gravity through the environment: "
            "a charged atmosphere, NPC reactions that convey finality, "
            "environmental weight, and irreversible stakes. "
            "Do NOT narrate the player's internal thoughts or decisions."
        )

    # Divergence steering (S05 AC-5.10)
    if state.divergence_guidance:
        parts.append(f"\n{state.divergence_guidance}")

    # Dormant chain closure hints (S05 AC-5.8)
    if state.pruned_chain_closures:
        closure_text = "; ".join(state.pruned_chain_closures[:3])
        parts.append(
            f"\nFading story threads to resolve naturally: {closure_text}. "
            "Briefly acknowledge their conclusion in passing."
        )

    # NPC dialogue salience (S06 AC-6.5, AC-6.6)
    npc_contexts = wc.get("npc_dialogue_contexts")
    if npc_contexts and isinstance(npc_contexts, list):
        raw_ctxs = [
            c.model_dump() if hasattr(c, "model_dump") else c for c in npc_contexts
        ]
        if raw_ctxs:
            parts.append(f"\n{_build_npc_section(raw_ctxs)}")

    # Companion presence (S06 AC-6.7)
    companions = wc.get("active_companions")
    if companions and isinstance(companions, list):
        names = ", ".join(companions)
        parts.append(
            f"\nCompanion(s) present: {names}. "
            "Include them naturally in the scene — they may comment, "
            "react, assist, or offer perspective as fits their character."
        )

    parts.append(f"\nAim for {word_min}-{word_max} words.")
    parts.append("Generate a narrative response.")
    return "\n".join(parts)


async def generate_stage(state: TurnState, deps: PipelineDeps) -> TurnState:
    """Generate narrative and extract world changes.

    Implements a 3-tier retry cascade for transient LLM failures
    (S03 FR-8.1, FR-8.2). Non-transient failures (safety, budget,
    moderation) are never retried.
    """
    # 1. Build generation prompt
    prompt = _build_generation_prompt(state)
    state = state.model_copy(update={"generation_prompt": prompt})

    # Observe-only injection signal scan on USER content (AC-09.8)
    log_injection_signals(prompt, context="generate_user_message")

    # 2. Pre-generation safety check
    safety_pre = await deps.safety_pre_gen.pre_generation_check(state)
    if not safety_pre.safe:
        log.warning(
            "safety_blocked_pre_gen",
            session_id=str(state.session_id),
            flags=safety_pre.flags,
        )
        return state.model_copy(
            update={
                "status": TurnStatus.failed,
                "safety_flags": safety_pre.flags,
            }
        )

    # 3. Call LLM with transient-failure retry cascade
    gen_system = _resolve_system_prompt(deps)
    messages = [
        Message(role=MessageRole.SYSTEM, content=gen_system),
        Message(role=MessageRole.USER, content=prompt),
    ]

    narrative: str | None = None
    degraded = False
    response: LLMResponse | None = None

    try:
        response = await _llm_with_retries(messages, deps, state)
        narrative = response.content
    except (BudgetExceededError, AppError, PermanentLLMError):
        raise  # Non-transient — propagate immediately
    except (TransientLLMError, AllTiersFailedError):
        # All retries exhausted — use graceful in-world fallback
        log.warning(
            "generation_fallback_activated",
            session_id=str(state.session_id),
            exc_info=True,
        )
        narrative = _FALLBACK_NARRATIVE
        degraded = True

    # 4. Post-generation safety check
    safety_post = await deps.safety_post_gen.post_generation_check(narrative, state)
    if not safety_post.safe:
        log.warning(
            "safety_blocked_post_gen",
            session_id=str(state.session_id),
            flags=safety_post.flags,
        )
        if safety_post.modified_content:
            import hashlib

            content_hash = hashlib.sha256(narrative.encode()).hexdigest()
            log.warning(
                "moderation_blocked_output",
                session_id=str(state.session_id),
                flags=safety_post.flags,
                content_hash=content_hash,
                blocked_content_length=len(narrative),
            )
            return state.model_copy(
                update={
                    "status": TurnStatus.moderated,
                    "narrative_output": safety_post.modified_content,
                    "safety_flags": safety_post.flags,
                }
            )
        return state.model_copy(
            update={
                "status": TurnStatus.failed,
                "safety_flags": safety_post.flags,
            }
        )

    narrative = safety_post.modified_content or narrative

    # 5. Extract world changes (skip on degraded turns)
    if degraded:
        log.info(
            "extraction_skipped_degraded",
            session_id=str(state.session_id),
        )
        return state.model_copy(
            update={
                "narrative_output": narrative,
                "model_used": "fallback",
                "world_state_updates": list(state.world_state_updates or []),
                "suggested_actions": None,
            }
        )

    world_updates, suggestions = await _extract_world_changes(
        narrative, state.player_input, deps
    )

    prior = list(state.world_state_updates or [])
    merged = prior + (world_updates or [])

    return state.model_copy(
        update={
            "narrative_output": narrative,
            "model_used": response.model_used if response else "fallback",
            "token_count": response.token_count if response else None,
            "world_state_updates": merged if merged else [],
            "suggested_actions": suggestions or None,
        }
    )


def _resolve_system_prompt(deps: PipelineDeps) -> str:
    """Resolve generation system prompt from registry (AC-09.1).

    Templates are the single source of truth — no inline fallback.
    """
    if not deps.prompt_registry or not deps.prompt_registry.has("narrative.generate"):
        log.error("generation_template_missing")
        raise AppError(
            ErrorCategory.INTERNAL_ERROR,
            "TEMPLATE_MISSING",
            "Narrative generation template not available",
        )
    rendered = deps.prompt_registry.render("narrative.generate", {})
    return rendered.text


def _simplify_prompt(state: TurnState) -> str:
    """Build a shorter prompt without world context JSON for retry tier 2."""
    intent = state.parsed_intent.intent if state.parsed_intent else "unknown"
    word_min, word_max = INTENT_WORD_RANGES.get(intent, _DEFAULT_WORD_RANGE)
    return (
        f"Player action: {state.player_input}\n"
        f"Intent: {intent}\n"
        f"Aim for {word_min}-{word_max} words.\n"
        "Generate a narrative response."
    )


async def _llm_with_retries(
    messages: list[Message],
    deps: PipelineDeps,
    state: TurnState,
) -> LLMResponse:
    """Call LLM with retry cascade for transient failures (S03 FR-8).

    Tier 1: retry with same messages
    Tier 2: retry with simplified prompt (no world context JSON)
    Raises on non-transient or all-tiers-exhausted errors.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
        try:
            return await guarded_llm_call(deps, ModelRole.GENERATION, messages)
        except (TransientLLMError, AllTiersFailedError) as exc:
            last_exc = exc
            log.warning(
                "generation_retry",
                attempt=attempt + 1,
                max_retries=_MAX_TRANSIENT_RETRIES,
                session_id=str(state.session_id),
                error=str(exc),
            )
            # Tier 2: simplify prompt on second retry
            if attempt == 0:
                simplified = _simplify_prompt(state)
                messages = [
                    messages[0],
                    Message(role=MessageRole.USER, content=simplified),
                ]
        except (BudgetExceededError, AppError, PermanentLLMError):
            raise
        except Exception as exc:
            # Classify unknown exceptions
            from tta.llm.errors import classify_error

            err_cls = classify_error(exc)
            if err_cls is TransientLLMError:
                last_exc = exc
                log.warning(
                    "generation_retry_classified",
                    attempt=attempt + 1,
                    session_id=str(state.session_id),
                    error=str(exc),
                )
                continue
            raise

    # All retries exhausted — wrap as AllTiersFailedError for consistent handling
    errors = [last_exc] if last_exc else []
    raise AllTiersFailedError(ModelRole.GENERATION, errors)


async def _extract_world_changes(
    narrative: str,
    player_input: str,
    deps: PipelineDeps,
) -> tuple[list[dict], list[str]]:
    """Extract world state changes and suggested actions from narrative.

    Returns ``(world_changes, suggested_actions)`` — both default to
    empty lists on any failure (extraction is best-effort).
    """
    # Resolve extraction system prompt from registry (AC-09.1).
    if not deps.prompt_registry or not deps.prompt_registry.has(
        "extraction.world-changes"
    ):
        log.debug("extraction_template_missing")
        return [], []
    try:
        extraction_prompt = deps.prompt_registry.render("extraction.world-changes", {})
    except Exception:
        log.error(
            "extraction_template_render_failed",
            template_id="extraction.world-changes",
            exc_info=True,
        )
        return [], []
    messages = [
        Message(role=MessageRole.SYSTEM, content=extraction_prompt.text),
        Message(
            role=MessageRole.USER,
            content=(f"Narrative: {narrative}\nPlayer action: {player_input}"),
        ),
    ]
    try:
        response = await guarded_llm_call(deps, ModelRole.EXTRACTION, messages)
        parsed = json.loads(response.content)

        # New format: {"world_changes": [...], "suggested_actions": [...]}
        if isinstance(parsed, dict):
            raw_changes = parsed.get("world_changes", [])
            raw_suggestions = parsed.get("suggested_actions", [])
        elif isinstance(parsed, list):
            # Backwards-compatible: old format was a plain array
            raw_changes = parsed
            raw_suggestions = []
        else:
            return [], []

        # Validate world changes
        validated: list[dict] = []
        for item in raw_changes if isinstance(raw_changes, list) else []:
            if isinstance(item, dict) and "entity" in item:
                validated.append(item)
            else:
                log.debug("extraction_skipped_element", element=item)

        # Validate suggested actions: non-empty, distinct, at least 3
        suggestions: list[str] = []
        seen: set[str] = set()
        for item in raw_suggestions if isinstance(raw_suggestions, list) else []:
            if not isinstance(item, str):
                continue
            stripped = item.strip()
            if not stripped:
                continue
            normalised = stripped.casefold()
            if normalised in seen:
                continue
            seen.add(normalised)
            suggestions.append(stripped)

        if len(suggestions) < 3:
            log.debug(
                "extraction_insufficient_suggestions",
                count=len(suggestions),
            )
            return validated, []

        return validated, suggestions
    except (json.JSONDecodeError, Exception):
        log.debug("extraction_parse_failed", exc_info=True)
        return [], []
