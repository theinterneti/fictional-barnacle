"""Content moderation domain models (S24 FR-24.02–FR-24.05, FR-24.09)."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

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

# Default verdicts for overridable categories.  Operators can override
# these at runtime via ``TTA_MODERATION_CATEGORY_OVERRIDES`` (JSON dict,
# see config.py).  ALWAYS_BLOCK categories cannot be relaxed.
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
    flags: list[str] = Field(default_factory=list)


class ModerationContext(BaseModel):
    """Contextual information passed to the moderation service."""

    game_id: str = ""
    player_id: str = ""
    turn_id: str = ""
    stage: str = ""  # "input" | "output"


class ModerationRecord(BaseModel):
    """Persistent record of a moderation action (FR-24.09).

    Stored in the ``moderation_records`` Postgres table. General
    logs reference ``moderation_id`` and ``content_hash`` only —
    the raw content lives exclusively in this table (FR-24.14).
    """

    moderation_id: str = Field(default_factory=lambda: str(uuid4()))
    turn_id: str
    game_id: str
    player_id: str
    stage: str  # "input" | "output"
    content_hash: str
    content: str  # raw text, access-controlled (FR-24.14)
    verdict: ModerationVerdict
    category: ContentCategory
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
