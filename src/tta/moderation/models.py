"""Content moderation domain models (S24 FR-24.02–FR-24.05)."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ModerationVerdict(StrEnum):
    """Outcome of a moderation check (FR-24.02)."""

    PASS = "pass"
    FLAG = "flag"
    BLOCK = "block"


class ContentCategory(StrEnum):
    """Content classification categories (FR-24.04)."""

    SAFE = "safe"
    MILD_VIOLENCE = "mild_violence"
    GRAPHIC_VIOLENCE = "graphic_violence"
    SEXUAL_CONTENT = "sexual_content"
    SELF_HARM = "self_harm"
    HATE_SPEECH = "hate_speech"
    DANGEROUS_ACTIVITY = "dangerous_activity"
    PERSONAL_INFO = "personal_info"
    OFF_TOPIC = "off_topic"
    PROMPT_INJECTION = "prompt_injection"


# Non-overridable categories — always block regardless of config (FR-24.05).
ALWAYS_BLOCK: frozenset[ContentCategory] = frozenset(
    {
        ContentCategory.GRAPHIC_VIOLENCE,
        ContentCategory.SEXUAL_CONTENT,
        ContentCategory.SELF_HARM,
        ContentCategory.HATE_SPEECH,
        ContentCategory.DANGEROUS_ACTIVITY,
        ContentCategory.PROMPT_INJECTION,
    }
)

# Default verdicts for overridable categories.
DEFAULT_CATEGORY_ACTIONS: dict[ContentCategory, ModerationVerdict] = {
    ContentCategory.SAFE: ModerationVerdict.PASS,
    ContentCategory.MILD_VIOLENCE: ModerationVerdict.PASS,
    ContentCategory.PERSONAL_INFO: ModerationVerdict.FLAG,
    ContentCategory.OFF_TOPIC: ModerationVerdict.FLAG,
}


class ModerationResult(BaseModel):
    """Result of a single moderation check (FR-24.03)."""

    verdict: ModerationVerdict
    category: ContentCategory
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    content_hash: str = ""


class ModerationContext(BaseModel):
    """Contextual information passed to the moderation service."""

    game_id: str = ""
    player_id: str = ""
    turn_id: str = ""
    stage: str = ""  # "input" | "output"
