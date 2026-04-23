"""Context stage — assemble world context for generation.

Queries WorldService for live world data when available,
with graceful fallback to a basic context dict from game_state.
(plans/llm-and-pipeline.md §4)
"""

from __future__ import annotations

import structlog

from tta.models.turn import TurnState
from tta.models.world import NPC
from tta.pipeline.types import PipelineDeps
from tta.world.dialogue import build_dialogue_contexts_for_location
from tta.world.relationship_service import (
    COMPANION_AFFINITY_THRESHOLD,
    COMPANION_TRUST_THRESHOLD,
    RelationshipService,
)
from tta.world.state import get_full_context

log = structlog.get_logger()

# Player entity id used as source for relationship lookups
_PLAYER_SOURCE_ID = "player"


async def context_stage(state: TurnState, deps: PipelineDeps) -> TurnState:
    """Assemble world context for the generation prompt.

    Attempts to fetch live world data via WorldService.
    Falls back to a basic game_state dict if the service
    is unavailable or raises.
    """
    intent = state.parsed_intent.intent if state.parsed_intent else "unknown"

    # Try to get live world context from WorldService
    try:
        world_context = await get_full_context(deps.world, state.session_id)
        world_context["intent"] = intent
        world_context["turn_number"] = state.turn_number
        context_partial = False
    except Exception as exc:
        # Fallback: still try to get recent events from Postgres
        log.warning(
            "context_fallback",
            reason="world_service_unavailable",
            error=str(exc),
            exc_info=True,
        )
        recent_events: list[dict] = []
        try:
            events = await deps.world.get_recent_events(state.session_id, limit=5)
            recent_events = [e.model_dump(mode="json") for e in events]
        except Exception:
            log.warning(
                "context_events_fetch_failed",
                session_id=str(state.session_id),
                exc_info=True,
            )

        world_context = {
            "game_state": state.game_state,
            "intent": intent,
            "turn_number": state.turn_number,
            "session_id": str(state.session_id),
            "recent_events": recent_events,
        }
        context_partial = True

    # v2 S35 — NPC Autonomy (guarded: no-op for v1 sessions without universe_id)
    if deps.autonomy_processor is not None and deps.world_time_service is not None:
        universe_id = world_context.get("universe_id") or (
            state.game_state.get("universe_id")
            if isinstance(state.game_state, dict)
            else None
        )
        if universe_id:
            npcs = world_context.get("npcs_present", [])
            current_ticks = (
                state.game_state.get("world_time", {}).get("total_ticks", 0)
                if isinstance(state.game_state, dict)
                else 0
            )
            tick_delta = deps.world_time_service.tick(current_ticks)
            autonomy_delta = deps.autonomy_processor.process(
                universe_id=universe_id,
                world_time=tick_delta.world_time,
                npcs=npcs,
            )
            world_context["autonomous_changes"] = [
                {"npc_id": c.npc_id, "action_type": c.action_type, "after": c.after}
                for c in autonomy_delta.changes
            ]
            world_context["autonomous_events"] = [
                {
                    "event_id": e.event_id,
                    "description": e.description,
                    "severity": e.severity,
                }
                for e in autonomy_delta.events
            ]
            # v2 S36 — Consequence Propagation
            if deps.consequence_propagator is not None and autonomy_delta.events:
                from tta.simulation.types import PropagationSource

                sources = [
                    PropagationSource(
                        source_event_id=e.event_id,
                        source_type="npc_autonomy",
                        source_location_id=e.location_id or universe_id,
                        original_severity=e.severity,
                        description=e.description,
                    )
                    for e in autonomy_delta.events
                ]
                propagation_results = await deps.consequence_propagator.propagate(
                    source_events=sources,
                    universe_id=universe_id,
                    world_time=tick_delta.world_time,
                )
                world_context["propagated_consequences"] = [
                    {
                        "source_event_id": r.source_event_id,
                        "total_records": r.total_records,
                        "depth": r.propagation_depth_reached,
                    }
                    for r in propagation_results
                ]

            # v2 S37 — World Memory Recording
            if deps.memory_writer is not None:
                try:
                    _mem_content = str(
                        world_context.get("location_description", "")
                        or world_context.get("game_state", "")
                    )
                    _mem_cfg = (
                        state.game_state.get("memory_config", {})
                        if isinstance(state.game_state, dict)
                        else {}
                    )
                    await deps.memory_writer.record(
                        universe_id=universe_id,
                        session_id=state.session_id,
                        turn_number=state.turn_number,
                        world_time=tick_delta.world_time,
                        source="narrator",
                        content=_mem_content,
                        attributed_to=None,
                        tags=[],
                        consequence_ids=[],
                        npc_tier=None,
                        max_consequence_severity=None,
                    )
                    _mem_ctx = await deps.memory_writer.get_context(
                        universe_id=universe_id,
                        session_id=state.session_id,
                        current_tick=tick_delta.world_time.total_ticks,
                        budget_tokens=2000,
                        memory_config=_mem_cfg,
                    )
                    world_context["memory_context"] = {
                        "working": [r.content for r in _mem_ctx.working],
                        "active": [r.content for r in _mem_ctx.active],
                        "compressed": [r.content for r in _mem_ctx.compressed],
                    }
                except Exception:
                    log.warning("memory_writer_failed", exc_info=True)

    # Inject tone/genre from world seed (S03 FR-6.1)
    world_context = _inject_tone(world_context, state)

    # Inject genesis elements for early-turn continuity (S02 AC-2.3, AC-2.10)
    world_context = _inject_genesis_elements(world_context, state)

    # Inject existing session summary (S03 FR-3.2)
    world_context = _inject_summary(world_context, state)

    # Enrich with NPC dialogue contexts (S06 FR-6)
    world_context = await _enrich_npc_dialogue(world_context, state, deps)

    # Identify active companions from NPC dialogue contexts (S06 AC-6.7)
    world_context = _identify_companions(world_context)

    # Enrich with active consequence data (S05 FR-3)
    world_context = await _enrich_consequences(world_context, state, deps)

    # Populate TurnState.active_consequences from chain data
    active_consequence_chains = None
    divergence_guidance: str | None = None
    consequence_svc = getattr(deps, "consequence_service", None)
    if consequence_svc is not None:
        try:
            chains = await consequence_svc.get_active_chains(state.session_id)
            if chains:
                active_consequence_chains = chains
        except Exception:
            pass  # Already logged in _enrich_consequences

        # Divergence steering (S05 AC-5.10)
        try:
            score = await consequence_svc.calculate_divergence(
                state.session_id, state.turn_number
            )
            if score and score.needs_steering:
                anchors = await consequence_svc.get_active_anchors(state.session_id)
                # Pick the anchor matching nearest_anchor_id when available
                nearest_desc: str | None = None
                if anchors and score.nearest_anchor_id:
                    for a in anchors:
                        if a.id == score.nearest_anchor_id:
                            nearest_desc = a.description
                            break
                if nearest_desc is None and anchors:
                    nearest_desc = anchors[0].description
                if nearest_desc:
                    divergence_guidance = (
                        f"The story is diverging significantly "
                        f"(divergence {score.score:.1f}). "
                        f"Gently steer toward: {nearest_desc}"
                    )
                else:
                    divergence_guidance = (
                        f"The story is diverging significantly "
                        f"(divergence {score.score:.1f}). "
                        "Introduce narrative elements that reconnect "
                        "to established story threads."
                    )
        except Exception:
            log.warning(
                "divergence_calculation_failed",
                session_id=str(state.session_id),
                exc_info=True,
            )

    log.debug(
        "context_assembled",
        intent=intent,
        turn_number=state.turn_number,
        partial=context_partial,
    )

    update: dict = {
        "world_context": world_context,
        "context_partial": context_partial,
    }
    if active_consequence_chains is not None:
        update["active_consequences"] = active_consequence_chains
    if divergence_guidance is not None:
        update["divergence_guidance"] = divergence_guidance

    return state.model_copy(update=update)


