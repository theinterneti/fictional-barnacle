"""Tests for enhanced privacy filter (S17 §3 FR-17.5, FR-15.7)."""

from unittest.mock import MagicMock

from tta.logging import PII_CONTENT_FIELDS, _privacy_filter


class TestEnhancedPrivacyFilter:
    """Verify expanded PII content fields are redacted."""

    def test_display_name_redacted(self) -> None:
        event = {"display_name": "Alice", "event": "test"}
        result = _privacy_filter(MagicMock(), "info", event)
        assert result["display_name"] == "[PII_REDACTED]"

    def test_player_name_redacted(self) -> None:
        event = {"player_name": "Bob", "event": "test"}
        result = _privacy_filter(MagicMock(), "info", event)
        assert result["player_name"] == "[PII_REDACTED]"

    def test_handle_redacted(self) -> None:
        event = {"handle": "cool_player", "event": "test"}
        result = _privacy_filter(MagicMock(), "info", event)
        assert result["handle"] == "[PII_REDACTED]"

    def test_pii_content_fields_complete(self) -> None:
        expected = {
            "player_input",
            "email",
            "phone",
            "address",
            "ip_address",
            "display_name",
            "player_name",
            "handle",
        }
        assert expected == PII_CONTENT_FIELDS

    def test_non_pii_field_passes_through(self) -> None:
        event = {"correlation_id": "abc-123", "event": "test"}
        result = _privacy_filter(MagicMock(), "info", event)
        assert result["correlation_id"] == "abc-123"
