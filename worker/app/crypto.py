"""Fernet decrypt/encrypt for Last9 tokens.

ponytail: a 3-line mirror of api/app/crypto.py using the same LAST9_ENCRYPTION_KEY.
Promote both to a shared package if a third consumer appears.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().last9_encryption_key.encode())


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()
