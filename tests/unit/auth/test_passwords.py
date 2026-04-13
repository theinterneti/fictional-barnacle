"""Tests for bcrypt password hashing and verification."""

from __future__ import annotations

import pytest

from tta.auth.passwords import hash_password, verify_password
from tta.config import Settings


@pytest.fixture(autouse=True)
def _override_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use low bcrypt cost for fast tests."""
    s = Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        bcrypt_cost=4,  # minimum for speed
    )
    monkeypatch.setattr("tta.auth.passwords.get_settings", lambda: s)


class TestHashPassword:
    def test_returns_bcrypt_hash(self) -> None:
        h = hash_password("hunter2")
        assert h.startswith("$2b$")

    def test_different_passwords_different_hashes(self) -> None:
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        assert h1 != h2

    def test_same_password_different_salts(self) -> None:
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # unique salt each time


class TestVerifyPassword:
    def test_correct_password_verifies(self) -> None:
        h = hash_password("correct-horse")
        assert verify_password("correct-horse", h) is True

    def test_wrong_password_fails(self) -> None:
        h = hash_password("correct-horse")
        assert verify_password("wrong-horse", h) is False

    def test_empty_password_fails(self) -> None:
        h = hash_password("notempty")
        assert verify_password("", h) is False
