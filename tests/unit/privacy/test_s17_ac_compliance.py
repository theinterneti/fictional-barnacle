"""S17 Data Privacy — Acceptance Criteria compliance tests.

Covers spec sections testable without live infrastructure:
  §2 Data classification — DataCategory enum values; classify_field() accuracy
  §3 PII registry — get_pii_fields() returns expected fields; consent non-erasable
  §4 Retention policies — all policies present with correct retention_days values
  §6 Consent enforcement — CURRENT_CONSENT_VERSION; REQUIRED_CONSENT_CATEGORIES
  §9 Age gate — register rejects body when age_13_plus_confirmed is False
  §11 Breach response plan — SECURITY.md exists; contains 72-hour notification

Deferred (infra or external doc only):
  §5 TLS / encryption in transit (infrastructure)
  §7 Third-party data disclosure documentation
  §10 Anonymisation / pseudonymisation script
  §12 /api/v1/privacy endpoint (requires full app fixture)
"""

from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import get_pg
from tta.config import CURRENT_CONSENT_VERSION, REQUIRED_CONSENT_CATEGORIES, Settings
from tta.privacy.classification import (
    DataCategory,
    classify_field,
    get_all_fields,
    get_pii_fields,
)
from tta.privacy.retention import RetentionPolicy
from tta.privacy.retention import get_all_policies as get_policies

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).parents[3]  # tests/unit/privacy/../../..


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": "postgresql://test@localhost/test",
        "neo4j_password": "test",
        "neo4j_uri": "",
    }
    base.update(overrides)
    return Settings(**base)


def _make_result(rows: list[Any]) -> MagicMock:
    result = MagicMock()
    result.one_or_none.return_value = rows[0] if rows else None
    result.all.return_value = rows
    return result


def _make_pg() -> AsyncMock:
    pg = AsyncMock()
    pg.execute.return_value = _make_result([])
    return pg


# ---------------------------------------------------------------------------
# §2 — Data classification
# ---------------------------------------------------------------------------


class TestS17DataClassification:
    """S17 §2 — four-tier data classification registry."""

    def test_datacategory_has_exactly_four_values(self) -> None:
        """DataCategory enum must have exactly 4 values (FR-17.3)."""
        assert len(list(DataCategory)) == 4

    def test_datacategory_values_match_spec(self) -> None:
        """DataCategory values match S17 §2 tier names."""
        assert DataCategory.PII == "pii"
        assert DataCategory.SENSITIVE_GAME_DATA == "sensitive_game_data"
        assert DataCategory.GAME_DATA == "game_data"
        assert DataCategory.SYSTEM_DATA == "system_data"

    def test_player_id_classified_as_pii(self) -> None:
        """player_id is classified as PII (FR-17.4)."""
        result = classify_field("player_id")
        assert result is not None
        assert result.category == DataCategory.PII

    def test_world_state_classified_as_game_data(self) -> None:
        """world_state is classified as GAME_DATA (FR-17.4)."""
        result = classify_field("world_state")
        assert result is not None
        assert result.category == DataCategory.GAME_DATA

    def test_display_name_classified_as_pii(self) -> None:
        """display_name is classified as PII (FR-17.4)."""
        result = classify_field("display_name")
        assert result is not None
        assert result.category == DataCategory.PII

    def test_application_logs_classified_as_system_data(self) -> None:
        """application_logs is classified as SYSTEM_DATA."""
        result = classify_field("application_logs")
        assert result is not None
        assert result.category == DataCategory.SYSTEM_DATA

    def test_unknown_field_returns_none(self) -> None:
        """classify_field returns None for unknown fields (graceful lookup)."""
        result = classify_field("completely_unknown_field_xyz")
        assert result is None

    def test_all_fields_returns_non_empty(self) -> None:
        """get_all_fields() must return a non-empty registry (FR-17.4)."""
        fields = get_all_fields()
        assert len(fields) > 0

    def test_field_classification_has_required_attributes(self) -> None:
        """FieldClassification exposes name, category, storage, retention_days,
        erasable."""
        fc = classify_field("player_id")
        assert fc is not None
        assert hasattr(fc, "name")
        assert hasattr(fc, "category")
        assert hasattr(fc, "storage")
        assert hasattr(fc, "retention_days")
        assert hasattr(fc, "erasable")


# ---------------------------------------------------------------------------
# §3 — PII registry and consent erasability
# ---------------------------------------------------------------------------


