"""Tests for Langfuse pseudonymization and enhanced privacy filter."""

from tta.observability.langfuse import pseudonymize_player_id


class TestPseudonymizePlayerId:
    """FR-15.21: Player IDs hashed in Langfuse traces."""

    def test_returns_hex_string(self) -> None:
        result = pseudonymize_player_id("player-123")
        assert isinstance(result, str)
        assert len(result) == 16
        # All hex chars
        int(result, 16)

    def test_deterministic(self) -> None:
        a = pseudonymize_player_id("player-abc")
        b = pseudonymize_player_id("player-abc")
        assert a == b

    def test_different_inputs_different_hashes(self) -> None:
        a = pseudonymize_player_id("player-1")
        b = pseudonymize_player_id("player-2")
        assert a != b

    def test_not_reversible(self) -> None:
        result = pseudonymize_player_id("player-123")
        assert "player-123" not in result
        assert "123" not in result
