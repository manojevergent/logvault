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


def _retry(func, max_retries: int | None = None, delay: int | None = None):
    """Retry a function with linear backoff.

    ``max_retries`` is the total number of attempts, not the number of retries
    after the first. Each wait is ``delay * attempt``, so 5s, 10s, 15s — linear,
    not exponential. With the defaults a failed alert can hold a worker slot for
    about two minutes, which is why the send happens outside the transaction.
    """
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
            print(f"[email.final_error] {exc}", file=sys.stderr)

    if cfg["slack_webhook_url"]:
        try:
            _retry(lambda: _send_slack(cfg, schedule_name, job_id, error_message, customer))
        except Exception as exc:
            print(f"[slack.final_error] {exc}", file=sys.stderr)


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

    print(f"[email.sent] schedule={schedule_name}, job={job_id}, recipients={recipients}")


def _send_slack(
    cfg: dict,
    schedule_name: str,
    job_id: int,
    error_message: str,
    customer: str = "",
) -> None:
    """Send Slack notification (sync)."""
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
    print(f"[slack.sent] schedule={schedule_name}, job={job_id}")


def send_anomaly_alert(
    recipients: list[str],
    schedule_name: str,
    job_id: int,
    customer: str,
    *,
    reasons: list[str],
    current_rows: int,
    previous_rows: int | None,
    drop_pct: float | None,
    rows_unmatched: int,
    parsed_rows: int,
    unmatched_pct: float | None,
    row_drop_threshold_pct: int,
    unmatched_threshold: int,
) -> dict[str, dict[str, object]]:
    """Send an anomaly alert for a completed scheduled run.

    Email goes to the schedule's recipients; Slack uses the global webhook, so
    a team can receive anomalies there even when no per-schedule email address
    has been configured.

    Returns one entry per channel with what actually happened, exactly like
    ``send_health_alert``. The caller records the "Anomaly detected" marker
    before this runs, so a silent channel failure would otherwise leave a job
    that looks alerted while nobody was told. Returning the outcome is what
    lets the caller write that failure down.
    """
    cfg = load_config()
    who = f"[{customer}] " if customer else ""
    subject = f"LogVault: {who}Schedule '{schedule_name}' anomaly (Job {job_id})"

    details = [
        f"Schedule '{schedule_name}' (Job {job_id}) completed with an anomaly.",
        f"Customer: {customer or '(unassigned)'}",
        f"Rows written: {current_rows:,}",
        f"Previous run: {previous_rows:,}" if previous_rows is not None else "Previous run: n/a",
    ]
    if drop_pct is not None:
        # drop_pct is "percent lost", so a positive number means a smaller run.
        # Printing it signed read as growth in the alert body.
        direction = "drop" if drop_pct > 0 else "growth" if drop_pct < 0 else "flat"
        details.append(f"Row change: {abs(drop_pct):.1f}% {direction}")
        details.append(f"Row-drop threshold: {row_drop_threshold_pct}%")
    if parsed_rows:
        details.append(f"Unmatched rows: {rows_unmatched:,} of {parsed_rows:,} parsed")
        if unmatched_pct is not None:
            details.append(f"Unmatched share: {unmatched_pct:.2f}%")
        details.append(f"Unmatched threshold: {unmatched_threshold:,} rows")
    body = (
        "\n".join(details)
        + "\n\nReasons:\n"
        + "\n".join(f"- {reason}" for reason in reasons)
        + "\n\nCheck the job details at the LogVault dashboard."
    )

    result: dict[str, dict[str, object]] = {}
    if not recipients:
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
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            print(f"[email.final_error] {exc}", file=sys.stderr)
            result["email"] = {"attempted": True, "ok": False, "reason": str(exc)[:300]}

    if not cfg["slack_webhook_url"]:
        result["slack"] = {"attempted": False, "ok": False, "reason": "no Slack webhook configured"}
    else:
        try:
            _retry(lambda: _send_slack_text(cfg["slack_webhook_url"], subject, body))
            result["slack"] = {"attempted": True, "ok": True, "reason": "sent"}
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            print(f"[slack.final_error] {exc}", file=sys.stderr)
            result["slack"] = {"attempted": True, "ok": False, "reason": str(exc)[:300]}

    return result


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
    msg.attach(MIMEText(_render_alert_html(subject, body), "html"))

    server = _smtp_connection(cfg)
    try:
        if int(cfg["smtp_port"]) != 465:
            server.starttls()
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.sendmail(cfg["smtp_from"], recipients, msg.as_string())
    finally:
        server.quit()
    print(f"[email.sent] subject={subject}, recipients={recipients}")


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
    print(f"[slack.health_sent] subject={subject}")
