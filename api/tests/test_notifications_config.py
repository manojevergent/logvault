"""Notification settings: persisted, admin-only, password encrypted at rest.

The endpoint used to be a no-op that returned {"ok": True} without storing
anything, so the form reported success and alerts kept using env vars only.
"""

from __future__ import annotations

import pytest

from app import crypto, notifications
from app.models import AppSetting

CFG = {
    "slack_webhook_url": "https://hooks.slack.com/services/T/B/xyz",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "noc-alerts@evergent.com",
    "smtp_password": "hunter2-app-password",
    "smtp_from": "noc-alerts@evergent.com",
}


def test_saving_persists_and_is_read_back(client):
    assert client.patch("/settings/notifications", json=CFG).status_code == 200

    out = client.get("/settings/notifications").json()
    assert out["smtp_host"] == "smtp.gmail.com"
    assert out["smtp_user"] == "noc-alerts@evergent.com"
    assert out["smtp_port"] == 587
    assert out["slack_webhook_url"] == CFG["slack_webhook_url"]
    # The password is never echoed back — only whether one exists.
    assert out["smtp_password_set"] is True
    assert "smtp_password" not in out


def test_password_is_encrypted_at_rest(client):
    client.patch("/settings/notifications", json=CFG)

    with client.session_factory() as db:
        stored = db.get(AppSetting, notifications.NOTIFICATIONS_KEY).value
        assert "smtp_password" not in stored, "plaintext password stored"
        assert stored["smtp_password_encrypted"] != CFG["smtp_password"]
        assert crypto.decrypt(stored["smtp_password_encrypted"]) == CFG["smtp_password"]


def test_blank_password_keeps_the_stored_one(client):
    client.patch("/settings/notifications", json=CFG)
    # The form never receives the password, so a host-only edit sends it blank.
    client.patch(
        "/settings/notifications",
        json={**CFG, "smtp_password": "", "smtp_host": "smtp.office365.com"},
    )

    with client.session_factory() as db:
        cfg = notifications.load_config(db)
    assert cfg["smtp_host"] == "smtp.office365.com"
    assert cfg["smtp_password"] == CFG["smtp_password"]


def test_send_path_reads_saved_config_not_env(client, monkeypatch):
    """What an alert actually sends with — the bug was that this only ever saw
    env vars, so saving in the UI changed nothing.

    send_failure_alert opens its own session (the worker has no request scope),
    so point that at the test database.
    """
    client.patch("/settings/notifications", json=CFG)
    monkeypatch.setattr(notifications, "SessionLocal", client.session_factory)

    sent = {}
    monkeypatch.setattr(notifications, "_send_slack", lambda cfg, *a: sent.update(cfg))
    monkeypatch.setattr(notifications, "_send_email", lambda cfg, *a: None)
    notifications.send_failure_alert(["ops@evergent.com"], "Daily_aha", 42, "boom")

    assert sent["slack_webhook_url"] == CFG["slack_webhook_url"]
    assert sent["smtp_password"] == CFG["smtp_password"]


def test_unset_config_falls_back_to_env(client):
    with client.session_factory() as db:
        cfg = notifications.load_config(db)
    # Nothing saved yet -> the env-based settings still apply.
    assert cfg["smtp_port"] == 587
    assert cfg["smtp_host"] == ""


@pytest.mark.parametrize("method,kwargs", [("get", {}), ("patch", {"json": CFG})])
def test_members_cannot_read_or_change_notification_settings(member_client, method, kwargs):
    assert getattr(member_client, method)("/settings/notifications", **kwargs).status_code == 403


def test_failure_alert_passes_customer_to_email_and_slack(monkeypatch):
    cfg = {
        **CFG,
        "smtp_from": "noc-alerts@evergent.com",
        "smtp_user": "noc-alerts@evergent.com",
        "smtp_password": "secret",
    }
    monkeypatch.setattr(notifications, "load_config", lambda: cfg)
    monkeypatch.setattr(notifications, "_retry", lambda fn: fn())

    captured: dict[str, str] = {}

    def email(_cfg, _recipients, _name, _job_id, _error, customer=""):
        captured["email"] = customer

    def slack(_cfg, _name, _job_id, _error, customer=""):
        captured["slack"] = customer

    monkeypatch.setattr(notifications, "_send_email", email)
    monkeypatch.setattr(notifications, "_send_slack", slack)

    notifications.send_failure_alert(["ops@evergent.com"], "Daily_aha", 42, "boom", "ACME")
    assert captured == {"email": "ACME", "slack": "ACME"}
