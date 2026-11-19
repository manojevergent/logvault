"""Send alerts on job failure via email + Slack."""

from __future__ import annotations

import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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


def _render_alert_html(subject: str, body: str) -> str:
    """An email-client-safe HTML card for a plain-text alert.

    Inline styles and a table layout only: Gmail, Outlook and Apple Mail strip
    <style> blocks and external CSS. The plain-text body is still attached as
    the alternative part, so text-only clients see the original message.
    """
    import html as _html
    from datetime import UTC, datetime

    recovered = "recovered" in subject.lower()
    accent = "#16a34a" if recovered else "#d97706"
    badge_bg = "#ecfdf5" if recovered else "#fffbeb"
    badge_fg = "#047857" if recovered else "#b45309"
    badge = "Recovered" if recovered else "Action required"

    title = subject.split(":", 1)[1].strip() if ":" in subject else subject
    paragraphs = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
    first = paragraphs[0].splitlines() if paragraphs else [title]
    lead = first[0].strip() if first else title
    details = [line.strip() for line in first[1:] if line.strip()]
    note = paragraphs[1:]

    stamp = datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")

    def esc(value: str) -> str:
        return _html.escape(value, quote=True)

    detail_rows = "".join(
        '<tr><td style="padding:10px 0;border-top:1px solid #eef2f7;'
        'color:#475569;font-size:13px;line-height:1.55;">' + esc(d) + "</td></tr>"
        for d in details
    )
    detail_html = (
        '<tr><td style="padding:6px 28px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        + detail_rows
        + "</table></td></tr>"
        if details
        else ""
    )
    note_html = "".join(
        '<p style="margin:0 0 10px;color:#475569;font-size:13px;line-height:1.65;">'
        + esc(p)
        + "</p>"
        for p in note
    )
    note_html = (
        '<tr><td style="padding:18px 28px 0;">' + note_html + "</td></tr>" if note_html else ""
    )

    return f"""<!doctype html>
<html lang="en">
<body style="margin:0;padding:0;background:#f4f6f9;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border:1px solid #e6eaf0;border-radius:0;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<tr><td style="background:#0a1f44;padding:20px 28px;">
<table role="presentation" width="100%"><tr>
<td style="color:#ffffff;font-size:18px;font-weight:700;letter-spacing:-0.2px;">LogVault</td>
<td align="right" style="color:#94a3b8;font-size:10px;font-weight:600;letter-spacing:1.4px;text-transform:uppercase;">System alert</td>
</tr></table>
</td></tr>
<tr><td style="height:4px;background:{accent};font-size:0;line-height:0;">&nbsp;</td></tr>
<tr><td style="padding:26px 28px 0;">
<span style="display:inline-block;background:{badge_bg};color:{badge_fg};font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:6px 10px;border-radius:0;">{badge}</span>
<h1 style="margin:14px 0 6px;font-size:22px;line-height:1.3;color:#0f172a;font-weight:700;">{esc(title)}</h1>
<p style="margin:0;color:#475569;font-size:14px;line-height:1.6;">{esc(lead)}</p>
</td></tr>
{detail_html}
{note_html}
<tr><td style="padding:24px 28px 26px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #eef2f7;border-radius:0;">
<tr><td style="padding:14px 16px;color:#64748b;font-size:12px;line-height:1.6;">
Automated alert from LogVault &middot; {stamp}<br>
Manage alert thresholds and recipients in LogVault.
</td></tr>
</table>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


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


def _post_slack(webhook: str, payload: dict) -> None:
    """Post to a Slack webhook and fail loudly when Slack rejects it.

    A revoked webhook answers 404 ``no_service`` and a malformed payload
    answers 400, both as ordinary responses. Without raise_for_status() every
    one of those looked like a delivered message, so a dead webhook reported
    "sent" for as long as nobody read the Slack channel. Raising here puts the
    rejection into _retry and into the per-channel result the caller reports.
    """
    response = httpx.post(webhook, json=payload, timeout=10)
    response.raise_for_status()


def _retry(func, max_retries: int = None, delay: int = None):
    """Retry a function with linear backoff.

    ``max_retries`` is the total number of attempts, not the number of retries
    after the first. Each wait is ``delay * attempt`` — 5s, 10s, 15s — so this is
    linear, not exponential. With the defaults a failed alert can hold a worker
    slot for about two minutes.
    """
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
                time.sleep(delay * attempt)  # linear: 5s, 10s, 15s
    raise last_exc


def send_failure_alert(
    recipients: list[str],
    schedule_name: str,
    job_id: int,
    error_message: str,
    customer: str = "",
) -> None:
    """Send email + Slack notification for a failed job (sync).

    ponytail: if one fails, other still tries. Retries configured in settings.
    """
    cfg = load_config()

    if recipients and cfg["smtp_host"] and cfg["smtp_user"]:
        try:
            _retry(
                lambda: _send_email(
                    cfg, recipients, schedule_name, job_id, error_message, customer
                )
            )
        except Exception as exc:
            log.exception("email.final_error", exc_info=exc)

    if cfg["slack_webhook_url"]:
        try:
            _retry(lambda: _send_slack(cfg, schedule_name, job_id, error_message, customer))
        except Exception as exc:
            log.exception("slack.final_error", exc_info=exc)


def _send_email(
    cfg: dict,
    recipients: list[str],
    schedule_name: str,
    job_id: int,
    error_message: str,
    customer: str = "",
) -> None:
    """Send email to recipients."""
    msg = MIMEMultipart("alternative")
    who = f"[{customer}] " if customer else ""
    msg["Subject"] = f"LogVault: {who}Schedule '{schedule_name}' failed (Job {job_id})"
    msg["From"] = cfg["smtp_from"]
    msg["To"] = ", ".join(recipients)

    text = f"""Schedule '{schedule_name}' (Job {job_id}) failed.
