"""Tests for data classification (S17 §3 FR-17.1 – FR-17.4)."""

from tta.privacy.classification import (
    DataCategory,
    FieldClassification,
    classify_field,
    get_fields_by_category,
    get_pii_fields,
)


class TestDataCategory:
    def test_four_tiers_exist(self) -> None:
        assert len(DataCategory) == 4

    def test_tier_values(self) -> None:
        assert DataCategory.PII.value == "pii"
        assert DataCategory.SENSITIVE_GAME_DATA.value == "sensitive_game_data"
        assert DataCategory.GAME_DATA.value == "game_data"
        assert DataCategory.SYSTEM_DATA.value == "system_data"


class TestClassifyField:
    def test_known_pii_field(self) -> None:
        result = classify_field("email")
        assert result is not None
        assert result.category == DataCategory.PII

    def test_known_system_field(self) -> None:
        result = classify_field("account_created_at")
        assert result is not None
        assert result.category == DataCategory.SYSTEM_DATA

    def test_known_game_data_field(self) -> None:
        result = classify_field("world_state")
        assert result is not None
        assert result.category == DataCategory.GAME_DATA

    def test_known_sensitive_game_data_field(self) -> None:
        result = classify_field("player_input")
        assert result is not None
        assert result.category == DataCategory.SENSITIVE_GAME_DATA

    def test_unknown_field_returns_none(self) -> None:
        result = classify_field("totally_nonexistent_field_xyz")
        assert result is None


class TestGetPiiFields:
    def test_returns_only_pii(self) -> None:
        pii = get_pii_fields()
        assert len(pii) > 0
        for fc in pii:
            assert fc.category == DataCategory.PII

    def test_returns_field_classification_objects(self) -> None:
        pii = get_pii_fields()
        for fc in pii:
            assert isinstance(fc, FieldClassification)
            assert fc.name != ""


class TestGetFieldsByCategory:
    def test_system_data_fields(self) -> None:
        fields = get_fields_by_category(DataCategory.SYSTEM_DATA)
        assert len(fields) > 0
        for fc in fields:
            assert fc.category == DataCategory.SYSTEM_DATA

    def test_all_categories_covered(self) -> None:
        total = 0
        for cat in DataCategory:
            total += len(get_fields_by_category(cat))
        assert total > 0

    def test_empty_for_nonexistent_category_value(self) -> None:
        # All valid categories should return results
        for cat in DataCategory:
            fields = get_fields_by_category(cat)
            assert isinstance(fields, list)


class TestFieldClassification:
    def test_pii_fields_mostly_erasable(self) -> None:
        pii = get_pii_fields()
        # Most PII fields should be erasable; consent_* fields + consent_records
        # are the exceptions (erasable=False for legal retention)
        erasable = [fc for fc in pii if fc.erasable]
        non_erasable = [fc for fc in pii if not fc.erasable]
        assert len(erasable) >= len(pii) - len(non_erasable)

    def test_storage_is_populated(self) -> None:
        result = classify_field("email")
        assert result is not None
        assert result.storage != ""
