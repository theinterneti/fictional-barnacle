"""Password hashing and verification using bcrypt (S11 FR-11.24-28).

Used for the anonymous→registered upgrade flow where players
set an email and password to preserve their game history.
"""

from __future__ import annotations

import bcrypt

from tta.config import get_settings


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt."""
    settings = get_settings()
    salt = bcrypt.gensalt(rounds=settings.bcrypt_cost)
    return bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())
