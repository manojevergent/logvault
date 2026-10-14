"""Send alerts on job failure via email + Slack."""

from __future__ import annotations

import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
from sqlalchemy import select

from app import crypto
from app import db as dbmod
from app.config import get_settings

settings = get_settings()

NOTIFICATIONS_KEY = "notifications"
_FIELDS = ("slack_webhook_url", "smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from")


def load_config() -> dict:
    """Saved config over env defaults, SMTP password decrypted.

    Mirrors api/app/notifications.load_config — the worker deliberately does not
    import the api package (see db.py). Read at send time, not import time, so a
    change saved in the admin UI applies without restarting this process.
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
    return cfg


def _retry(func, max_retries: int = None, delay: int = None):
    """Retry a function with exponential backoff."""
    if max_retries is None:
        max_retries = settings.notification_max_retries
    if delay is None:
        delay = settings.notification_retry_delay_seconds

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                print(
                    f"[notification.retry] attempt={attempt}, max={max_retries}, error={exc}",
                    file=sys.stderr,
                )
                time.sleep(delay * attempt)  # exponential: 5s, 10s, 15s
    raise last_exc


def send_failure_alert(
    recipients: list[str],
    schedule_name: str,
    job_id: int,
    error_message: str,
) -> None:
    """Send email + Slack notification for a failed job (sync).

    ponytail: if one fails, other still tries. Retries configured in settings.
    """
    if not recipients:
        return

    cfg = load_config()

    if cfg["smtp_host"] and cfg["smtp_user"]:
        try:
            _retry(lambda: _send_email(cfg, recipients, schedule_name, job_id, error_message))
        except Exception as exc:
            print(f"[email.final_error] {exc}", file=sys.stderr)

    if cfg["slack_webhook_url"]:
        try:
            _retry(lambda: _send_slack(cfg, schedule_name, job_id, error_message))
        except Exception as exc:
            print(f"[slack.final_error] {exc}", file=sys.stderr)


def _send_email(
    cfg: dict,
    recipients: list[str],
    schedule_name: str,
    job_id: int,
    error_message: str,
) -> None:
    """Send email to recipients."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"LogVault: Schedule '{schedule_name}' failed (Job {job_id})"
    msg["From"] = cfg["smtp_from"]
    msg["To"] = ", ".join(recipients)

    text = f"""Schedule '{schedule_name}' (Job {job_id}) failed.

Error: {error_message}

Check the job details at the LogVault dashboard.
"""
    part = MIMEText(text, "plain")
    msg.attach(part)

    server = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30)
    try:
        server.starttls()
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.sendmail(cfg["smtp_from"], recipients, msg.as_string())
    finally:
        server.quit()

    print(f"[email.sent] schedule={schedule_name}, job={job_id}, recipients={recipients}")


def _send_slack(
    cfg: dict,
    schedule_name: str,
    job_id: int,
    error_message: str,
) -> None:
    """Send Slack notification (sync)."""
    payload = {
        "text": "⚠️ LogVault Job Failure",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Schedule:* {schedule_name}\n*Job ID:* {job_id}\n*Error:* {error_message}",
                },
            }
        ],
    }

    httpx.post(cfg["slack_webhook_url"], json=payload, timeout=10)
    print(f"[slack.sent] schedule={schedule_name}, job={job_id}")
