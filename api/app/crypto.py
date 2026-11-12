"""Symmetric encryption for Last9 tokens at rest (Fernet/AES).

The key comes from LAST9_ENCRYPTION_KEY (env). Plaintext tokens are never logged
and never returned to the browser after save.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().last9_encryption_key.encode())


def key_is_valid(key: str) -> bool:
    """True when ``key`` is a Fernet key: 32 bytes, url-safe base64, padded.

    Fernet rejects unpadded base64, which is exactly what a "strip the ="
    secret generator produces. Checked at startup so a bad key fails loudly
    instead of at the first credential save.
    """
    try:
        Fernet(key.encode())
    except (TypeError, ValueError):
        return False
    return True


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
