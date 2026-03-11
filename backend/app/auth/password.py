"""Password hashing using PBKDF2-HMAC-SHA256 with a random salt.

No third-party dependency — uses the Python standard library only.

Stored format (colon-separated):
    pbkdf2_sha256:<iterations>:<salt_hex>:<hash_hex>
"""

from __future__ import annotations

import hashlib
import hmac
import os

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 260_000  # OWASP 2023 recommendation for PBKDF2-SHA256
_HASH_NAME = "sha256"
_SALT_BYTES = 32


def hash_password(plain: str) -> str:
    """Return a salted PBKDF2-SHA256 hash of *plain* suitable for storage."""
    salt = os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        _HASH_NAME,
        plain.encode("utf-8"),
        salt,
        _ITERATIONS,
    )
    return f"{_ALGORITHM}:{_ITERATIONS}:{salt.hex()}:{dk.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """Return True if *plain* matches the stored hash, False otherwise.

    Performs a constant-time comparison to prevent timing attacks.
    """
    try:
        algorithm, iterations_str, salt_hex, hash_hex = stored.split(":", 3)
    except ValueError:
        return False

    if algorithm != _ALGORITHM:
        return False

    try:
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False

    dk = hashlib.pbkdf2_hmac(
        _HASH_NAME,
        plain.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(dk, expected)
