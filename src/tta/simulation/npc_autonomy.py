"""NPC Autonomy Processor — S35 implementation.

AutonomyProcessor: typing.Protocol for the processor contract.
DefaultAutonomyProcessor: salience-filtered, rule-based + optional LLM batch.
MemoryAutonomyProcessor: static test fixture that returns a preset WorldDelta.

Salience filter (AC-35.01–35.05):
    KEY + schedule        → process (rule-based or LLM batch)
    KEY + no schedule     → no-op
    SUPPORTING + schedule → process if inside salience window
    SUPPORTING otherwise  → skip
    BACKGROUND            → never process
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from tta.simulation.types import (
    DeferredNPC,
    NPCStateChange,
    RoutineTrigger,
    WorldDelta,
    WorldEvent,
    WorldTime,
)

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# Triggers that are logged and return "not_matched" in v2.0 (AC-35.10)
_UNMATCHED_TRIGGERS: frozenset[RoutineTrigger] = frozenset(
    {"world_event", "player_visited"}
)


def _resolve_npc_field(npc: Any, field: str, default: Any = None) -> Any:
    """Extract a field from either a dict or an NPC model object."""
    if isinstance(npc, dict):
        return npc.get(field, default)
    return getattr(npc, field, default)


def _in_salience_window(
    npc: Any, world_time: WorldTime, world_context: dict | None = None
) -> bool:
    """Return True when a SUPPORTING NPC should be processed this tick.

    AC-35.03/35.04: A SUPPORTING NPC is in the salience window when its
    ``location_id`` appears in the set of locations visited in the last 5
    turns (extracted from ``world_context["recent_locations"]``).  If that
    context is absent we fall back to the time-of-day schedule heuristic so
    that unit tests that don't supply world_context keep working.
    """
    schedule: str | None = _resolve_npc_field(npc, "schedule")
    if not schedule:
        return False

    # Visitor-based check: use recent_locations from world_context
    if world_context is not None:
        recent: list[str] = world_context.get("recent_locations", [])
        if recent:
            npc_location: str | None = _resolve_npc_field(npc, "location_id")
            if npc_location is None:
                return False
            return npc_location in recent

    # Fallback: schedule string contains the current time-of-day label
    schedule_lower = schedule.lower()
    if schedule_lower in ("always", "*"):
        return True
    return world_time.time_of_day_label in schedule_lower


class AutonomyProcessor(Protocol):
    """Contract for NPC autonomy processors (S35)."""

    def process(
        self,
        universe_id: str,
        world_time: WorldTime,
        npcs: list[Any],
    ) -> WorldDelta:
        """Evaluate NPC routines for one tick and return a WorldDelta."""
        ...


class DefaultAutonomyProcessor:
    """Rule-based NPC autonomy with optional LLM-assisted KEY-tier batch.

    Parameters
    ----------
    budget_ms:
        Total wall-clock budget for SUPPORTING NPC processing.
        KEY NPCs are NEVER deferred regardless of budget (AC-35.06).
    max_llm_npcs:
        Maximum KEY-tier NPCs passed to the LLM batch per turn (AC-35.08).
    llm:
        Optional LLM client.  When None, llm_assisted NPCs fall back to
        rule-based processing (AC-35.09).
    """

    def __init__(
        self,
        budget_ms: int = 50,
        max_llm_npcs: int = 5,
        llm: Any = None,
    ) -> None:
        self.budget_ms = budget_ms
        self.max_llm_npcs = max_llm_npcs
        self.llm = llm
        # AC-35.06: tracks (universe_id, npc_id, step_idx, trigger, condition_label)
        # tuples for non-repeating steps that have already fired. Stored on the
        # processor (not the NPC payload) because npcs_present dicts are
        # rebuilt each turn from NPC.model_dump() in tta.world.state.
        self._fired_non_repeating_steps: set[
            tuple[str | None, str, int, str, str | None]
        ] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        universe_id: str,
        world_time: WorldTime,
        npcs: list[Any],
    ) -> WorldDelta:
        """Run salience filter → rule-based → LLM batch for one tick."""
        start = time.monotonic()

        changes: list[NPCStateChange] = []
        events: list[WorldEvent] = []
        deferred_npcs: list[DeferredNPC] = []
        deferred_changes: list[NPCStateChange] = []
        key_llm_batch: list[Any] = []

        for npc in npcs:
            npc_id: str | None = _resolve_npc_field(npc, "id")
            if npc_id is None:
                continue

            tier: str = str(
                _resolve_npc_field(npc, "tier", "background") or "background"
            )
            # Normalise enum values (e.g. NPCTier.BACKGROUND.value)
            if "." in tier:
                tier = tier.split(".")[-1].lower()
            if hasattr(tier, "value"):
                tier = tier.value  # type: ignore[union-attr]
            tier = str(tier).lower()

            schedule: str | None = _resolve_npc_field(npc, "schedule")
            autonomy_mode: str = str(
                _resolve_npc_field(npc, "autonomy_mode", "rule_based") or "rule_based"
            )

            if tier == "background":
                # AC-35.05 — BACKGROUND NPCs are never processed
                continue

            if tier == "key":
                if not schedule:
                    # AC-35.02 — KEY + no schedule → no-op
                    continue
                # KEY NPCs are NEVER deferred (AC-35.06)
                if autonomy_mode == "llm_assisted" and self.llm is not None:
                    key_llm_batch.append(npc)
                else:
                    npc_changes, npc_events = self._process_rule_based(
                        npc_id, npc, world_time, universe_id
                    )
                    changes.extend(npc_changes)
                    events.extend(npc_events)
                continue

            # tier == "supporting"
            if not schedule:
                # AC-35.04 — SUPPORTING + no schedule → skip
                continue
            if not _in_salience_window(npc, world_time):
                # AC-35.03 — outside window → skip
                continue

            # Budget guard (SUPPORTING only)
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms > self.budget_ms:
                deferred_npcs.append(
                    DeferredNPC(npc_id=npc_id, reason="budget_exceeded")
                )
                continue

            npc_changes, npc_events = self._process_rule_based(
                npc_id, npc, world_time, universe_id
            )
            changes.extend(npc_changes)
            events.extend(npc_events)

        # LLM batch for KEY-tier (AC-35.08 — capped at max_llm_npcs)
        if key_llm_batch:
            llm_changes, llm_events = self._process_llm_batch(
                universe_id, world_time, key_llm_batch[: self.max_llm_npcs]
            )
            changes.extend(llm_changes)
            events.extend(llm_events)

        return WorldDelta(
            from_tick=world_time.total_ticks,
            to_tick=world_time.total_ticks,
            world_time=world_time,
            was_capped=False,
            tick=world_time.total_ticks,
            changes=changes,
            events=events,
            deferred_npcs=deferred_npcs,
            deferred_changes=deferred_changes,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process_rule_based(
        self,
        npc_id: str,
        npc: Any,
        world_time: WorldTime,
        universe_id: str,
    ) -> tuple[list[NPCStateChange], list[WorldEvent]]:
        """Apply the NPC's routine RoutineSteps, then fall back to tod schedule."""
        from tta.simulation.types import (
            DispositionShiftAction,
            MoveAction,
            NarrativeEventAction,
            RoutineStep,
            StateChangeAction,
        )

        schedule: str | None = _resolve_npc_field(npc, "schedule")
        current_state: str = str(_resolve_npc_field(npc, "state", "idle") or "idle")
        routine: list[Any] = _resolve_npc_field(npc, "routine") or []
        tod = world_time.time_of_day_label

        changes: list[NPCStateChange] = []
        events: list[WorldEvent] = []

        # --- Phase 1: evaluate RoutineStep triggers (AC-35.03) ---
        for step_idx, step in enumerate(routine):
            if not isinstance(step, RoutineStep):
                continue

            trigger = step.trigger
            matched = False

            if trigger == "time_of_day" and step.condition is not None:
                matched = step.condition.label.lower() == tod.lower()
            elif trigger == "tick_elapsed" and step.condition is not None:
                try:
                    interval = int(step.condition.label)
                    matched = interval > 0 and (world_time.total_ticks % interval == 0)
                except ValueError:
                    matched = False
            elif trigger in ("world_event", "player_visited"):
                # Not evaluated rule-based; logged as not_matched (AC-35.10)
                matched = False

            if not matched:
                continue

            # AC-35.06: skip non-repeating steps that have already fired.
            # Tracked on the processor, not the NPC payload, because
            # npcs_present dicts are rebuilt each turn from NPC.model_dump()
            # (see tta.world.state.get_full_context). Keying by npc_id +
            # step index + trigger + condition survives the dict rebuild and
            # keeps the NPC payload JSON-serializable for prompt assembly.
            if not step.repeating:
                step_signature = (
                    universe_id,
                    npc_id,
                    step_idx,
                    trigger,
                    step.condition.label if step.condition is not None else None,
                )
                if step_signature in self._fired_non_repeating_steps:
                    continue
                self._fired_non_repeating_steps.add(step_signature)

            action = step.action
            if isinstance(action, StateChangeAction):
                if action.new_state != current_state:
                    changes.append(
                        NPCStateChange(
                            npc_id=npc_id,
                            action_type="state_change",
                            before={"state": current_state},
                            after={"state": action.new_state},
                        )
                    )
                    current_state = action.new_state
            elif isinstance(action, MoveAction):
                changes.append(
                    NPCStateChange(
                        npc_id=npc_id,
                        action_type="move",
                        before={},
                        after={"location_id": action.target_location_id},
                    )
                )
            elif isinstance(action, DispositionShiftAction):
                changes.append(
                    NPCStateChange(
                        npc_id=npc_id,
                        action_type="disposition_shift",
                        before={},
                        after={"target_npc": action.npc_id, "delta": action.delta},
                    )
                )
            elif isinstance(action, NarrativeEventAction):
                events.append(
                    WorldEvent(
                        event_id=f"{npc_id}:{world_time.total_ticks}:narrative",
                        universe_id=universe_id,
                        event_type="narrative",
                        description=action.description,
                        severity=action.severity,
                        triggered_at_tick=world_time.total_ticks,
                        created_at=datetime.utcnow(),
                        source_npc_id=npc_id,
                        location_id=None,
                    )
                )

        # --- Phase 2: schedule-based tod fallback (only if no routine steps) ---
        if not routine and schedule:
            tod_to_state: dict[str, str] = {
                "morning": "active",
                "afternoon": "active",
                "evening": "busy",
                "night": "sleeping",
                "midnight": "sleeping",
            }
            new_state = tod_to_state.get(tod.lower(), current_state)
            if new_state != current_state:
                changes.append(
                    NPCStateChange(
                        npc_id=npc_id,
                        action_type="state_change",
                        before={"state": current_state},
                        after={"state": new_state},
                    )
                )

        return changes, events

    def _process_llm_batch(
        self,
        universe_id: str,
        world_time: WorldTime,
        npcs: list[Any],
    ) -> tuple[list[NPCStateChange], list[WorldEvent]]:
        """Issue a single batched LLM call for KEY-tier NPCs.

        Falls back to rule-based processing if the LLM call fails (AC-35.09).
        """
        try:
            # MVP: fall through to rule-based since async LLM integration
            # requires the turn pipeline's LLM client, not a sync constructor arg.
            # Full async LLM batch is wired in Wave F.
            changes: list[NPCStateChange] = []
            events: list[WorldEvent] = []
            for npc in npcs:
                npc_id: str | None = _resolve_npc_field(npc, "id")
                if npc_id is not None:
                    c, e = self._process_rule_based(
                        npc_id, npc, world_time, universe_id
                    )
                    changes.extend(c)
                    events.extend(e)
            return changes, events
        except Exception:
            log.exception("LLM batch failed; falling back to rule-based (AC-35.09)")
            changes = []
            events = []
            for npc in npcs:
                npc_id = _resolve_npc_field(npc, "id")
                if npc_id is not None:
                    c, e = self._process_rule_based(
                        npc_id, npc, world_time, universe_id
                    )
                    changes.extend(c)
                    events.extend(e)
            return changes, events


class MemoryAutonomyProcessor:
    """Test fixture that returns a pre-set WorldDelta without any computation."""

    def __init__(self, preset: WorldDelta | None = None) -> None:
        self._preset = preset

    def process(
        self,
        universe_id: str,
        world_time: WorldTime,
        npcs: list[Any],
    ) -> WorldDelta:
        if self._preset is not None:
            return self._preset
        return WorldDelta(
            from_tick=world_time.total_ticks,
            to_tick=world_time.total_ticks,
            world_time=world_time,
            was_capped=False,
        )
