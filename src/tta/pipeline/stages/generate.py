"""Generate stage — LLM narrative generation and world extraction.

Builds a generation prompt, runs safety_pre_gen and safety_post_gen
hooks, calls the LLM for narrative, then extracts world changes.
(plans/llm-and-pipeline.md §5)
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

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
from tta.prompts.registry import RenderedPrompt

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
    "Somewhere nearby, a sound catches your attention — "
    "faint and familiar, yet just beyond recognition. "
    "After a moment, everything steadies. "
    "The world is still here, waiting for your next move."
)

_MAX_TRANSIENT_RETRIES = 2

_CONTEXT_META_KEYS = {
    "tone",
    "genre",
    "session_summary",
    "npc_dialogue_contexts",
    "active_companions",
}


def _parse_extraction_response(content: str) -> dict[str, Any] | list[Any] | None:
    """Extract JSON payload from extraction-model output.

    Handles raw JSON, fenced JSON, and JSON objects/lists embedded in prose.
    Returns None when no parseable JSON payload is found.
    """
    stripped = content.strip()
    if not stripped:
        return None

    decoder = json.JSONDecoder()
    candidates = [stripped]

    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", content, re.DOTALL)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(parsed, (dict, list)):
                return parsed

    start_positions = sorted(
        {idx for idx in (content.find("{"), content.find("[")) if idx != -1}
    )
    for start in start_positions:
        try:
            parsed, _ = decoder.raw_decode(content[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed

    return None


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
        # Knowledge boundary (S06 AC-6.9)
        if ctx.get("knowledge_boundary"):
            parts.append(f"  Knows about: {ctx['knowledge_boundary']}")
        # Shared history with player (S06 AC-6.8)
        if ctx.get("shared_history"):
            parts.append(f"  History with player: {ctx['shared_history']}")
        # Revealed goals influence dialogue (S06 AC-6.6)
        if ctx.get("goals_short"):
            parts.append(
                f"  {name} subtly steers conversation toward: {ctx['goals_short']}"
            )
        lines.extend(parts)
    lines.append(
        "Write each NPC's dialogue in their distinct voice and mannerisms. "
        "NPCs must not share information outside their knowledge boundary."
    )
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

    # Genesis element references for early-turn continuity (S02 AC-2.3)
    genesis_elems = wc.get("genesis_elements")
    if genesis_elems and isinstance(genesis_elems, list):
        joined = "; ".join(genesis_elems[:10])
        parts.append(
            f"\nEstablished world elements: {joined}. "
            "Reference at least two of these by name in your response."
        )

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

    # Exploration hook guidance (S03 AC-3.8)
    if intent in ("examine", "move"):
        parts.append(
            "End with a subtle narrative hook — a detail, sound, or glimpse "
            "that invites further exploration."
        )

    # Failure-consequence instruction (S01 AC-1.5)
    parts.append(
        "If the action fails or has negative outcomes, narrate the failure "
        "as a meaningful story beat with visible consequences."
    )

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
    wc = state.world_context or {}
    context_data = {k: v for k, v in wc.items() if k not in _CONTEXT_META_KEYS}
    log.info(
        "generation_prompt_built",
        session_id=str(state.session_id),
        turn_number=state.turn_number,
        context_partial=state.context_partial,
        prompt_len=len(prompt),
        world_context_keys=sorted(wc.keys()),
        world_context_size=len(json.dumps(wc, default=str)),
        context_data_size=len(json.dumps(context_data, default=str)),
        active_consequences_count=len(state.active_consequences or []),
        consequence_hints_count=len(state.consequence_hints or []),
        pruned_chain_closures_count=len(state.pruned_chain_closures or []),
    )
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
    gen_system, rendered_system_prompt = await _resolve_system_prompt(deps)
    messages = [
        Message(role=MessageRole.SYSTEM, content=gen_system),
        Message(role=MessageRole.USER, content=prompt),
    ]

    narrative: str | None = None
    degraded = False
    response: LLMResponse | None = None

    try:
        llm_start = time.monotonic()
        response = await _llm_with_retries(
            messages,
            deps,
            state,
            prompt_id=rendered_system_prompt.template_id,
            prompt_version=rendered_system_prompt.template_version,
            fragment_versions=rendered_system_prompt.fragment_versions,
            prompt_hash=rendered_system_prompt.prompt_hash,
            langfuse_prompt=rendered_system_prompt.metadata.get("langfuse_prompt"),
            generation_profile=state.generation_profile,
            traffic_class=state.traffic_class,
        )
        llm_elapsed_ms = (time.monotonic() - llm_start) * 1000
        narrative = response.content
        log.info(
            "generation_llm_succeeded",
            session_id=str(state.session_id),
            turn_number=state.turn_number,
            model_used=response.model_used,
            llm_elapsed_ms=round(llm_elapsed_ms, 1),
            narrative_len=len(narrative or ""),
            token_count=(
                response.token_count.model_dump() if response.token_count else None
            ),
        )
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

    extract_start = time.monotonic()
    try:
        world_updates, suggestions = await _extract_world_changes(
            narrative,
            state.player_input,
            deps,
            traffic_class=state.traffic_class,
        )
    except TimeoutError:
        extract_elapsed_ms = (time.monotonic() - extract_start) * 1000
        log.warning(
            "generation_extraction_timeout",
            session_id=str(state.session_id),
            turn_number=state.turn_number,
            extraction_elapsed_ms=round(extract_elapsed_ms, 1),
            model_used=response.model_used if response else "fallback",
            narrative_len=len(narrative),
            exc_info=True,
        )
        world_updates = []
        suggestions = []
    else:
        extract_elapsed_ms = (time.monotonic() - extract_start) * 1000
        log.info(
            "generation_extraction_complete",
            session_id=str(state.session_id),
            turn_number=state.turn_number,
            extraction_elapsed_ms=round(extract_elapsed_ms, 1),
            world_updates_count=len(world_updates or []),
            suggested_actions_count=len(suggestions or []),
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


async def _resolve_system_prompt(deps: PipelineDeps) -> tuple[str, RenderedPrompt]:
    """Resolve generation system prompt from registry (AC-09.1).

    Templates are the single source of truth — no inline fallback.
    When the Langfuse bridge is active, rendering goes through it to
    attach prompt provenance metadata (AC-09.7 / FB-005).
    """
    if not deps.prompt_registry or not deps.prompt_registry.has("narrative.generate"):
        log.error("generation_template_missing")
        raise AppError(
            ErrorCategory.INTERNAL_ERROR,
            "TEMPLATE_MISSING",
            "Narrative generation template not available",
        )
    rendered = await deps.render_prompt("narrative.generate")
    return rendered.text, rendered


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
    *,
    prompt_id: str | None = None,
    prompt_version: str | None = None,
    fragment_versions: dict[str, str] | None = None,
    prompt_hash: str | None = None,
    langfuse_prompt: Any | None = None,
    generation_profile: str | None = None,
    traffic_class: str | None = None,
) -> LLMResponse:
    """Call LLM with retry cascade for transient failures (S03 FR-8).

    Tier 1: retry with same messages
    Tier 2: retry with simplified prompt (no world context JSON)
    Raises on non-transient or all-tiers-exhausted errors.
    """
    last_exc: Exception | None = None
    serving_kwargs: dict[str, Any] = {}
    if generation_profile is not None:
        serving_kwargs["generation_profile"] = generation_profile
    resolved_traffic_class = traffic_class or state.traffic_class
    if resolved_traffic_class is not None:
        serving_kwargs["traffic_class"] = resolved_traffic_class

    for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
        try:
            return await guarded_llm_call(
                deps,
                ModelRole.GENERATION,
                messages,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                fragment_versions=fragment_versions,
                prompt_hash=prompt_hash,
                langfuse_prompt=langfuse_prompt,
                **serving_kwargs,
            )
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
    *,
    traffic_class: str | None = None,
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
        extraction_prompt = await deps.render_prompt("extraction.world-changes")
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
        response = await guarded_llm_call(
            deps,
            ModelRole.EXTRACTION,
            messages,
            prompt_id=extraction_prompt.template_id,
            prompt_version=extraction_prompt.template_version,
            fragment_versions=extraction_prompt.fragment_versions,
            prompt_hash=extraction_prompt.prompt_hash,
            langfuse_prompt=extraction_prompt.metadata.get("langfuse_prompt"),
            traffic_class=traffic_class,
        )
        parsed = _parse_extraction_response(response.content)
        if parsed is None:
            return [], []

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
