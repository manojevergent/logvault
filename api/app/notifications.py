"""Send alerts on job failure via email + Slack."""

from __future__ import annotations

import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx

from app import crypto
from app.config import get_settings
from app.database import SessionLocal
from app.logging_config import get_logger
from app.models import AppSetting

log = get_logger("logvault.notifications")
settings = get_settings()

NOTIFICATIONS_KEY = "notifications"
_FIELDS = ("slack_webhook_url", "smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from")


def _env_defaults() -> dict:
    return {f: getattr(settings, f) for f in _FIELDS}


def load_config(db=None) -> dict:
    """Saved config over env defaults, with the SMTP password decrypted.

    Read at send time, not import time, so saving in the UI takes effect without
    restarting the API and worker.
    """
    own = db is None
    db = db or SessionLocal()
    try:
        cfg = _env_defaults()
        row = db.get(AppSetting, NOTIFICATIONS_KEY)
        if row and row.value:
            saved = dict(row.value)
            enc = saved.pop("smtp_password_encrypted", "")
            if enc:
                try:
                    saved["smtp_password"] = crypto.decrypt(enc)
                except Exception:  # key rotated out from under the stored value
                    log.warning("notifications.password_undecryptable")
            cfg.update({k: v for k, v in saved.items() if k in _FIELDS and v not in ("", None)})
        return cfg
    finally:
        if own:
            db.close()


def save_config(db, cfg: dict, updated_by: str | None = None) -> None:
    """Persist config, encrypting the SMTP password. A blank password keeps the
    stored one — the UI never receives it back, so it cannot resend it."""
    row = db.get(AppSetting, NOTIFICATIONS_KEY)
    stored = dict(row.value) if row and row.value else {}
    for f in _FIELDS:
        if f == "smtp_password":
            continue
        if f in cfg:
            stored[f] = cfg[f]
    password = cfg.get("smtp_password") or ""
    if password:
        stored["smtp_password_encrypted"] = crypto.encrypt(password)
    stored.pop("smtp_password", None)  # never store plaintext
    if row is None:
        db.add(AppSetting(key=NOTIFICATIONS_KEY, value=stored, updated_by=updated_by))
    else:
        row.value = stored
        row.updated_by = updated_by


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
                log.warning(
                    "notification.retry",
                    attempt=attempt,
                    max_retries=max_retries,
                    delay=delay,
                    error=str(exc),
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
            log.exception("email.final_error", exc_info=exc)

    if cfg["slack_webhook_url"]:
        try:
            _retry(lambda: _send_slack(cfg, schedule_name, job_id, error_message))
        except Exception as exc:
            log.exception("slack.final_error", exc_info=exc)


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

    log.info("email.sent", recipients=recipients, schedule=schedule_name, job_id=job_id)


def _send_slack(
    cfg: dict,
    schedule_name: str,
    job_id: int,
    error_message: str,
) -> None:
    """Send Slack notification."""
    payload = {
        "text": f"⚠️ LogVault Job Failure",
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
    log.info("slack.sent", schedule=schedule_name, job_id=job_id)
