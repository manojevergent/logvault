import base64

from cryptography.fernet import Fernet

from app import crypto


def test_encrypt_roundtrip():
    secret = "refresh-token-abc123"
    blob = crypto.encrypt(secret)
    assert blob != secret
    assert crypto.decrypt(blob) == secret


def test_generated_fernet_key_is_valid():
    assert crypto.key_is_valid(Fernet.generate_key().decode())


def test_unpadded_key_is_rejected():
    # `base64 | tr -d '='` produces this shape; Fernet refuses it, so startup
    # must too rather than failing on the first credential save.
    unpadded = base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")
    assert len(unpadded) == 43
    assert crypto.key_is_valid(unpadded) is False
