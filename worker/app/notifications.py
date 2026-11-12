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


def _retry(func, max_retries: int | None = None, delay: int | None = None):
    """Retry a function with linear backoff."""
    if max_retries is None:
        max_retries = settings.notification_max_retries
    if delay is None:
        delay = settings.notification_retry_delay_seconds
    # A configured 0 would skip the loop and `raise last_exc` would raise None.
    max_retries = max(1, max_retries)

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
    cfg = load_config()

    if recipients and cfg["smtp_host"] and cfg["smtp_user"]:
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


def send_health_alert(
    *,
    subject: str,
    body: str,
    slack: bool,
    email: bool,
    recipients: list[str],
) -> dict[str, dict[str, object]]:
    """Send a host-health alert to the configured channels.

    Returns one entry per channel with what actually happened, so the caller can
    log "skipped: email disabled" or the SMTP error instead of assuming success.
    """
    cfg = load_config()
    result: dict[str, dict[str, object]] = {}

    if not email:
        result["email"] = {"attempted": False, "ok": False, "reason": "email channel is off"}
    elif not recipients:
        result["email"] = {"attempted": False, "ok": False, "reason": "no recipients"}
    elif not (cfg["smtp_host"] and cfg["smtp_user"]):
        result["email"] = {
            "attempted": False,
            "ok": False,
            "reason": "SMTP host/user not configured",
        }
    else:
        try:
            _retry(lambda: _send_plain_email(cfg, recipients, subject, body))
            result["email"] = {"attempted": True, "ok": True, "reason": "sent"}
        except Exception as exc:  # noqa: BLE001
            print(f"[email.health_error] {exc}", file=sys.stderr)
            result["email"] = {
                "attempted": True,
                "ok": False,
                "reason": _friendly_smtp_error(exc),
            }

    if not slack:
        result["slack"] = {"attempted": False, "ok": False, "reason": "slack channel is off"}
    elif not cfg["slack_webhook_url"]:
        result["slack"] = {
            "attempted": False,
            "ok": False,
            "reason": "no Slack webhook configured",
        }
    else:
        try:
            _retry(lambda: _send_slack_text(cfg["slack_webhook_url"], subject, body))
            result["slack"] = {"attempted": True, "ok": True, "reason": "sent"}
        except Exception as exc:  # noqa: BLE001
            print(f"[slack.health_error] {exc}", file=sys.stderr)
            result["slack"] = {"attempted": True, "ok": False, "reason": str(exc)[:300]}

    return result


def _friendly_smtp_error(exc: Exception) -> str:
    text = str(exc)
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (
            "SMTP authentication failed — the password was rejected. Gmail and most "
            "providers need an app-specific password, not the account password."
        )
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return f"SMTP refused the recipient(s): {text[:200]}"
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return f"SMTP refused the sender: {text[:200]}"
    if isinstance(exc, smtplib.SMTPConnectError):
        return f"Could not connect to the SMTP server: {text[:200]}"
    if isinstance(exc, TimeoutError | OSError):
        return f"Could not reach the SMTP server: {text[:200]}"
    return text[:300] or exc.__class__.__name__


def _smtp_connection(cfg: dict):
    """SMTP or SMTPS by port: 465 is implicit TLS and rejects STARTTLS."""
    host = cfg["smtp_host"]
    port = int(cfg["smtp_port"])
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=30)
    return smtplib.SMTP(host, port, timeout=30)


def _send_plain_email(cfg: dict, recipients: list[str], subject: str, body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["smtp_from"]
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body, "plain"))

    server = _smtp_connection(cfg)
    try:
        if int(cfg["smtp_port"]) != 465:
            server.starttls()
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.sendmail(cfg["smtp_from"], recipients, msg.as_string())
    finally:
        server.quit()
    print(f"[email.health_sent] subject={subject}, recipients={recipients}")


def _send_slack_text(webhook: str, subject: str, body: str) -> None:
    payload = {
        "text": subject,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{subject}*\n{body}"},
            }
        ],
    }
    httpx.post(webhook, json=payload, timeout=10)
    print(f"[slack.health_sent] subject={subject}")