class TestS17PiiRegistry:
    """S17 §3 — PII fields list and GDPR erasability constraints."""

    def test_get_pii_fields_returns_non_empty(self) -> None:
        """get_pii_fields() must return at least one field (FR-17.5)."""
        pii_fields = get_pii_fields()
        assert len(pii_fields) > 0

    def test_all_pii_entries_have_pii_category(self) -> None:
        """Every entry returned by get_pii_fields() is categorised as PII."""
        for fc in get_pii_fields():
            assert fc.category == DataCategory.PII, (
                f"Expected PII category for {fc.name!r}"
            )

    def test_consent_records_not_erasable(self) -> None:
        """consent_records must have erasable=False (GDPR legal obligation)."""
        fc = classify_field("consent_records")
        assert fc is not None, "consent_records must be in the field registry"
        assert fc.erasable is False, (
            "consent_records must not be erasable (legal retention obligation)"
        )

    def test_consent_fields_not_erasable(self) -> None:
        """Consent audit fields (consent_version, consent_accepted_at, …)
        are non-erasable."""
        non_erasable = {
            "consent_records",
            "consent_version",
            "consent_accepted_at",
            "consent_categories",
            "age_confirmed_at",
            "consent_ip_hash",
        }
        for field_name in non_erasable:
            fc = classify_field(field_name)
            if fc is not None:  # field may not exist in all revisions
                assert fc.erasable is False, (
                    f"Expected {field_name!r} to be non-erasable"
                )

    def test_player_id_is_erasable(self) -> None:
        """player_id must be erasable (right to erasure, S17 §9)."""
        fc = classify_field("player_id")
        assert fc is not None
        assert fc.erasable is True


# ---------------------------------------------------------------------------
# §4 — Retention policies
# ---------------------------------------------------------------------------


class TestS17RetentionPolicies:
    """S17 §4 — data retention periods per spec."""

    def _by_name(self, name: str) -> RetentionPolicy | None:
        for p in get_policies():
            if p.category == name:
                return p
        return None

    def test_get_policies_returns_non_empty(self) -> None:
        """get_policies() must return at least one policy."""
        assert len(get_policies()) > 0

    def test_completed_session_retention_90_days(self) -> None:
        """Completed sessions in PostgreSQL are retained for 90 days (S17 §4.a)."""
        policy = self._by_name("completed_session_postgresql")
        assert policy is not None, "Policy 'completed_session_postgresql' must exist"
        assert policy.retention_days == 90

    def test_application_logs_retention_30_days(self) -> None:
        """Application logs are retained for 30 days (S17 §4.c)."""
        policy = self._by_name("application_logs")
        assert policy is not None, "Policy 'application_logs' must exist"
        assert policy.retention_days == 30

    def test_traces_retention_7_days(self) -> None:
        """Jaeger traces are retained for 7 days (S17 §4.d)."""
        policy = self._by_name("traces_jaeger")
        assert policy is not None, "Policy 'traces_jaeger' must exist"
        assert policy.retention_days == 7

    def test_player_profile_retention_none(self) -> None:
        """Player profile has no automatic deletion (permanent until erasure
        request)."""
        policy = self._by_name("player_profile")
        assert policy is not None, "Policy 'player_profile' must exist"
        assert policy.retention_days is None

    def test_retention_policy_is_frozen_dataclass(self) -> None:
        """RetentionPolicy is a frozen dataclass (immutable at runtime)."""
        import dataclasses

        assert dataclasses.is_dataclass(RetentionPolicy)
        params = dataclasses.fields(RetentionPolicy)
        field_names = {f.name for f in params}
        assert "category" in field_names
        assert "retention_days" in field_names

    def test_retention_policy_immutable(self) -> None:
        """Frozen dataclass prevents accidental mutation."""
        policy = self._by_name("application_logs")
        assert policy is not None
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            policy.retention_days = 999  # type: ignore[misc]

    def test_retention_policy_has_justification(self) -> None:
        """RetentionPolicy.justification is a non-empty string."""
        for policy in get_policies():
            assert isinstance(policy.justification, str), (
                f"Policy {policy.category!r} missing justification"
            )
            assert len(policy.justification) > 0


import dataclasses  # noqa: E402 (needed for test body above)

# ---------------------------------------------------------------------------
# §6 — Consent enforcement constants
# ---------------------------------------------------------------------------


class TestS17ConsentConstants:
    """S17 §6 — consent version and required categories."""

    def test_current_consent_version_is_semver_string(self) -> None:
        """CURRENT_CONSENT_VERSION is a non-empty string (FR-17.22)."""
        assert isinstance(CURRENT_CONSENT_VERSION, str)
        assert len(CURRENT_CONSENT_VERSION) > 0

    def test_current_consent_version_is_1_0(self) -> None:
        """Consent version must be '1.0' per S17 spec."""
        assert CURRENT_CONSENT_VERSION == "1.0"

    def test_required_consent_categories_is_frozenset(self) -> None:
        """REQUIRED_CONSENT_CATEGORIES is a frozenset (immutable)."""
        assert isinstance(REQUIRED_CONSENT_CATEGORIES, frozenset)

    def test_required_consent_categories_non_empty(self) -> None:
        """At least one consent category is required (FR-17.24)."""
        assert len(REQUIRED_CONSENT_CATEGORIES) > 0

    def test_core_gameplay_is_required(self) -> None:
        """core_gameplay consent is always required."""
        assert "core_gameplay" in REQUIRED_CONSENT_CATEGORIES

    def test_llm_processing_is_required(self) -> None:
        """llm_processing consent is always required."""
        assert "llm_processing" in REQUIRED_CONSENT_CATEGORIES


