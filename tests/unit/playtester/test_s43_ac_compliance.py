"""S43 — Human Playtester Program AC compliance tests.

AC-43.01  Consent gate: not_granted raises ConsentDeniedError
AC-43.02  Structured JSON feedback: HumanFeedbackRecord round-trips via from_dict
AC-43.03  Withdrawal / anonymization via process_withdrawal
AC-43.04  NOT_VALIDATED signal when median overall or coherence < 3.0
"""

from __future__ import annotations

import datetime

import pytest

from tta.playtester.aggregate import (
    check_not_validated_threshold,
    compute_aggregate,
)
from tta.playtester.consent import (
    ConsentDeniedError,
    check_consent_gate,
    process_withdrawal,
)
from tta.playtester.models import HumanFeedbackRecord

# ---------------------------------------------------------------------------
# Fixtures


def _make_record(**kwargs) -> HumanFeedbackRecord:
    defaults: dict = {
        "session_id": "sess-001",
        "scenario_seed_id": "bus-stop-shimmer",
        "turns_played": 10,
        "genesis_completed": True,
        "submission_timestamp": datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        "q_coherence": 4.0,
        "q_wonder": 3.5,
        "q_character": 4.0,
        "q_pacing": 3.0,
        "q_genesis_comfort": 4.0,
        "q_consequence": 3.5,
        "q_overall": 4.0,
        "q_recommend": "yes",
    }
    defaults.update(kwargs)
    return HumanFeedbackRecord(**defaults)


# ---------------------------------------------------------------------------
# AC-43.01 — Consent gate


@pytest.mark.spec("AC-43.01")
def test_consent_gate_not_granted_raises():
    record = _make_record(consent_status="not_granted")
    with pytest.raises(ConsentDeniedError):
        check_consent_gate(record)


@pytest.mark.spec("AC-43.01")
def test_consent_gate_granted_returns_true():
    record = _make_record(consent_status="granted")
    assert check_consent_gate(record) is True


@pytest.mark.spec("AC-43.01")
def test_consent_gate_withdrawn_returns_false():
    record = _make_record(consent_status="withdrawn")
    assert check_consent_gate(record) is False


# ---------------------------------------------------------------------------
# AC-43.02 — Structured JSON feedback


@pytest.mark.spec("AC-43.02")
def test_human_feedback_record_from_dict_roundtrip():
    original = _make_record(q_freeform="Great game!")
    d = {
        "session_id": original.session_id,
        "scenario_seed_id": original.scenario_seed_id,
        "turns_played": original.turns_played,
        "genesis_completed": original.genesis_completed,
        "submission_timestamp": original.submission_timestamp.isoformat(),
        "q_coherence": original.q_coherence,
        "q_wonder": original.q_wonder,
        "q_character": original.q_character,
        "q_pacing": original.q_pacing,
        "q_genesis_comfort": original.q_genesis_comfort,
        "q_consequence": original.q_consequence,
        "q_overall": original.q_overall,
        "q_recommend": original.q_recommend,
        "q_freeform": original.q_freeform,
    }
    restored = HumanFeedbackRecord.from_dict(d)
    assert restored.session_id == original.session_id
    assert restored.q_wonder == original.q_wonder
    assert restored.submission_timestamp == original.submission_timestamp


@pytest.mark.spec("AC-43.02")
def test_text_fields_clamped_to_500():
    long_text = "x" * 600
    record = _make_record(q_freeform=long_text)
    assert len(record.q_freeform) == 500


@pytest.mark.spec("AC-43.02")
def test_to_feedback_record_bridges_session_id():
    record = _make_record(
        session_id="my-session", q_wonder=4.5, q_consequence=2.0, q_character=3.5
    )
    fb = record.to_feedback_record()
    assert fb.run_id == "my-session"
    assert fb.q_wonder == 4.5
    assert fb.q_consequence == 2.0
    assert fb.q_character == 3.5


@pytest.mark.spec("AC-43.02")
def test_is_low_signal_all_ones_no_text():
    record = _make_record(
        q_coherence=1.0,
        q_wonder=1.0,
        q_character=1.0,
        q_pacing=1.0,
        q_genesis_comfort=1.0,
        q_consequence=1.0,
        q_overall=1.0,
    )
    assert record.is_low_signal() is True


@pytest.mark.spec("AC-43.02")
def test_is_low_signal_false_when_text_present():
    record = _make_record(
        q_coherence=1.0,
        q_wonder=1.0,
        q_character=1.0,
        q_pacing=1.0,
        q_genesis_comfort=1.0,
        q_consequence=1.0,
        q_overall=1.0,
        q_freeform="Some feedback",
    )
    assert record.is_low_signal() is False


# ---------------------------------------------------------------------------
# AC-43.03 — Withdrawal / anonymisation


@pytest.mark.spec("AC-43.03")
def test_process_withdrawal_sets_flag_and_anonymizes():
    record = _make_record(
        participant_name="Alice", participant_contact="alice@example.com"
    )
    withdrawn = process_withdrawal(record)
    assert withdrawn.withdrawal_requested is True
    assert withdrawn.is_anonymized is True
    assert withdrawn.participant_name == ""
    assert withdrawn.participant_contact == ""


@pytest.mark.spec("AC-43.03")
def test_process_withdrawal_does_not_mutate_original():
    record = _make_record(participant_name="Bob")
    process_withdrawal(record)
    assert record.participant_name == "Bob"
    assert record.withdrawal_requested is False


@pytest.mark.spec("AC-43.03")
def test_anonymize_copy_preserves_feedback_data():
    record = _make_record(participant_name="Carol", q_overall=4.5)
    anon = record.anonymize()
    assert anon.q_overall == 4.5
    assert anon.participant_name == ""


# ---------------------------------------------------------------------------
# AC-43.04 — NOT_VALIDATED signal


@pytest.mark.spec("AC-43.04")
def test_not_validated_when_overall_below_threshold():
    records = [_make_record(q_overall=2.5, q_coherence=4.0) for _ in range(3)]
    agg = compute_aggregate(records)
    assert check_not_validated_threshold(agg) is True


@pytest.mark.spec("AC-43.04")
def test_not_validated_when_coherence_below_threshold():
    records = [_make_record(q_overall=4.0, q_coherence=2.9) for _ in range(3)]
    agg = compute_aggregate(records)
    assert check_not_validated_threshold(agg) is True


@pytest.mark.spec("AC-43.04")
def test_not_validated_false_when_both_above_threshold():
    records = [_make_record(q_overall=3.5, q_coherence=3.5) for _ in range(3)]
    agg = compute_aggregate(records)
    assert check_not_validated_threshold(agg) is False


@pytest.mark.spec("AC-43.04")
def test_aggregate_not_validated_field_reflects_threshold():
    records = [_make_record(q_overall=2.0, q_coherence=4.0)]
    agg = compute_aggregate(records)
    assert agg.not_validated is True


@pytest.mark.spec("AC-43.04")
def test_compute_aggregate_count_and_mean():
    records = [
        _make_record(q_overall=2.0),
        _make_record(q_overall=4.0),
    ]
    agg = compute_aggregate(records)
    assert agg.count == 2
    assert agg.mean_q_overall == pytest.approx(3.0)
