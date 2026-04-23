"""S43 — Human playtester feedback data models."""

from __future__ import annotations

import copy
import datetime
from dataclasses import dataclass
from typing import Literal

from tta.quality.feedback import FeedbackRecord

ConsentStatus = Literal["granted", "not_granted", "withdrawn"]

NOT_VALIDATED_THRESHOLD: float = 3.0

_FLOAT_FIELDS = (
    "q_coherence",
    "q_wonder",
    "q_character",
    "q_pacing",
    "q_genesis_comfort",
    "q_consequence",
    "q_overall",
)
_TEXT_FIELDS = ("q_best_moment", "q_worst_moment", "q_confusion", "q_freeform")


@dataclass
class HumanFeedbackRecord:
    """Structured feedback submitted by a human playtester."""

    session_id: str
    scenario_seed_id: str
    turns_played: int
    genesis_completed: bool
    submission_timestamp: datetime.datetime

    # Numeric ratings 1–5
    q_coherence: float
    q_wonder: float
    q_character: float
    q_pacing: float
    q_genesis_comfort: float
    q_consequence: float
    q_overall: float

    q_recommend: Literal["yes", "no", "maybe"]

    # Optional qualitative text (clamped to 500 chars)
    q_best_moment: str = ""
    q_worst_moment: str = ""
    q_confusion: str = ""
    q_freeform: str = ""

    # Privacy / consent
    participant_name: str = ""
    participant_contact: str = ""
    is_anonymized: bool = False
    withdrawal_requested: bool = False
    consent_status: ConsentStatus = "granted"

    def __post_init__(self) -> None:
        for tf in _TEXT_FIELDS:
            value = getattr(self, tf)
            if len(value) > 500:
                object.__setattr__(self, tf, value[:500])

    # ------------------------------------------------------------------
    # Helpers

    def is_low_signal(self) -> bool:
        """True when all numeric ratings are 1 and there is no qualitative text."""
        all_ones = all(getattr(self, f) == 1.0 for f in _FLOAT_FIELDS)
        no_text = not any(getattr(self, tf) for tf in _TEXT_FIELDS)
        return all_ones and no_text

    def anonymize(self) -> HumanFeedbackRecord:
        """Return an anonymized copy; sets is_anonymized=True and clears PII."""
        anon = copy.copy(self)
        anon.participant_name = ""
        anon.participant_contact = ""
        anon.is_anonymized = True
        return anon

    def to_feedback_record(self) -> FeedbackRecord:
        """Bridge to the quality layer FeedbackRecord (session_id → run_id)."""
        return FeedbackRecord(
            run_id=self.session_id,
            q_wonder=self.q_wonder,
            q_consequence=self.q_consequence,
            q_character=self.q_character,
        )

    @classmethod
    def from_dict(cls, data: dict) -> HumanFeedbackRecord:
        """Deserialise from a plain dict (e.g. loaded from JSON)."""
        d = dict(data)
        ts = d.get("submission_timestamp")
        if isinstance(ts, str):
            d["submission_timestamp"] = datetime.datetime.fromisoformat(ts)
        return cls(**d)
