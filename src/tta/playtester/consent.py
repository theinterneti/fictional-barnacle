"""S43 — Consent gate and withdrawal processing."""

from __future__ import annotations

from tta.playtester.models import HumanFeedbackRecord


class ConsentDeniedError(Exception):
    """Raised when a feedback record has consent_status == 'not_granted'."""


def check_consent_gate(record: HumanFeedbackRecord) -> bool:
    """Enforce the consent gate.

    Returns:
        True  — consent granted, proceed normally.
        False — consent withdrawn, record should be anonymised and skipped.

    Raises:
        ConsentDeniedError — consent was never granted.
    """
    if record.consent_status == "not_granted":
        raise ConsentDeniedError(f"Consent not granted for session {record.session_id}")
    if record.consent_status == "withdrawn":
        return False
    return True  # "granted"


def process_withdrawal(record: HumanFeedbackRecord) -> HumanFeedbackRecord:
    """Return an anonymised copy of *record* with withdrawal_requested=True."""
    anon = record.anonymize()
    anon.withdrawal_requested = True
    return anon
