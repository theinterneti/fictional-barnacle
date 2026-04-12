"""Simulation test fixtures — role-aware LLM mock + full pipeline deps."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tta.choices.consequence_service import InMemoryConsequenceService
from tta.llm.client import GenerationParams, LLMResponse, Message
from tta.llm.roles import ModelRole
from tta.models.turn import TokenCount
from tta.pipeline.types import PipelineDeps
from tta.prompts.registry import RenderedPrompt
from tta.safety.hooks import PassthroughHook
from tta.world.memory_service import InMemoryWorldService
from tta.world.template_registry import TemplateRegistry

# ---------------------------------------------------------------------------
# SimulationLLMClient — role-aware mock that produces meaningful responses
# ---------------------------------------------------------------------------

# Intent patterns mirrored from understand.py for classification routing
_INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("meta", re.compile(r"\b(help|save|quit|exit|menu|inventory|status)\b", re.I)),
    ("move", re.compile(r"\b(go|walk|move|run|head|travel|enter|leave)\b", re.I)),
    ("examine", re.compile(r"\b(look|examine|inspect|search|check|observe)\b", re.I)),
    ("talk", re.compile(r"\b(talk|say|ask|tell|speak|greet|whisper)\b", re.I)),
    (
        "use",
        re.compile(r"\b(use|take|grab|pick|drop|put|open|close|push|pull)\b", re.I),
    ),
]

# Narrative pool indexed by intent for variety
_NARRATIVE_POOL: dict[str, list[str]] = {
    "move": [
        "You make your way along the winding path, leaves crunching beneath your "
        "feet. The air grows cooler as you approach a new area. Ahead, the landscape "
        "shifts — stone walls give way to open sky.\n\nYou pause, taking in the "
        "unfamiliar surroundings. Somewhere nearby, you hear the faint sound of "
        "running water.",
        "Your footsteps echo softly as you cross the threshold. The atmosphere "
        "changes immediately — warmer, perhaps, or simply different. You sense "
        "a story hidden in every corner of this place.\n\nThe path behind you "
        "fades from view as you commit to this new direction.",
        "You stride forward with purpose. The terrain underfoot shifts from "
        "packed earth to smooth flagstones. A breeze carries unfamiliar scents — "
        "wood smoke and something floral.\n\nAhead, the route branches. Each "
        "fork promises its own adventure.",
        "The corridor opens into a sunlit clearing you hadn't expected. Moss-covered "
        "stones form a rough boundary, and wildflowers push through the cracks. "
        "You feel a strange calm settle over you.\n\nA narrow trail leads onward, "
        "disappearing into the treeline.",
        "You descend a spiralling staircase, each step carrying you deeper. The walls "
        "are cool and damp against your fingertips, and torchlight flickers at "
        "intervals.\n\nAt the bottom, an arched doorway stands open, revealing "
        "a chamber carved from living rock.",
        "You follow the sound of distant music. The path winds through tall hedges "
        "that block the sky, creating a green tunnel of rustling leaves.\n\nWhen "
        "you emerge, the music is gone, but the scene before you is breathtaking.",
    ],
    "examine": [
        "You study your surroundings carefully. Details emerge that you hadn't "
        "noticed before — the subtle wear patterns on the floor, the way shadows "
        "pool in certain corners. Everything tells a story.\n\nYour attention is "
        "drawn to a peculiar marking etched into the wall nearby.",
        "You take a moment to observe. The light falls differently here, revealing "
        "textures and colours that demand closer inspection. A faded inscription "
        "catches your eye.\n\nBeneath a layer of dust, something glints — metal, "
        "perhaps, or glass.",
        "You crouch low and peer into the alcove. Shelves line the interior, each "
        "holding objects both familiar and strange. Cobwebs bridge the gaps between "
        "them.\n\nOne item sits apart from the rest, placed deliberately, as "
        "though someone meant for it to be found.",
        "Running your fingers along the surface, you detect a seam almost invisible "
        "to the eye. The craftsmanship is remarkable — whoever made this wanted it "
        "to last.\n\nA tiny mechanism clicks under your touch, and a panel slides "
        "aside with a whisper of air.",
        "You kneel beside the object and study it from every angle. The engravings "
        "tell a story — battles, treaties, betrayals. Whoever carved this knew "
        "their history.\n\nOne symbol recurs more than the rest, a serpent "
        "swallowing its own tail.",
        "Your careful examination reveals layers upon layers. Beneath the obvious "
        "surface lies a hidden compartment, a false bottom, a secret waiting to "
        "be uncovered.\n\nPatience rewards you with a discovery that changes "
        "everything you thought you knew.",
    ],
    "talk": [
        "The figure regards you with measured interest. 'Well met, traveller,' "
        "they say, their voice carrying the weight of many conversations. 'I "
        "don't often see new faces around here.'\n\nThey lean forward slightly, "
        "as though deciding how much to share. 'Ask your questions — I may "
        "have answers.'",
        "Your words hang in the air between you. The other person considers "
        "them carefully before responding. 'That's a bold thing to say,' they "
        "murmur. 'Not many would admit it.'\n\nSomething in their expression "
        "shifts — warmer, more open. 'Let me tell you what I know.'",
        "The conversation unfolds naturally, each exchange revealing a little "
        "more. Your companion speaks with a rhythm that suggests deep familiarity "
        "with these parts.\n\n'There's more going on here than meets the eye,' "
        "they confide. 'But that's a story for another time — unless you're "
        "willing to listen now.'",
        "A wry smile crosses their face. 'You're persistent, I'll give you that.' "
        "They gesture for you to sit. 'Very well. What I'm about to tell you "
        "doesn't leave this room.'\n\nTheir voice drops to a whisper, and "
        "the tale that follows is stranger than you imagined.",
        "They study you for a long moment before speaking. 'I've been waiting "
        "for someone to ask the right questions.' Their eyes brighten with "
        "something like hope.\n\n'Come, walk with me. Some things are easier "
        "to explain when you can see them for yourself.'",
        "The exchange starts cautiously, but warmth creeps in as trust builds. "
        "'I haven't told anyone this,' they admit, glancing around. 'But you "
        "seem different from the others.'\n\nWhat follows is a revelation "
        "that reframes everything you've encountered so far.",
    ],
    "use": [
        "You reach for the object, feeling its weight and texture in your hands. "
        "It responds to your touch in ways you didn't expect — a subtle vibration, "
        "a shift in temperature.\n\nSomething has changed. The air feels "
        "different, charged with possibility.",
        "Your hands move with practiced confidence. The mechanism resists at first "
        "then yields with a satisfying click. A hidden compartment slides open, "
        "revealing what lies within.\n\nYou pocket your discovery, already "
        "considering its implications.",
        "You apply careful pressure, and the world shifts around you. What was "
        "once sealed is now open. What was hidden is now revealed.\n\nThe "
        "consequences of your action ripple outward like stones dropped in water.",
        "The item hums faintly in your grasp, resonating with an energy you can "
        "feel but not see. When you direct it forward, the barrier shimmers and "
        "dissolves.\n\nA draft of ancient air rushes past you, carrying the "
        "scent of old parchment and forgotten promises.",
        "You fit the pieces together with a satisfying snap. The assembled whole "
        "is greater than its parts — light pulses along its edges, and the room "
        "responds.\n\nSomewhere in the distance, a door unlocks.",
        "With deliberate care, you activate the mechanism. Gears turn, chains "
        "rattle, and the ground trembles briefly. When the dust settles, a new "
        "passage stands where solid wall once was.\n\nYour resourcefulness has "
        "opened a way forward.",
    ],
    "other": [
        "The world responds to your unexpected action with a moment of stillness. "
        "Then, slowly, things begin to shift. Not everything here follows "
        "predictable rules.\n\nYou sense that your choice has set something "
        "in motion — something that cannot easily be undone.",
        "Your unconventional approach yields surprising results. The environment "
        "seems to acknowledge your creativity, responding in kind.\n\nA new "
        "possibility opens up — one you couldn't have predicted when you started.",
        "You do something nobody expected, least of all yourself. The moment "
        "stretches, reality bending around your audacity.\n\nWhen things settle, "
        "the landscape has subtly rearranged itself. Your boldness has been noted.",
        "The world tilts its head at your approach, metaphorically speaking. "
        "Nothing quite like this has happened before, and the rules seem uncertain "
        "how to respond.\n\nIn the end, the unexpected proves to be exactly "
        "what was needed.",
    ],
    "meta": [
        "You take a moment to reflect on your journey so far. The path has been "
        "winding, but every step has led you closer to understanding.\n\nThe "
        "world waits patiently for your next decision.",
        "A quiet pause settles over the scene. In the stillness, you gather your "
        "thoughts and take stock of where you are and what you've learned.\n\n"
        "The adventure continues whenever you're ready.",
    ],
}

# Suggested actions pool by intent
_SUGGESTIONS: dict[str, list[list[str]]] = {
    "move": [
        [
            "Look around the new area",
            "Talk to anyone nearby",
            "Search for hidden paths",
        ],
        ["Explore further ahead", "Return the way you came", "Rest and observe"],
        ["Follow the sound of water", "Climb the nearby hill", "Enter the building"],
    ],
    "examine": [
        ["Pick up the glinting object", "Read the inscription", "Search the shelves"],
        ["Touch the marking on the wall", "Look behind the furniture", "Call out"],
        ["Take notes on what you see", "Examine the floor closely", "Open the box"],
    ],
    "talk": [
        [
            "Ask about the local history",
            "Inquire about recent events",
            "Share your story",
        ],
        ["Press for more details", "Change the subject", "Offer to help"],
        ["Ask about the mysterious stranger", "Request a favour", "Say farewell"],
    ],
    "use": [
        ["Examine what you found", "Try using it on the door", "Show it to someone"],
        ["Combine it with another item", "Place it on the pedestal", "Keep it hidden"],
        ["Test its properties", "Offer it as a gift", "Leave it behind"],
    ],
    "other": [
        ["Look around carefully", "Talk to someone nearby", "Try something else"],
        ["Retrace your steps", "Wait and observe", "Search for clues"],
    ],
    "meta": [
        ["Continue exploring", "Talk to the nearest person", "Check your belongings"],
    ],
}


def _classify_input(text: str) -> str:
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(text):
            return intent
    return "other"


class SimulationLLMClient:
    """Role-aware mock LLM that returns contextually appropriate responses.

    - CLASSIFICATION → intent word matching understand.py patterns
    - GENERATION → varied narrative prose keyed by intent
    - EXTRACTION → valid JSON with world changes and suggested actions
    - SUMMARIZATION → brief summary text
    """

    def __init__(self) -> None:
        self.call_history: list[dict] = []
        self._gen_counters: dict[str, int] = {}
        self._suggestion_counters: dict[str, int] = {}

    def _pick_narrative(self, intent: str) -> str:
        pool = _NARRATIVE_POOL.get(intent, _NARRATIVE_POOL["other"])
        idx = self._gen_counters.get(intent, 0) % len(pool)
        self._gen_counters[intent] = idx + 1
        return pool[idx]

    def _pick_suggestions(self, intent: str) -> list[str]:
        pool = _SUGGESTIONS.get(intent, _SUGGESTIONS["other"])
        idx = self._suggestion_counters.get(intent, 0) % len(pool)
        self._suggestion_counters[intent] = idx + 1
        return pool[idx]

    def _extract_player_input(self, messages: list[Message]) -> str:
        for m in reversed(messages):
            if m.role.value == "user":
                return m.content
        return ""

    def _respond(self, role: ModelRole, messages: list[Message]) -> str:
        user_content = self._extract_player_input(messages)

        if role == ModelRole.CLASSIFICATION:
            return _classify_input(user_content)

        if role == ModelRole.GENERATION:
            # Infer intent from prompt context
            intent = "other"
            if "Intent:" in user_content:
                for line in user_content.split("\n"):
                    if line.startswith("Intent:"):
                        intent = line.split(":", 1)[1].strip()
                        break
            return self._pick_narrative(intent)

        if role == ModelRole.EXTRACTION:
            # Determine intent from "Player action:" in the prompt
            intent = "other"
            if "Player action:" in user_content:
                action_line = ""
                for line in user_content.split("\n"):
                    if line.startswith("Player action:"):
                        action_line = line.split(":", 1)[1].strip()
                        break
                intent = _classify_input(action_line)

            suggestions = self._pick_suggestions(intent)
            return json.dumps(
                {
                    "world_changes": [],
                    "suggested_actions": suggestions,
                }
            )

        if role == ModelRole.SUMMARIZATION:
            return (
                "The adventurer has been exploring a mysterious locale, encountering "
                "various characters and uncovering secrets along the way."
            )

        return "Mock response for unknown role."

    def _build_response(self, role: ModelRole, messages: list[Message]) -> LLMResponse:
        content = self._respond(role, messages)
        prompt_tokens = sum(len(m.content.split()) for m in messages)
        completion_tokens = len(content.split())
        return LLMResponse(
            content=content,
            model_used="simulation-mock",
            token_count=TokenCount(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            latency_ms=1.0,
            tier_used="primary",
        )

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        self.call_history.append(
            {"method": "generate", "role": role, "messages": messages}
        )
        return self._build_response(role, messages)

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        self.call_history.append(
            {"method": "stream", "role": role, "messages": messages}
        )
        return self._build_response(role, messages)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sim_llm() -> SimulationLLMClient:
    return SimulationLLMClient()


@pytest.fixture
def world_service() -> InMemoryWorldService:
    return InMemoryWorldService()


@pytest.fixture
def template_registry() -> TemplateRegistry:
    templates_dir = (
        Path(__file__).resolve().parents[2] / "src" / "tta" / "world" / "templates"
    )
    return TemplateRegistry(templates_dir)


@pytest.fixture
def session_id() -> UUID:
    return uuid4()


@pytest.fixture
def mock_session_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_turn_repo() -> AsyncMock:
    return AsyncMock()


def _make_sim_registry() -> MagicMock:
    """Mock prompt registry for simulation tests."""
    tpls = {
        "narrative.generate": "You are a narrative engine.",
        "classification.intent": "Classify the player intent.",
        "extraction.world-changes": "Extract world changes as JSON.",
    }
    registry = MagicMock()
    registry.has.side_effect = lambda tid: tid in tpls
    registry.render.side_effect = lambda tid, _vars: RenderedPrompt(
        text=tpls[tid],
        template_id=tid,
        template_version="v1.1.0",
    )
    return registry


@pytest.fixture
def pipeline_deps(
    sim_llm: SimulationLLMClient,
    world_service: InMemoryWorldService,
    mock_session_repo: AsyncMock,
    mock_turn_repo: AsyncMock,
) -> PipelineDeps:
    return PipelineDeps(
        llm=sim_llm,
        world=world_service,
        session_repo=mock_session_repo,
        turn_repo=mock_turn_repo,
        safety_pre_input=PassthroughHook(),
        safety_pre_gen=PassthroughHook(),
        safety_post_gen=PassthroughHook(),
        consequence_service=InMemoryConsequenceService(),
        prompt_registry=_make_sim_registry(),
    )
