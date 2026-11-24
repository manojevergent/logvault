"""Seed the acceptance DB with the configured Last9 credential.

Runs inside the acceptance API container. The development ciphertext is
decrypted with the development key and re-encrypted with this container's key.
Nothing is printed except a confirmation.
"""

import os

import psycopg
from cryptography.fernet import Fernet

plain = Fernet(os.environ["DEV_KEY"].encode()).decrypt(
    os.environ["DEV_CIPHERTEXT"].encode()
)
sealed = Fernet(os.environ["LAST9_ENCRYPTION_KEY"].encode()).encrypt(plain).decode()

url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
with psycopg.connect(url) as c:
    c.execute("DELETE FROM last9_credentials WHERE id = 9")
    c.execute(
        "INSERT INTO last9_credentials "
        "(id, label, org_slug, encrypted_refresh_token, refresh_token_last4, owner_scope) "
        "VALUES (9, %s, %s, %s, %s, 'shared')",
        (os.environ["CRED_LABEL"], os.environ["CRED_ORG"], sealed, os.environ["CRED_LAST4"]),
    )

print("credential seeded")
