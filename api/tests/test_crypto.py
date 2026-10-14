from app import crypto


def test_encrypt_roundtrip():
    secret = "refresh-token-abc123"
    blob = crypto.encrypt(secret)
    assert blob != secret
    assert crypto.decrypt(blob) == secret
