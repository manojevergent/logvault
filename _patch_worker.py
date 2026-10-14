import io

# ── worker table mirror ───────────────────────────────────────────────────────
p = "worker/app/db.py"
s = io.open(p, encoding="utf-8").read()
old = '''index_targets = Table(
    "index_targets",'''
new = '''# Runtime settings the admin UI writes; the worker reads them at send time so a
# saved SMTP change applies without restarting this process.
app_settings = Table(
    "app_settings",
    metadata,
    Column("key", String(60), primary_key=True),
    Column("value", JSON),
)

index_targets = Table(
    "index_targets",'''
assert old in s
s = s.replace(old, new, 1)
io.open(p, "w", encoding="utf-8").write(s)
print("worker/db.py -> app_settings table")

# ── worker notifications: same DB-first read as the api ───────────────────────
p = "worker/app/notifications.py"
s = io.open(p, encoding="utf-8").read()
head_old = "from app.config import get_settings"
assert head_old in s, "worker notifications import block not found"
s = s.replace(
    head_old,
    """from sqlalchemy import select

from app import crypto, db as dbmod
from app.config import get_settings""",
    1,
)

# insert the loader right after the module-level settings assignment
anchor = "settings = get_settings()"
assert anchor in s
loader = '''settings = get_settings()

NOTIFICATIONS_KEY = "notifications"
_FIELDS = ("slack_webhook_url", "smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from")


def load_config() -> dict:
    """Saved config over env defaults, SMTP password decrypted.

    Mirrors api/app/notifications.load_config — the worker deliberately does not
    import the api package (see db.py). Read at send time, not import time.
    """
    cfg = {f: getattr(settings, f) for f in _FIELDS}
    try:
        with dbmod.engine().connect() as conn:
            row = conn.execute(
                select(dbmod.app_settings.c.value).where(
                    dbmod.app_settings.c.key == NOTIFICATIONS_KEY
                )
            ).scalar_one_or_none()
    except Exception as exc:  # never let a config read stop an alert going out
        print(f"[notifications.config_read_failed] {exc}")
        return cfg
    if row:
        saved = dict(row)
        enc = saved.pop("smtp_password_encrypted", "")
        if enc:
            try:
                saved["smtp_password"] = crypto.decrypt(enc)
            except Exception:
                print("[notifications.password_undecryptable]")
        cfg.update({k: v for k, v in saved.items() if k in _FIELDS and v not in ("", None)})
    return cfg'''
s = s.replace(anchor, loader, 1)

s = s.replace(
    """    if settings.smtp_host and settings.smtp_user:
        try:
            _retry(lambda: _send_email(recipients, schedule_name, job_id, error_message))""",
    """    cfg = load_config()

    if cfg["smtp_host"] and cfg["smtp_user"]:
        try:
            _retry(lambda: _send_email(cfg, recipients, schedule_name, job_id, error_message))""",
)
s = s.replace(
    """    if settings.slack_webhook_url:
        try:
            _retry(lambda: _send_slack(schedule_name, job_id, error_message))""",
    """    if cfg["slack_webhook_url"]:
        try:
            _retry(lambda: _send_slack(cfg, schedule_name, job_id, error_message))""",
)
s = s.replace(
    """def _send_email(
    recipients: list[str],""",
    """def _send_email(
    cfg: dict,
    recipients: list[str],""",
)
s = s.replace(
    """def _send_slack(
    schedule_name: str,""",
    """def _send_slack(
    cfg: dict,
    schedule_name: str,""",
)
s = s.replace('msg["From"] = settings.smtp_from', 'msg["From"] = cfg["smtp_from"]')
s = s.replace(
    "smtplib.SMTP(settings.smtp_host, settings.smtp_port)",
    'smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30)',
)
s = s.replace(
    "server.login(settings.smtp_user, settings.smtp_password)",
    'server.login(cfg["smtp_user"], cfg["smtp_password"])',
)
s = s.replace(
    "server.sendmail(settings.smtp_from, recipients, msg.as_string())",
    'server.sendmail(cfg["smtp_from"], recipients, msg.as_string())',
)
s = s.replace(
    "httpx.post(settings.slack_webhook_url, json=payload, timeout=10)",
    'httpx.post(cfg["slack_webhook_url"], json=payload, timeout=10)',
)
leftovers = [
    l for l in s.splitlines()
    if "settings." in l and not l.strip().startswith(("#", '"""'))
    and "notification_max_retries" not in l and "notification_retry_delay" not in l
    and "get_settings()" not in l and "getattr(settings" not in l
]
assert not leftovers, f"env-only reads remain: {leftovers}"
io.open(p, "w", encoding="utf-8").write(s)
print("worker/notifications.py -> DB-backed")
