"""Copy the configured Last9 credential into the disposable acceptance DB.

The refresh token is decrypted with the development key and re-encrypted with
the acceptance key inside this process. It is never printed and never written
to disk.
"""

import os

import psycopg
from cryptography.fernet import Fernet

dev = os.environ["DEV_DB"]
acc = os.environ["ACC_DB"]
cred_id = int(os.environ.get("CRED_ID", "9"))

dev_fernet = Fernet(os.environ["DEV_KEY"].encode())
acc_fernet = Fernet(os.environ["ACC_KEY"].encode())

with psycopg.connect(dev) as c:
    row = c.execute(
        "SELECT id, label, org_slug, encrypted_refresh_token, refresh_token_last4 "
        "FROM last9_credentials WHERE id = %s",
        (cred_id,),
    ).fetchone()

if row is None:
    raise SystemExit(f"credential {cred_id} not found in the development database")

plain = dev_fernet.decrypt(row[3].encode())
sealed = acc_fernet.encrypt(plain).decode()

with psycopg.connect(acc) as c:
    c.execute("DELETE FROM last9_credentials WHERE id = %s", (row[0],))
    c.execute(
        "INSERT INTO last9_credentials "
        "(id, label, org_slug, encrypted_refresh_token, refresh_token_last4, owner_scope) "
        "VALUES (%s, %s, %s, %s, %s, 'shared')",
        (row[0], row[1], row[2], sealed, row[4]),
    )

print(f"ok id={row[0]} label={row[1]} org={row[2]} last4={row[4]}")