# ---------------------------------------------------------------------------
# §9 — Age gate (registration endpoint)
# ---------------------------------------------------------------------------


class TestS17AgeGate:
    """S17 §9 — age confirmation required for registration."""

    def _client(self, pg: AsyncMock) -> TestClient:
        app = create_app(_settings())
        app.dependency_overrides[get_pg] = lambda: pg
        return TestClient(app, raise_server_exceptions=False)

    def _valid_body(self) -> dict[str, Any]:
        return {
            "handle": "TestPlayer123",
            "age_13_plus_confirmed": True,
            "consent_version": CURRENT_CONSENT_VERSION,
            "consent_categories": dict.fromkeys(REQUIRED_CONSENT_CATEGORIES, True),
        }

    def test_age_gate_rejects_when_false(self) -> None:
        """POST /api/v1/players with age_13_plus_confirmed=False returns 400."""
        pg = _make_pg()
        client = self._client(pg)
        body = self._valid_body()
        body["age_13_plus_confirmed"] = False

        response = client.post("/api/v1/players", json=body)

        assert response.status_code == 400

    def test_age_gate_error_code(self) -> None:
        """Error code is AGE_CONFIRMATION_REQUIRED when age gate fails."""
        pg = _make_pg()
        client = self._client(pg)
        body = self._valid_body()
        body["age_13_plus_confirmed"] = False

        response = client.post("/api/v1/players", json=body)
        data = response.json()

        # Accept either 422 from Pydantic or 400 from AppError
        assert response.status_code in (400, 422)
        # If it's an AppError response, check the code
        if "code" in data:
            assert data["code"] == "AGE_CONFIRMATION_REQUIRED"

    def test_age_gate_accepts_confirmed(self) -> None:
        """POST /api/v1/players with age_13_plus_confirmed=True proceeds past age gate.

        May fail later on DB (handle uniqueness) but must not fail on age gate.
        """

        pg = _make_pg()
        # Return None for handle uniqueness check → no conflict
        pg.execute.return_value = _make_result([])
        client = self._client(pg)
        body = self._valid_body()

        response = client.post("/api/v1/players", json=body)

        # Age gate must not reject a confirmed player.
        assert response.status_code != 400, (
            "Age gate should have passed with age_13_plus_confirmed=True"
        )

        # Anything except 422 means age gate passed
        if response.status_code == 422:
            data = response.json()
            if "code" in data:
                assert data["code"] != "AGE_CONFIRMATION_REQUIRED", (
                    "Age gate should have passed with age_13_plus_confirmed=True"
                )


# ---------------------------------------------------------------------------
# §11 — Breach response plan
# ---------------------------------------------------------------------------


class TestS17BreachResponse:
    """S17 §11 — documented breach notification procedure."""

    def test_security_md_exists(self) -> None:
        """SECURITY.md exists at repository root (S17 §11 requires documented plan)."""
        security_file = _REPO_ROOT / "SECURITY.md"
        assert security_file.exists(), "SECURITY.md must exist in the repository root"

    def test_security_md_contains_72_hour_notification(self) -> None:
        """SECURITY.md contains 72-hour notification requirement (GDPR Art. 33)."""
        security_file = _REPO_ROOT / "SECURITY.md"
        if not security_file.exists():
            pytest.skip("SECURITY.md not present")
        content = security_file.read_text(encoding="utf-8").lower()
        assert "72 hour" in content or "72-hour" in content, (
            "SECURITY.md must document the 72-hour breach notification timeline"
        )

    def test_security_md_contains_breach_notification_section(self) -> None:
        """SECURITY.md contains a breach notification section or template."""
        security_file = _REPO_ROOT / "SECURITY.md"
        if not security_file.exists():
            pytest.skip("SECURITY.md not present")
        content = security_file.read_text(encoding="utf-8").lower()
        assert "breach" in content, "SECURITY.md must contain a breach response section"

    def test_security_md_contains_notification_template(self) -> None:
        """SECURITY.md contains a notification template or procedure."""
        security_file = _REPO_ROOT / "SECURITY.md"
        if not security_file.exists():
            pytest.skip("SECURITY.md not present")
        content = security_file.read_text(encoding="utf-8").lower()
        # Accept "notification template", "notification plan", "notify", etc.
        has_template = (
            "notification template" in content
            or "notification plan" in content
            or "notify affected" in content
            or "data breach response" in content
        )
        assert has_template, (
            "SECURITY.md must document a notification template or response plan"
        )
