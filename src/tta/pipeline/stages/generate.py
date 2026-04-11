"""Generate stage — LLM narrative generation and world extraction.

Builds a generation prompt, runs safety_pre_gen and safety_post_gen
hooks, calls the LLM for narrative, then extracts world changes.
(plans/llm-and-pipeline.md §5)
"""

from __future__ import annotations

import json

import structlog

from tta.llm.client import Message, MessageRole
from tta.llm.roles import ModelRole
from tta.models.turn import TurnState, TurnStatus
from tta.pipeline.llm_guard import guarded_llm_call
from tta.pipeline.types import PipelineDeps

log = structlog.get_logger()

_GENERATION_SYSTEM_PROMPT = (
    "You are a narrative game engine. "
    "Write immersive second-person prose responding to the player's "
    "action within the current world context. "
    "Keep responses concise (2-4 paragraphs)."
)

_EXTRACTION_SYSTEM_PROMPT = (
    "Extract world state changes and suggested actions from the narrative. "
    "Return a JSON object with two keys:\n"
    '  "world_changes": an array of objects with keys '
    "'entity', 'attribute', 'old_value', 'new_value', 'reason'. "
    "Use an empty array if nothing changed.\n"
    '  "suggested_actions": an array of exactly 3 short strings — '
    "distinct actions the player could take next.\n"
    "Example: "
    '{"world_changes": [], "suggested_actions": ["Look around", '
    '"Talk to the stranger", "Open the chest"]}'
)


def _build_generation_prompt(state: TurnState) -> str:
    """Build the user prompt from pipeline state."""
    intent = state.parsed_intent.intent if state.parsed_intent else "unknown"
    context_str = json.dumps(state.world_context or {}, default=str)
    parts = [
        f"Player action: {state.player_input}",
        f"Intent: {intent}",
        f"World context: {context_str}",
    ]
    if state.consequence_hints:
        hints = "; ".join(state.consequence_hints)
        parts.append(
            f"\nSubtle foreshadowing (weave naturally, do not state directly): {hints}"
        )
    if state.active_consequences:
        parts.append(f"\nActive consequence chains: {len(state.active_consequences)}")
    parts.append("\nGenerate a narrative response.")
    return "\n".join(parts)


async def generate_stage(state: TurnState, deps: PipelineDeps) -> TurnState:
    """Generate narrative and extract world changes."""
    # 1. Build generation prompt
    prompt = _build_generation_prompt(state)
    state = state.model_copy(update={"generation_prompt": prompt})

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

    # 3. Call LLM for narrative generation
    # Use prompt registry if available, else fall back to hardcoded
    gen_system = _GENERATION_SYSTEM_PROMPT
    if deps.prompt_registry and deps.prompt_registry.has("narrative.generate"):
        rendered = deps.prompt_registry.render(
            "narrative.generate",
            {
                "player_input": state.player_input,
                "world_context": state.world_context or "",
            },
        )
        gen_system = rendered.text

    messages = [
        Message(role=MessageRole.SYSTEM, content=gen_system),
        Message(role=MessageRole.USER, content=prompt),
    ]
    response = await guarded_llm_call(deps, ModelRole.GENERATION, messages)

    # 4. Post-generation safety check
    safety_post = await deps.safety_post_gen.post_generation_check(
        response.content, state
    )
    if not safety_post.safe:
        log.warning(
            "safety_blocked_post_gen",
            session_id=str(state.session_id),
            flags=safety_post.flags,
        )
        # Buffer-then-stream moderation: the full LLM output is
        # moderated before any SSE events are sent to the client.
        # On block the redirect narrative replaces the original
        # content (AC-24.2) and the SSE layer emits a ModerationEvent.
        if safety_post.modified_content:
            import hashlib

            content_hash = hashlib.sha256(response.content.encode()).hexdigest()
            # Log content_hash for audit correlation (FR-24.14).
            # Raw content is stored only in moderation_records DB
            # via ModerationRecorder, not in general logs.
            log.warning(
                "moderation_blocked_output",
                session_id=str(state.session_id),
                flags=safety_post.flags,
                content_hash=content_hash,
                blocked_content_length=len(response.content),
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

    narrative = safety_post.modified_content or response.content

    # 5. Extract world changes + suggested actions via LLM
    world_updates, suggestions = await _extract_world_changes(
        narrative, state.player_input, deps
    )

    # Merge consequence-originated updates with extraction-originated ones
    prior = list(state.world_state_updates or [])
    merged = prior + (world_updates or [])

    return state.model_copy(
        update={
            "narrative_output": narrative,
            "model_used": response.model_used,
            "token_count": response.token_count,
            "world_state_updates": merged if merged else [],
            "suggested_actions": suggestions or None,
        }
    )


async def _extract_world_changes(
    narrative: str,
    player_input: str,
    deps: PipelineDeps,
) -> tuple[list[dict], list[str]]:
    """Extract world state changes and suggested actions from narrative.

    Returns ``(world_changes, suggested_actions)`` — both default to
    empty lists on any failure (extraction is best-effort).
    """
    messages = [
        Message(role=MessageRole.SYSTEM, content=_EXTRACTION_SYSTEM_PROMPT),
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
