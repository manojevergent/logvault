"""System health alert config + worker capacity endpoints."""

from __future__ import annotations

import app.routers.admin as admin_router
import app.tasks_client as tasks_client


def test_health_alert_config_defaults_and_roundtrip(client):
    got = client.get("/settings/health-alerts")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["cpu_threshold_pct"] == 85
    assert body["enabled"] is True
    # Email on by default but no recipients would be an unusable default.
    saved = client.put(
        "/settings/health-alerts",
        json={
            "enabled": True,
            "cpu_threshold_pct": 70,
            "memory_threshold_pct": 80,
            "disk_threshold_pct": 90,
            "cooldown_minutes": 15,
            "slack": True,
            "email": False,
            "recipients": ["ops@example.com"],
            "notify_on_recovery": False,
        },
    )
    assert saved.status_code == 200, saved.text
    again = client.get("/settings/health-alerts").json()
    assert again["cpu_threshold_pct"] == 70
    assert again["disk_threshold_pct"] == 90
    assert again["cooldown_minutes"] == 15
    assert again["recipients"] == ["ops@example.com"]
    assert again["notify_on_recovery"] is False


def test_health_alert_config_rejects_out_of_range_thresholds(client):
    base = {
        "enabled": True,
        "cpu_threshold_pct": 85,
        "memory_threshold_pct": 85,
        "disk_threshold_pct": 85,
        "cooldown_minutes": 30,
        "slack": True,
        "email": False,
        "recipients": [],
        "notify_on_recovery": True,
    }
    response = client.put("/settings/health-alerts", json={**base, "cpu_threshold_pct": 0})
    assert response.status_code == 422
    response = client.put("/settings/health-alerts", json={**base, "cooldown_minutes": 0})
    assert response.status_code == 422


def test_email_channel_requires_a_recipient(client):
    response = client.put(
        "/settings/health-alerts",
        json={
            "enabled": True,
            "cpu_threshold_pct": 85,
            "memory_threshold_pct": 85,
            "disk_threshold_pct": 85,
            "cooldown_minutes": 30,
            "slack": False,
            "email": True,
            "recipients": [],
            "notify_on_recovery": True,
        },
    )
    assert response.status_code == 422
    assert "recipient" in response.json()["detail"]


def test_email_defaults_off_until_recipients_exist(client):
    body = client.get("/settings/health-alerts").json()
    assert body["email"] is False
    assert body["slack"] is True


def test_test_alert_dispatches_to_configured_channels(client, monkeypatch):
    calls = []

    def fake_send(**kwargs):
        calls.append(kwargs)
        return {
            "email": {"attempted": True, "ok": True, "reason": "sent"},
            "slack": {"attempted": True, "ok": True, "reason": "sent"},
        }

    monkeypatch.setattr(admin_router.notifications, "send_health_alert", fake_send)
    client.put(
        "/settings/health-alerts",
        json={
            "enabled": True,
            "cpu_threshold_pct": 85,
            "memory_threshold_pct": 85,
            "disk_threshold_pct": 85,
            "cooldown_minutes": 30,
            "slack": True,
            "email": True,
            "recipients": ["ops@example.com"],
            "notify_on_recovery": True,
        },
    )
    response = client.post("/settings/health-alerts/test")
    assert response.status_code == 200
    assert calls and calls[0]["slack"] is True and calls[0]["email"] is True
    assert calls[0]["recipients"] == ["ops@example.com"]
    body = response.json()
    assert body["ok"] is True
    assert "email" in body["message"]


def test_test_alert_reports_a_channel_that_was_off(client, monkeypatch):
    """The old endpoint claimed success while email was disabled — that is how a
    missing inbox message became impossible to diagnose."""

    def fake_send(**kwargs):
        return {
            "email": {"attempted": False, "ok": False, "reason": "email channel is off"},
            "slack": {"attempted": True, "ok": True, "reason": "sent"},
        }

    monkeypatch.setattr(admin_router.notifications, "send_health_alert", fake_send)
    client.put(
        "/settings/health-alerts",
        json={
            "enabled": True,
            "cpu_threshold_pct": 85,
            "memory_threshold_pct": 85,
            "disk_threshold_pct": 85,
            "cooldown_minutes": 30,
            "slack": True,
            "email": False,
            "recipients": ["ops@example.com"],
            "notify_on_recovery": True,
        },
    )
    body = client.post("/settings/health-alerts/test").json()
    assert body["ok"] is True
    assert "email" in body["skipped"]
    assert "email channel is off" in body["skipped"]["email"]


