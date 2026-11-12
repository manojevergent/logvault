"""Health monitor: threshold evaluation, latch/cooldown, recovery."""

from __future__ import annotations

import app.health_monitor as monitor


def _metrics(**over):
    base = {
        "ts": "2026-01-01T00:00:00+00:00",
        "cpu_pct": 10.0,
        "memory_pct": 20.0,
        "disk_pct": 30.0,
        "memory_used_mb": 100,
        "memory_total_mb": 1000,
        "disk_free_gb": 10.0,
        "disk_total_gb": 100.0,
        "disk_path": "/data/exports",
        "load1": 0.5,
    }
    base.update(over)
    return base


def _cfg(**over):
    base = dict(monitor.DEFAULTS)
    base.update(over)
    return base


def test_no_breach_below_thresholds():
    assert monitor._breaches(_cfg(), _metrics()) == {}


def test_each_metric_breaches_independently():
    found = monitor._breaches(
        _cfg(cpu_threshold_pct=50, memory_threshold_pct=50, disk_threshold_pct=50),
        _metrics(cpu_pct=75, memory_pct=10, disk_pct=90),
    )
    assert set(found) == {"cpu", "disk"}
    assert found["cpu"] == {"value": 75.0, "threshold": 50.0}
    assert found["disk"] == {"value": 90.0, "threshold": 50.0}


def test_a_zero_threshold_disables_that_metric():
    found = monitor._breaches(
        _cfg(cpu_threshold_pct=0, memory_threshold_pct=0, disk_threshold_pct=0),
        _metrics(cpu_pct=100, memory_pct=100, disk_pct=100),
    )
    assert found == {}


def test_breach_message_names_the_metric_and_value():
    subject, body = monitor._format_breach(
        "disk", {"value": 91.5, "threshold": 85}, _metrics(disk_pct=91.5)
    )
    assert "Disk" in subject
    assert "91.5%" in subject
    assert "85%" in subject
    # The disk message must explain why it matters more than CPU/memory.
    assert "Postgres" in body


def _fake_redis(store: dict, deleted: list[str] | None = None):
    class FakeRedis:
        def set(self, key, value, nx=False, ex=None):
            if nx and key in store:
                return None
            store[key] = value
            return True

        def getdel(self, key):
            return store.pop(key, None)

        def delete(self, key):
            (deleted if deleted is not None else []).append(key)
            store.pop(key, None)

    return FakeRedis()


def _fake_send(sent: list[dict], *, ok: bool = True):
    """Stand-in for notifications.send_health_alert: records and reports back."""

    def _send(**kwargs):
        sent.append(kwargs)
        detail = {"attempted": True, "ok": ok, "reason": "sent" if ok else "boom"}
        return {"email": dict(detail), "slack": dict(detail)}

    return _send


def test_alerting_latches_once_then_cools_down(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(monitor, "load_config", lambda: _cfg(cpu_threshold_pct=50))
    monkeypatch.setattr(monitor, "sample", lambda: _metrics(cpu_pct=99))
    store: dict = {}
    monkeypatch.setattr(monitor, "_redis", lambda: _fake_redis(store))
    monkeypatch.setattr(monitor.notifications, "send_health_alert", _fake_send(sent))

    first = monitor.check_system_health()
    assert first["alerts"] == ["cpu:email/slack"]
    assert len(sent) == 1
    assert "CPU" in sent[0]["subject"]

    # Second tick inside the cooldown: latched, no repeat.
    second = monitor.check_system_health()
    assert second["alerts"] == []
    assert len(sent) == 1


def test_recovery_notices_only_when_a_breach_was_latched(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        monitor, "load_config", lambda: _cfg(cpu_threshold_pct=50, notify_on_recovery=True)
    )
    store = {"logvault:health:breach:cpu": "{}", "logvault:health:alerted:cpu": "1"}
    monkeypatch.setattr(monitor, "sample", lambda: _metrics(cpu_pct=5))
    monkeypatch.setattr(monitor, "_redis", lambda: _fake_redis(store))
    monkeypatch.setattr(monitor.notifications, "send_health_alert", _fake_send(sent))

    result = monitor.check_system_health()
    assert result["alerts"] == ["cpu:recovered:email/slack"]
    assert "recovered" in sent[0]["subject"]
    # Cooldown latch cleared so a new breach can alert immediately.
    assert "logvault:health:alerted:cpu" not in store


def test_disabled_monitoring_samples_without_alerting(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(monitor, "load_config", lambda: _cfg(enabled=False))
    monkeypatch.setattr(monitor, "sample", lambda: _metrics(cpu_pct=99))
    monkeypatch.setattr(monitor, "_redis", lambda: _fake_redis({}))
    monkeypatch.setattr(monitor.notifications, "send_health_alert", _fake_send(sent))

    result = monitor.check_system_health()
    assert result["alerts"] == []
    assert sent == []
    assert result["metrics"]["cpu_pct"] == 99
