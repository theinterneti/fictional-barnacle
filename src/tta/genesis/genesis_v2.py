"""Genesis v2 — Real→Strange arc (S40).

Implements the 7-phase conversational genesis flow that transitions a player
from grounded realism (void) through escalating strangeness to the threshold
of full gameplay.

Phases (GenesisPhase):
  void → building_world → slip → building_character →
  first_light → becoming → threshold → COMPLETE

Invariants (FR-40.01):
- ≥2 player interactions per phase before advancing.
- State persisted to Postgres (``game_sessions.genesis_state``) between interactions.
- Harmful content redirects without corrupting state (FR-40.01d).
- Structlog events at every phase boundary (NFR-40.05).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.llm.client import LLMClient, Message, MessageRole
from tta.llm.roles import ModelRole

if TYPE_CHECKING:
    from tta.seeds.registry import SeedRegistry

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Seed composition helper (AC-41.06)
# ---------------------------------------------------------------------------


def apply_seed_composition(config: dict[str, Any], registry: SeedRegistry) -> None:
    """Overlay *config* with the composition data from a scenario seed.

    Reads ``config["genesis"]["seed_id"]``. If absent, returns silently.
    If the seed exists in *registry* its composition is used to overwrite
    ``config["composition"]`` entirely, with ``seed_id`` and ``seed_version`` injected.

    Args:
        config: Mutable genesis config dict (modified in-place).
        registry: The :class:`~tta.seeds.registry.SeedRegistry` to look up.
    """
    seed_id: str | None = config.get("genesis", {}).get("seed_id")
    if not seed_id:
        return
    manifest = registry.get(seed_id)
    if manifest is None:
        log.warning("apply_seed_composition_not_found", seed_id=seed_id)
        return
    comp_dict = manifest.composition.to_dict()
    comp_dict["seed_id"] = manifest.id
    comp_dict["seed_version"] = manifest.version
    config["composition"] = comp_dict
    log.info(
        "apply_seed_composition_applied",
        seed_id=manifest.id,
        seed_version=manifest.version,
    )


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------


class GenesisPhase(StrEnum):
    VOID = "void"
    BUILDING_WORLD = "building_world"
    SLIP = "slip"
    BUILDING_CHARACTER = "building_character"
    FIRST_LIGHT = "first_light"
    BECOMING = "becoming"
    THRESHOLD = "threshold"
    COMPLETE = "COMPLETE"


_PHASE_ORDER = [
    GenesisPhase.VOID,
    GenesisPhase.BUILDING_WORLD,
    GenesisPhase.SLIP,
    GenesisPhase.BUILDING_CHARACTER,
    GenesisPhase.FIRST_LIGHT,
    GenesisPhase.BECOMING,
    GenesisPhase.THRESHOLD,
    GenesisPhase.COMPLETE,
]

_MIN_INTERACTIONS_PER_PHASE = 2


# ---------------------------------------------------------------------------
# State dataclass
# ---------------------------------------------------------------------------


@dataclass
class GenesisState:
    """Persisted genesis state (stored in ``game_sessions.genesis_state`` JSONB)."""

    current_phase: GenesisPhase = GenesisPhase.VOID
    phase_interaction_count: int = 0
    interactions: list[dict[str, Any]] = field(default_factory=list)
    seed_phrase: str | None = None
    slip_event: str | None = None
    inferred_traits: list[str] = field(default_factory=list)
    confirmed_traits: list[str] = field(default_factory=list)
    narrator_form_hint: str | None = None
    character_name: str | None = None
    starting_location: str | None = None
    composition_committed: bool = False
    first_turn_seed: str | None = None
    completed: bool = False
    universe_id: UUID | None = None

    # ------------------------------------------------------------------
    # (De)serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_phase": self.current_phase,
            "phase_interaction_count": self.phase_interaction_count,
            "interactions": self.interactions,
            "seed_phrase": self.seed_phrase,
            "slip_event": self.slip_event,
            "inferred_traits": self.inferred_traits,
            "confirmed_traits": self.confirmed_traits,
            "narrator_form_hint": self.narrator_form_hint,
            "character_name": self.character_name,
            "starting_location": self.starting_location,
            "composition_committed": self.composition_committed,
            "first_turn_seed": self.first_turn_seed,
            "completed": self.completed,
            "universe_id": str(self.universe_id) if self.universe_id else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GenesisState:
        return cls(
            current_phase=GenesisPhase(d.get("current_phase", GenesisPhase.VOID)),
            phase_interaction_count=d.get("phase_interaction_count", 0),
            interactions=d.get("interactions", []),
            seed_phrase=d.get("seed_phrase"),
            slip_event=d.get("slip_event"),
            inferred_traits=d.get("inferred_traits", []),
            confirmed_traits=d.get("confirmed_traits", []),
            narrator_form_hint=d.get("narrator_form_hint"),
            character_name=d.get("character_name"),
            starting_location=d.get("starting_location"),
            composition_committed=d.get("composition_committed", False),
            first_turn_seed=d.get("first_turn_seed"),
            completed=d.get("completed", False),
            universe_id=UUID(d["universe_id"]) if d.get("universe_id") else None,
        )


# ---------------------------------------------------------------------------
# Harmful-content guard
# ---------------------------------------------------------------------------

_HARMFUL_RE = re.compile(
    r"\b(harm|hurt|kill|murder|suicid|self.harm|violence|abuse|"
    r"weapon|bomb|exploit|hack|inject)\b",
    re.IGNORECASE,
)


def _is_harmful(text: str) -> bool:
    return bool(_HARMFUL_RE.search(text))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class GenesisOrchestrator:
    """Drive a player through the 7-phase Real→Strange genesis arc.

    Usage::

        orch = GenesisOrchestrator(llm)
        response, state = await orch.start(session_id, universe_id, pg)
        response, state = await orch.advance(session_id, player_input, pg)
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(
        self,
        session_id: UUID,
        universe_id: UUID,
        pg: AsyncSession,
    ) -> tuple[str, GenesisState]:
        """Initialise genesis state and return the opening narrator message."""
        state = GenesisState()
        state.universe_id = universe_id
        await self._save_state(session_id, state, pg)

        log.info(
            "genesis_phase_boundary",
            universe_id=str(universe_id),
            session_id=str(session_id),
            from_phase=None,
            to_phase=state.current_phase,
        )

        response = await self._phase_prompt(state, player_input=None)
        state.interactions.append({"role": "narrator", "content": response})
        await self._save_state(session_id, state, pg)
        return response, state

    async def advance(
        self,
        session_id: UUID,
        player_input: str,
        pg: AsyncSession,
    ) -> tuple[str, GenesisState]:
        """Process one player interaction and return the narrator's response."""
        state = await self._load_state(session_id, pg)

        if state.completed:
            return "Genesis is already complete.", state

        # Guard harmful content — redirect without corrupting state (FR-40.01d)
        if _is_harmful(player_input):
            redirect = (
                "I hear something difficult in your words. "
                "Let's keep our journey on a gentler path. "
                "Tell me — what draws you to this world?"
            )
            state.interactions.append({"role": "narrator", "content": redirect})
            await self._save_state(session_id, state, pg)
            return redirect, state

        state.interactions.append({"role": "player", "content": player_input})
        state.phase_interaction_count += 1

        # Phase-specific processing
        response = await self._process_phase(state, player_input, session_id, pg)
        state.interactions.append({"role": "narrator", "content": response})

        # Advance phase if minimum interactions met
        if (
            state.phase_interaction_count >= _MIN_INTERACTIONS_PER_PHASE
            and state.current_phase != GenesisPhase.COMPLETE
        ):
            await self._maybe_advance_phase(state, session_id, pg)

        await self._save_state(session_id, state, pg)
        return response, state

    # ------------------------------------------------------------------
    # Phase processing
    # ------------------------------------------------------------------

    async def _process_phase(
        self,
        state: GenesisState,
        player_input: str,
        session_id: UUID,
        pg: AsyncSession,
    ) -> str:
        """Dispatch to per-phase handler."""
        phase = state.current_phase

        if phase == GenesisPhase.VOID:
            return await self._phase_void(state, player_input)

        if phase == GenesisPhase.BUILDING_WORLD:
            return await self._phase_building_world(state, player_input, pg)

        if phase == GenesisPhase.SLIP:
            return await self._phase_slip(state, player_input)

        if phase == GenesisPhase.BUILDING_CHARACTER:
            return await self._phase_building_character(state, player_input)

        if phase == GenesisPhase.FIRST_LIGHT:
            return await self._phase_first_light(state, player_input)

        if phase == GenesisPhase.BECOMING:
            return await self._phase_becoming(state, player_input)

        if phase == GenesisPhase.THRESHOLD:
            return await self._phase_threshold(state, player_input, session_id, pg)

        return "The journey continues…"

    async def _phase_void(self, state: GenesisState, player_input: str) -> str:
        """Phase 1: Anchor — grounded, ordinary world."""
        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a narrator establishing a grounded, realistic world. "
                    "Ask the player about the ordinary world they inhabit — "
                    "their surroundings, daily life, what matters to them. "
                    "Keep the tone warm but unremarkable. "
                    "Respond in 2-3 sentences."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=player_input,
            ),
        ]
        result = await self._llm.generate(ModelRole.GENERATION, messages)
        return result.content.strip()

    async def _phase_building_world(
        self, state: GenesisState, player_input: str, pg: AsyncSession
    ) -> str:
        """Phase 2: Notice — first shimmer; extract world composition via LLM."""
        # On second interaction, attempt composition extraction
        if (
            state.phase_interaction_count >= _MIN_INTERACTIONS_PER_PHASE
            and not state.composition_committed
        ):
            await self._extract_composition(state, pg)

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a narrator who notices something subtly unusual — "
                    "a shimmer at the edge of the ordinary. Ask the player what "
                    "small strangeness they have noticed lately. "
                    "Keep it suggestive, not alarming. 2-3 sentences."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=player_input,
            ),
        ]
        result = await self._llm.generate(ModelRole.GENERATION, messages)
        return result.content.strip()

    async def _phase_slip(self, state: GenesisState, player_input: str) -> str:
        """Phase 3: Question — doubt creeps in."""
        # Record the slip event from player's input
        if not state.slip_event:
            state.slip_event = player_input[:200]

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a narrator deepening a sense of doubt and unreality. "
                    "The player's world is slipping slightly. Reflect their "
                    "uncertainty back with empathy — help them question what they "
                    "thought was solid. 2-3 sentences, second-person."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=player_input,
            ),
        ]
        result = await self._llm.generate(ModelRole.GENERATION, messages)
        return result.content.strip()

    async def _phase_building_character(
        self, state: GenesisState, player_input: str
    ) -> str:
        """Phase 4: Cross — infer character traits from player's responses."""
        if (
            state.phase_interaction_count >= _MIN_INTERACTIONS_PER_PHASE
            and not state.inferred_traits
        ):
            await self._infer_traits(state, player_input)

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a narrator helping a character take shape. "
                    "Ask the player about who they are becoming in this strange "
                    "world — their instincts, their fears, what they would protect. "
                    "2-3 sentences."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=player_input,
            ),
        ]
        result = await self._llm.generate(ModelRole.GENERATION, messages)
        return result.content.strip()

    async def _phase_first_light(self, state: GenesisState, player_input: str) -> str:
        """Phase 5: Strange — player refines one trait; narrator takes partial form."""
        # Confirm traits from player's response
        if state.inferred_traits and not state.confirmed_traits:
            state.confirmed_traits = state.inferred_traits[:2]

        # Narrator takes partial form
        if not state.narrator_form_hint:
            state.narrator_form_hint = "a voice between memory and shadow"

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a narrator who has begun to take partial form — "
                    f"you are {state.narrator_form_hint}. "
                    "Ask the player to confirm one truth about themselves. "
                    "The strangeness is now undeniable. 2-3 sentences."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=player_input,
            ),
        ]
        result = await self._llm.generate(ModelRole.GENERATION, messages)
        return result.content.strip()

    async def _phase_becoming(self, state: GenesisState, player_input: str) -> str:
        """Phase 6: Integration — player names their character."""
        # Extract character name from player input
        if not state.character_name:
            # Simple heuristic: first capitalised word or use raw input trimmed
            words = player_input.strip().split()
            for word in words:
                clean = re.sub(r"[^a-zA-Z']", "", word)
                if clean and clean[0].isupper() and len(clean) > 1:
                    state.character_name = clean
                    break
            if not state.character_name:
                state.character_name = player_input.strip()[:40]

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a narrator witnessing a character claim their name. "
                    f"The player has named themselves '{state.character_name}'. "
                    "Acknowledge this naming with weight — it is an act of becoming. "
                    "Tell them what this name will mean in the strange world ahead. "
                    "2-3 sentences."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=player_input,
            ),
        ]
        result = await self._llm.generate(ModelRole.GENERATION, messages)
        return result.content.strip()

    async def _phase_threshold(
        self,
        state: GenesisState,
        player_input: str,
        session_id: UUID,
        pg: AsyncSession,
    ) -> str:
        """Phase 7: Return or Stay — construct first-turn seed; store MemoryRecord."""
        # Build first-turn seed summary
        if not state.first_turn_seed:
            parts = []
            if state.character_name:
                parts.append(f"Character: {state.character_name}")
            if state.confirmed_traits:
                parts.append("Traits: " + ", ".join(state.confirmed_traits))
            if state.narrator_form_hint:
                parts.append(f"Narrator form: {state.narrator_form_hint}")
            if state.slip_event:
                parts.append(f"The slip: {state.slip_event}")
            state.first_turn_seed = (
                " | ".join(parts) if parts else "A traveller steps through."
            )

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a narrator standing at the threshold between worlds. "
                    "Deliver the final, pivotal moment of genesis — the step that "
                    "cannot be taken back. Make it feel earned and mythic. "
                    "3-4 sentences. Close with a single question that will open "
                    "the first true turn."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=player_input,
            ),
        ]
        result = await self._llm.generate(ModelRole.GENERATION, messages)
        response = result.content.strip()

        return response

    # ------------------------------------------------------------------
    # LLM-assisted helpers
    # ------------------------------------------------------------------

    async def _extract_composition(self, state: GenesisState, pg: AsyncSession) -> None:
        """Use LLM to extract ThemeSpec/TropeSpec signals from the conversation."""
        history_text = "\n".join(
            f"{i['role'].upper()}: {i['content']}" for i in state.interactions[-8:]
        )
        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a JSON extractor. Analyse the following genesis "
                    "conversation and extract world composition signals as JSON "
                    "with keys: "
                    '"primary_genre" (string), '
                    '"themes" (list of {name, weight} objects, max 5), '
                    '"tropes" (list of {name, weight} objects, max 10). '
                    "Use snake_case names. Respond with JSON only."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=history_text,
            ),
        ]
        try:
            raw = await self._llm.generate(ModelRole.EXTRACTION, messages)
            blob = json.loads(raw.content)
            state.composition_committed = True
            # Store in interactions for downstream commit to universes.config
            state.interactions.append(
                {"role": "system", "content": f"composition_extract:{json.dumps(blob)}"}
            )
        except (json.JSONDecodeError, Exception):
            # Non-fatal — composition extraction is best-effort
            state.composition_committed = False

    async def _infer_traits(self, state: GenesisState, player_input: str) -> None:
        """Infer 2-3 character traits from conversation history."""
        history_text = "\n".join(
            f"{i['role'].upper()}: {i['content']}" for i in state.interactions[-6:]
        )
        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a character analyst. Based on the following conversation, "
                    "infer 2-3 personality traits for this character. "
                    "Respond with a JSON array of strings, "
                    'e.g. ["curious", "cautious"]. '
                    "Use single adjective words only."
                ),
            ),
            Message(
                role=MessageRole.USER,
                content=history_text + f"\nLATEST: {player_input}",
            ),
        ]
        try:
            raw = await self._llm.generate(ModelRole.EXTRACTION, messages)
            traits = json.loads(raw.content)
            if isinstance(traits, list):
                state.inferred_traits = [str(t) for t in traits[:3]]
        except (json.JSONDecodeError, Exception):
            # Non-fatal — inferred traits default to empty
            pass

    async def _phase_prompt(self, state: GenesisState, player_input: str | None) -> str:
        """Generate the opening prompt for the current phase."""
        phase_intros = {
            GenesisPhase.VOID: (
                "You find yourself in a moment of quiet. "
                "Tell me — what does your ordinary world look like right now?"
            ),
            GenesisPhase.BUILDING_WORLD: (
                "Something about today feels slightly… off. "
                "Have you noticed anything unusual at the edges of things?"
            ),
            GenesisPhase.SLIP: (
                "The ground beneath certainty has begun to shift. "
                "What do you find yourself questioning?"
            ),
            GenesisPhase.BUILDING_CHARACTER: (
                "In a world that has begun to change, who are you becoming? "
                "What do your instincts tell you?"
            ),
            GenesisPhase.FIRST_LIGHT: (
                "I can almost see you now. Tell me one true thing about yourself."
            ),
            GenesisPhase.BECOMING: (
                "You stand at the edge of becoming. "
                "What name do you carry into this strange world?"
            ),
            GenesisPhase.THRESHOLD: (
                "The door is before you. "
                "What is the last thing you hold onto before you step through?"
            ),
        }
        return phase_intros.get(
            state.current_phase, "The journey continues — what do you do next?"
        )

    # ------------------------------------------------------------------
    # Phase advancement
    # ------------------------------------------------------------------

    async def _maybe_advance_phase(
        self, state: GenesisState, session_id: UUID, pg: AsyncSession
    ) -> None:
        """Advance to the next phase and reset interaction counter."""
        current_idx = _PHASE_ORDER.index(state.current_phase)
        if current_idx + 1 >= len(_PHASE_ORDER):
            return

        old_phase = state.current_phase
        state.current_phase = _PHASE_ORDER[current_idx + 1]
        state.phase_interaction_count = 0

        if state.current_phase == GenesisPhase.COMPLETE:
            state.completed = True
        log.info(
            "genesis_phase_boundary",
            session_id=str(session_id),
            from_phase=old_phase,
            to_phase=state.current_phase,
            universe_id=str(state.universe_id) if state.universe_id else None,
        )

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    async def _save_state(
        self, session_id: UUID, state: GenesisState, pg: AsyncSession
    ) -> None:
        await pg.execute(
            sa.text(
                "UPDATE game_sessions SET genesis_state = CAST(:gs AS jsonb)"
                " WHERE id = :sid"
            ),
            {"gs": json.dumps(state.to_dict()), "sid": session_id},
        )
        await pg.commit()

    async def _load_state(self, session_id: UUID, pg: AsyncSession) -> GenesisState:
        result = await pg.execute(
            sa.text("SELECT genesis_state FROM game_sessions WHERE id = :sid"),
            {"sid": session_id},
        )
        row = result.first()
        if row is None or row.genesis_state is None:
            return GenesisState()
        raw = row.genesis_state
        if isinstance(raw, str):
            raw = json.loads(raw)
        return GenesisState.from_dict(raw)
