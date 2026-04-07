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
from tta.pipeline.types import PipelineDeps

log = structlog.get_logger()

_GENERATION_SYSTEM_PROMPT = (
    "You are a narrative game engine. "
    "Write immersive second-person prose responding to the player's "
    "action within the current world context. "
    "Keep responses concise (2-4 paragraphs)."
)

_EXTRACTION_SYSTEM_PROMPT = (
    "Extract world state changes from the narrative as a JSON array. "
    "Each element should be an object with keys: "
    "'entity' (what changed), 'attribute' (which property), "
    "'old_value' (previous value or null), 'new_value' (new value), "
    "and 'reason' (brief explanation). "
    "If no changes occurred, return an empty array: []"
)


def _build_generation_prompt(state: TurnState) -> str:
    """Build the user prompt from pipeline state."""
    intent = state.parsed_intent.intent if state.parsed_intent else "unknown"
    context_str = json.dumps(state.world_context or {}, default=str)
    return (
        f"Player action: {state.player_input}\n"
        f"Intent: {intent}\n"
        f"World context: {context_str}\n\n"
        "Generate a narrative response."
    )


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
    messages = [
        Message(role=MessageRole.SYSTEM, content=_GENERATION_SYSTEM_PROMPT),
        Message(role=MessageRole.USER, content=prompt),
    ]
    response = await deps.llm.generate(role=ModelRole.GENERATION, messages=messages)

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
        return state.model_copy(
            update={
                "status": TurnStatus.failed,
                "safety_flags": safety_post.flags,
            }
        )

    narrative = safety_post.modified_content or response.content

    # 5. Extract world changes via LLM
    world_updates = await _extract_world_changes(narrative, state.player_input, deps)

    return state.model_copy(
        update={
            "narrative_output": narrative,
            "model_used": response.model_used,
            "token_count": response.token_count,
            "world_state_updates": world_updates,
        }
    )


async def _extract_world_changes(
    narrative: str,
    player_input: str,
    deps: PipelineDeps,
) -> list[dict]:
    """Extract world state changes from narrative via LLM.

    Returns an empty list on any failure — extraction is best-effort.
    """
    messages = [
        Message(role=MessageRole.SYSTEM, content=_EXTRACTION_SYSTEM_PROMPT),
        Message(
            role=MessageRole.USER,
            content=(f"Narrative: {narrative}\nPlayer action: {player_input}"),
        ),
    ]
    try:
        response = await deps.llm.generate(role=ModelRole.EXTRACTION, messages=messages)
        parsed = json.loads(response.content)
        if not isinstance(parsed, list):
            return []
        # Validate each element is a dict with expected keys
        validated: list[dict] = []
        for item in parsed:
            if isinstance(item, dict) and "entity" in item:
                validated.append(item)
            else:
                log.debug("extraction_skipped_element", element=item)
        return validated
    except (json.JSONDecodeError, Exception):
        log.debug("extraction_parse_failed", exc_info=True)
        return []