def _inject_tone(world_context: dict, state: TurnState) -> dict:
    """Add tone from world seed to context (S03 FR-6.1)."""
    world_seed = state.game_state.get("world_seed")
    if isinstance(world_seed, dict):
        tone = world_seed.get("tone")
        if tone:
            world_context["tone"] = tone
        genre = world_seed.get("genre")
        if genre:
            world_context["genre"] = genre
    return world_context


# Genesis element threshold — inject elements for the first N gameplay turns
_GENESIS_ELEMENT_TURN_THRESHOLD = 3


def _inject_genesis_elements(world_context: dict, state: TurnState) -> dict:
    """Inject genesis elements into early turns for continuity (S02 AC-2.3).

    During the first few post-genesis turns, the generation prompt should
    reference key world elements (NPC names, location names, notable objects)
    established during genesis so the narrative feels continuous.
    """
    turn = state.turn_number
    if turn > _GENESIS_ELEMENT_TURN_THRESHOLD:
        return world_context

    world_seed = state.game_state.get("world_seed")
    if not isinstance(world_seed, dict):
        return world_context

    genesis = world_seed.get("genesis")
    if not isinstance(genesis, dict):
        return world_context

    elements = genesis.get("genesis_elements")
    if elements:
        world_context["genesis_elements"] = elements

    return world_context


def _inject_summary(world_context: dict, state: TurnState) -> dict:
    """Add existing session summary to context (S03 FR-3.2).

    Reuses the summary already persisted by ContextSummaryService
    via the game routes — no new persistence path.
    """
    summary = state.game_state.get("summary")
    if summary:
        world_context["session_summary"] = summary
    return world_context


def _identify_companions(world_context: dict) -> dict:
    """Tag NPCs meeting companion thresholds (S06 AC-6.7).

    Reads trust/affinity from npc_dialogue_contexts and stores qualifying
    NPC names in world_context['active_companions'].
    """
    npc_ctxs = world_context.get("npc_dialogue_contexts")
    if not npc_ctxs:
        return world_context
    companions: list[str] = []
    for ctx in npc_ctxs:
        obj = ctx.model_dump() if hasattr(ctx, "model_dump") else ctx
        trust = obj.get("relationship_trust")
        affinity = obj.get("relationship_affinity")
        if (
            trust is not None
            and affinity is not None
            and trust > COMPANION_TRUST_THRESHOLD
            and affinity > COMPANION_AFFINITY_THRESHOLD
        ):
            name = obj.get("npc_name", obj.get("npc_id", ""))
            if name:
                companions.append(name)
    if companions:
        world_context["active_companions"] = companions
    return world_context