def test_test_alert_surfaces_an_smtp_failure(client, monkeypatch):
    def fake_send(**kwargs):
        return {
            "email": {
                "attempted": True,
                "ok": False,
                "reason": "SMTP authentication failed — the password was rejected.",
            },
            "slack": {"attempted": False, "ok": False, "reason": "slack channel is off"},
        }

    monkeypatch.setattr(admin_router.notifications, "send_health_alert", fake_send)
    body = client.post("/settings/health-alerts/test").json()
    assert body["ok"] is False
    assert "authentication failed" in body["failed"]["email"]
    assert "Nothing was delivered" in body["message"]


def test_test_alert_reports_when_nothing_is_configured(client, monkeypatch):
    def fake_send(**kwargs):
        return {
            "email": {"attempted": False, "ok": False, "reason": "email channel is off"},
            "slack": {"attempted": False, "ok": False, "reason": "no Slack webhook configured"},
        }

    monkeypatch.setattr(admin_router.notifications, "send_health_alert", fake_send)
    body = client.post("/settings/health-alerts/test").json()
    assert body["ok"] is False
    assert "Nothing was sent" in body["message"]


def test_health_metrics_reports_absence_before_the_worker_samples(client):
    response = client.get("/health/metrics")
    assert response.status_code == 200
    assert response.json()["available"] is False


def test_worker_capacity_reports_when_no_worker_answers(client, monkeypatch):
    monkeypatch.setattr(tasks_client, "_stats", lambda: {})
    response = client.get("/admin/worker")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["configured"] >= 1


def _capacity_fake(state: dict):
    return lambda: {
        "configured": 4,
        "running": state["running"],
        "active_jobs": 0,
        "nodes": 1,
        "available": True,
    }


def test_worker_concurrency_grows_the_pool(client, monkeypatch):
    state = {"running": 4}
    monkeypatch.setattr(tasks_client, "worker_capacity", _capacity_fake(state))
    monkeypatch.setattr(tasks_client, "_RESIZE_POLL_DELAY", 0)

    class Control:
        def pool_grow(self, n: int) -> None:
            state["running"] += n

        def pool_shrink(self, n: int) -> None:
            state["running"] -= n

    monkeypatch.setattr(tasks_client, "_control", lambda: Control())

    response = client.post("/admin/worker/concurrency", json={"concurrency": 8})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] is True
    assert body["previous"] == 4
    assert state["running"] == 8


def test_worker_concurrency_shrinks_the_pool(client, monkeypatch):
    state = {"running": 8}
    monkeypatch.setattr(tasks_client, "worker_capacity", _capacity_fake(state))
    monkeypatch.setattr(tasks_client, "_RESIZE_POLL_DELAY", 0)

    class Control:
        def pool_grow(self, n: int) -> None:
            state["running"] += n

        def pool_shrink(self, n: int) -> None:
            state["running"] -= n

    monkeypatch.setattr(tasks_client, "_control", lambda: Control())

    response = client.post("/admin/worker/concurrency", json={"concurrency": 3})
    assert response.status_code == 200
    assert response.json()["applied"] is True
    assert state["running"] == 3


def test_worker_concurrency_is_a_no_op_when_already_there(client, monkeypatch):
    state = {"running": 4}
    monkeypatch.setattr(tasks_client, "worker_capacity", _capacity_fake(state))
    monkeypatch.setattr(tasks_client, "_RESIZE_POLL_DELAY", 0)
    called: list[int] = []
    monkeypatch.setattr(tasks_client, "_control", lambda: _FakeControl(called))
    response = client.post("/admin/worker/concurrency", json={"concurrency": 4})
    assert response.status_code == 200
    assert response.json()["applied"] is False
    assert called == []


def test_worker_concurrency_rejects_out_of_range(client):
    assert client.post("/admin/worker/concurrency", json={"concurrency": 0}).status_code == 422
    assert client.post("/admin/worker/concurrency", json={"concurrency": 100}).status_code == 422


class _FakeControl:
    def __init__(self, grown: list[int]) -> None:
        self._grown = grown

    def pool_grow(self, n: int) -> None:
        self._grown.append(n)

    def pool_shrink(self, n: int) -> None:
        self._grown.append(-n)
