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


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