_SHARED_HISTORY_TURN_LIMIT = 10
_SHARED_HISTORY_MAX_MENTIONS = 3


async def _inject_shared_history(
    dialogue_contexts: list[dict],
    state: TurnState,
    deps: PipelineDeps,
) -> list[dict]:
    """Populate shared_history for each NPC from recent turn narratives (S06 AC-6.8).

    Scans the last N turns for mentions of each NPC's name and builds
    brief history snippets so the LLM can reference past interactions.
    """
    if not dialogue_contexts:
        return dialogue_contexts

    turn_repo = getattr(deps, "turn_repo", None)
    if turn_repo is None:
        return dialogue_contexts

    try:
        recent = await turn_repo.get_recent_turns(
            state.session_id, limit=_SHARED_HISTORY_TURN_LIMIT
        )
    except Exception:
        log.debug("shared_history_fetch_failed", exc_info=True)
        return dialogue_contexts

    if not recent:
        return dialogue_contexts

    # Build name→mentions index (case-insensitive scan of narrative text)
    npc_names = {
        ctx.get("npc_name", "").lower(): ctx.get("npc_name", "")
        for ctx in dialogue_contexts
        if ctx.get("npc_name")
    }

    mentions: dict[str, list[str]] = {name_lower: [] for name_lower in npc_names}

    for turn_dict in recent:
        narrative = turn_dict.get("narrative_output") or ""
        turn_num = turn_dict.get("turn_number", "?")
        if not narrative:
            continue
        narrative_lower = narrative.lower()
        for name_lower, _display_name in npc_names.items():
            if (
                name_lower in narrative_lower
                and len(mentions[name_lower]) < _SHARED_HISTORY_MAX_MENTIONS
            ):
                # Extract a brief excerpt around the mention
                idx = narrative_lower.index(name_lower)
                start = max(0, idx - 40)
                end = min(len(narrative), idx + len(name_lower) + 60)
                snippet = narrative[start:end].strip()
                if start > 0:
                    snippet = "…" + snippet
                if end < len(narrative):
                    snippet = snippet + "…"
                mentions[name_lower].append(f"Turn {turn_num}: {snippet}")

    # Inject into dialogue contexts
    for ctx in dialogue_contexts:
        name_lower = (ctx.get("npc_name") or "").lower()
        if name_lower in mentions and mentions[name_lower]:
            ctx["shared_history"] = "; ".join(mentions[name_lower])

    return dialogue_contexts


async def _enrich_npc_dialogue(
    world_context: dict,
    state: TurnState,
    deps: PipelineDeps,
) -> dict:
    """Add npc_dialogue_contexts to world_context if NPCs are present."""
    npcs_raw: list[dict] = world_context.get("npcs_present", [])
    if not npcs_raw:
        return world_context

    # Resolve relationship service from deps if available
    rel_svc: RelationshipService | None = getattr(deps, "relationship_service", None)

    try:
        npcs = [NPC.model_validate(n) for n in npcs_raw]
        dialogue_contexts = await build_dialogue_contexts_for_location(
            npcs=npcs,
            session_id=state.session_id,
            source_id=_PLAYER_SOURCE_ID,
            relationship_service=rel_svc,
        )
        # AC-6.8: populate shared_history from recent turns
        dialogue_contexts = await _inject_shared_history(dialogue_contexts, state, deps)
        world_context["npc_dialogue_contexts"] = dialogue_contexts
    except Exception:
        log.warning(
            "npc_dialogue_context_failed",
            session_id=str(state.session_id),
            exc_info=True,
        )

    return world_context


async def _enrich_consequences(
    world_context: dict,
    state: TurnState,
    deps: PipelineDeps,
) -> dict:
    """Add active consequences and foreshadowing hints to context (S05 FR-3).

    Read-only: queries existing chain state without mutating it.
    Evaluation (state transitions) happens in the understand stage.
    """
    consequence_svc = getattr(deps, "consequence_service", None)
    if consequence_svc is None:
        return world_context

    try:
        chains = await consequence_svc.get_active_chains(state.session_id)
        if not chains:
            return world_context

        # Summaries for the generation prompt
        chain_summaries = [
            {
                "id": str(c.id),
                "trigger_description": c.root_trigger,
                "entries_count": len(c.entries),
                "is_resolved": c.is_resolved,
            }
            for c in chains
            if not c.is_resolved
        ]
        world_context["active_consequences"] = chain_summaries

        # Foreshadowing hints from hidden/foreshadowed entries
        hints = await consequence_svc.get_foreshadowing_hints(state.session_id)
        if hints:
            world_context["foreshadowing_hints"] = hints

    except Exception:
        log.warning(
            "consequence_enrichment_failed",
            session_id=str(state.session_id),
            exc_info=True,
        )

    return world_context
