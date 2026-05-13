"""Shared Pydantic model and prompt for intent classification (S08).

Every approach must produce output that validates against IntentOutput.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Intent(StrEnum):
    EXPLORE = "explore"
    INTERACT = "interact"
    USE_ITEM = "use_item"
    EXAMINE = "examine"
    SPEAK = "speak"
    REST = "rest"
    OTHER = "other"


class EmotionalTone(StrEnum):
    NEUTRAL = "neutral"
    ANXIOUS = "anxious"
    CURIOUS = "curious"
    FRUSTRATED = "frustrated"
    PLAYFUL = "playful"
    DISTRESSED = "distressed"


class IntentOutput(BaseModel):
    """Structured output for S08 §4.2 — Input Understanding."""

    intent: Intent = Field(description="Primary action category")
    confidence: float = Field(
        ge=0.0, le=1.0, description="How confident the model is in this classification"
    )
    entities: list[str] = Field(
        default_factory=list,
        description="Key entities mentioned (NPCs, items, locations, directions)",
    )
    emotional_tone: EmotionalTone = Field(
        description="Detected emotional register of the player's input"
    )
    summary: str = Field(
        default="", description="One-sentence summary of what the player wants to do"
    )


# Prompt from S08 §4.2 — kept minimal for apples-to-apples comparison.
# IMPORTANT: each approach wraps this differently (system message, JSON mode, etc.)
SYSTEM_PROMPT = """You are an intent classifier for a text adventure game.
Analyze the player's input and classify their intent.

YOU MUST RESPOND WITH ONLY A VALID JSON OBJECT. No markdown, no explanation, no other text.

The JSON must have exactly these fields:
- intent: one of "explore", "interact", "use_item", "examine", "speak", "rest", "other"
- confidence: float between 0.0 and 1.0
- entities: array of strings (key things mentioned: NPCs, items, locations, directions)
- emotional_tone: one of "neutral", "anxious", "curious", "frustrated", "playful", "distressed"
- summary: one-sentence summary of what the player wants to do

Example valid response:
{"intent": "explore", "confidence": 0.9, "entities": ["room"], "emotional_tone": "curious", "summary": "player wants to search the area"}"""


# 100 test inputs — mix of clear and ambiguous, drawn from S08 scenarios
TEST_INPUTS: list[str] = [
    "I want to search the room carefully",
    "look around",
    "examine the old key",
    "talk to the innkeeper",
    "use the healing potion",
    "open the wooden door",
    "I'll wait here and rest",
    "go north",
    "pick up the rusty sword",
    "read the inscription on the wall",
    "attack the goblin with my sword",
    "ask the wizard about the prophecy",
    "hide behind the barrel",
    "what's in my inventory?",
    "cast fireball at the troll",
    "sneak past the sleeping guard",
    "climb the rope ladder",
    "light the torch",
    "drink from the fountain",
    "give the amulet to the queen",
    "check under the bed",
    "push the stone block",
    "pull the lever",
    "look at the painting",
    "listen carefully",
    "smell the flowers",
    "taste the strange liquid",
    "follow the footprints",
    "swim across the river",
    "dig in the soft earth",
    "I want to go to the castle",
    "tell me about this place",
    "who are you?",
    "help!",
    "I'm not sure what to do",
    "yes",
    "no way",
    "maybe later",
    "I remember something...",
    "let me think about this",
    "run away!",
    "can I see that?",
    "I wonder what's behind that curtain",
    "give me a moment",
    "hello there",
    "goodbye",
    "what was that noise?",
    "I feel uneasy about this",
    "this looks dangerous",
    "I'm ready to fight",
    "let's make a deal",
    "show me what you've got",
    "I need to find the exit",
    "search the desk drawers",
    "kick down the door",
    "whisper to the thief",
    "throw a rock at the window",
    "light a candle",
    "draw my weapon",
    "sheathe my sword",
    "put on the cloak",
    "remove the ring",
    "eat the bread",
    "sleep in the bed",
    "I approach the throne cautiously",
    "scream loudly",
    "sing a song",
    "pray at the altar",
    "meditate by the stream",
    "count my gold coins",
    "sharpen my blade",
    "tie a rope to the post",
    "untie the prisoner",
    "lock the door behind me",
    "barricade the entrance",
    "signal the guards",
    "surrender",
    "negotiate",
    "threaten the merchant",
    "apologize to the dwarf",
    "compliment the elf",
    "insult the orc",
    "challenge the knight to a duel",
    "accept the quest",
    "refuse the offer",
    "demand answers",
    "beg for mercy",
    "laugh at the joke",
    "cry softly",
    "stare into the distance",
    "close my eyes and concentrate",
    "stretch my arms",
    "yawn",
    "scratch my head in confusion",
    "nod silently",
    "shake my head",
    "point at the strange symbol",
    "wave to the stranger",
    "bow before the king",
    "kneel at the grave",
    "spit on the ground",
]
