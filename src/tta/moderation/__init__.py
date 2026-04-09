"""Content moderation for TTA (S24 v1).

Provides input/output moderation with configurable verdicts
per content category. Default implementation uses keyword-based
classification; LLM-based classification planned for v2.
"""

from tta.moderation.flagging import SessionFlagTracker
from tta.moderation.models import (
    ALWAYS_BLOCK,
    ContentCategory,
    ModerationContext,
    ModerationRecord,
    ModerationResult,
    ModerationVerdict,
)
from tta.moderation.recorder import ModerationRecorder
from tta.moderation.service import ModerationService

__all__ = [
    "ALWAYS_BLOCK",
    "ContentCategory",
    "ModerationContext",
    "ModerationRecord",
    "ModerationRecorder",
    "ModerationResult",
    "ModerationService",
    "ModerationVerdict",
    "SessionFlagTracker",
]