Customer: {customer or "(unassigned)"}

Error: {error_message}

Check the job details at the LogVault dashboard.
"""
    part = MIMEText(text, "plain")
    msg.attach(part)
    msg.attach(MIMEText(_render_alert_html(msg["Subject"], text), "html"))

    server = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30)
    try:
        server.starttls()
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.sendmail(cfg["smtp_from"], recipients, msg.as_string())
    finally:
        server.quit()

    log.info(
        "email.sent",
        recipients=recipients,
        schedule=schedule_name,
        job_id=job_id,
        customer=customer,
    )


def _send_slack(
    cfg: dict,
    schedule_name: str,
    job_id: int,
    error_message: str,
    customer: str = "",
) -> None:
    """Send Slack notification."""
    payload = {
        "text": "⚠️ LogVault Job Failure",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Customer:* {customer or '(unassigned)'}\n"
                        f"*Schedule:* {schedule_name}\n"
                        f"*Job ID:* {job_id}\n"
                        f"*Error:* {error_message}"
                    ),
                },
            }
        ],
    }

    _post_slack(cfg["slack_webhook_url"], payload)
    log.info("slack.sent", schedule=schedule_name, job_id=job_id)


def send_health_alert(
    *,
    subject: str,
    body: str,
    slack: bool,
    email: bool,
    recipients: list[str],
) -> dict[str, dict[str, object]]:
    """Send a host-health alert to the configured channels.

    Returns one entry per channel with what actually happened, so a caller can
    report "skipped: email disabled" or the SMTP error instead of a blanket
    success. A failing channel never stops the other one.
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
            log.exception("email.health_error", exc_info=exc)
            result["email"] = {"attempted": True, "ok": False, "reason": _friendly_smtp_error(exc)}

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
            log.exception("slack.health_error", exc_info=exc)
            result["slack"] = {"attempted": True, "ok": False, "reason": str(exc)[:300]}

    return result


def _friendly_smtp_error(exc: Exception) -> str:
    """Name the cause a person can act on."""
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
    """SMTP or SMTPS depending on the port.

    Port 465 is implicit TLS and rejects the STARTTLS upgrade, which is the most
    common reason a working account "just doesn't send".
    """
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
    msg.attach(MIMEText(_render_alert_html(subject, body), "html"))

    server = _smtp_connection(cfg)
    try:
        if int(cfg["smtp_port"]) != 465:
            server.starttls()
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.sendmail(cfg["smtp_from"], recipients, msg.as_string())
    finally:
        server.quit()
    log.info("email.health_sent", subject=subject, recipients=recipients)


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
    _post_slack(webhook, payload)
    log.info("slack.health_sent", subject=subject)
