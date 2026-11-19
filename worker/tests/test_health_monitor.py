"""Health monitor: threshold evaluation, latch/cooldown, recovery."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    monkeypatch.setattr(monitor, "sample", lambda cfg=None: _metrics(cpu_pct=99))
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
    monkeypatch.setattr(monitor, "sample", lambda cfg=None: _metrics(cpu_pct=5))
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
    monkeypatch.setattr(monitor, "sample", lambda cfg=None: _metrics(cpu_pct=99))
    monkeypatch.setattr(monitor, "_redis", lambda: _fake_redis({}))
    monkeypatch.setattr(monitor.notifications, "send_health_alert", _fake_send(sent))

    result = monitor.check_system_health()
    assert result["alerts"] == []
    assert sent == []
    assert result["metrics"]["cpu_pct"] == 99


# --- cgroup-aware sampling ---------------------------------------------------
#
# A container limit is invisible to psutil: with --memory 512m --cpus 1 it still
# reports the host's 11.7 GB and 14 cores. These read the cgroup files Docker
# actually sets, so a threshold measures the container's allotment.


def test_cgroup_memory_uses_the_container_limit(tmp_path):
    (tmp_path / "memory.max").write_text("536870912\n")
    (tmp_path / "memory.current").write_text("104857600\n")
    (tmp_path / "memory.stat").write_text("anon 104857600\ninactive_file 10485760\n")
    assert monitor._cgroup_memory(str(tmp_path)) == {
        "memory_pct": 17.6,
        "memory_used_mb": 90,
        "memory_total_mb": 512,
    }


def test_cgroup_memory_unlimited_or_absent_falls_back(tmp_path):
    (tmp_path / "memory.max").write_text("max\n")
    (tmp_path / "memory.current").write_text("104857600\n")
    assert monitor._cgroup_memory(str(tmp_path)) is None
    # cgroup v1 hosts and Windows dev runs have no memory.max at all.
    assert monitor._cgroup_memory(str(tmp_path / "missing")) is None


def test_cgroup_cpu_quota_and_usage(tmp_path):
    (tmp_path / "cpu.max").write_text("100000 100000\n")
    (tmp_path / "cpu.stat").write_text("usage_usec 4200000\nuser_usec 1\n")
    assert monitor._cgroup_cpu_quota(str(tmp_path)) == 1.0
    assert monitor._cgroup_cpu_usage_usec(str(tmp_path)) == 4_200_000


def test_cgroup_cpu_unlimited_or_absent_falls_back(tmp_path):
    (tmp_path / "cpu.max").write_text("max 100000\n")
    assert monitor._cgroup_cpu_quota(str(tmp_path)) is None
    assert monitor._cgroup_cpu_usage_usec(str(tmp_path)) is None


def test_cpu_sample_uses_the_quota_delta():
    # 0.9s of CPU in a 1s window against a 1-core quota = 90%.
    assert monitor._cpu_sample(7.6, 1.0, 1_000_000, 1_900_000, 1.0) == 90.0


def test_cpu_sample_is_clamped_to_100():
    assert monitor._cpu_sample(7.6, 1.0, 0, 2_000_000, 1.0) == 100.0


def test_cpu_sample_falls_back_to_the_host_without_a_quota():
    assert monitor._cpu_sample(7.6, None, 1, 2, 1.0) == 7.6


class _HostMemory:
    total = 8 * 1024**3
    available = 6 * 1024**3
    percent = 25.0


def test_memory_sample_prefers_the_container_limit():
    cgroup = {"memory_pct": 1.0, "memory_used_mb": 50, "memory_total_mb": 512}
    assert monitor._memory_sample(_HostMemory(), cgroup) is cgroup


def test_memory_sample_falls_back_to_the_host():
    got = monitor._memory_sample(_HostMemory(), None)
    assert got == {
        "memory_pct": 25.0,
        "memory_used_mb": 2048,
        "memory_total_mb": 8192,
    }


def test_disk_path_setting_is_used_only_when_it_exists(tmp_path, monkeypatch):
    configured = tmp_path / "big"
    configured.mkdir()
    fallback = tmp_path / "exports"
    fallback.mkdir()
    monkeypatch.setattr(monitor, "get_settings", lambda: SimpleNamespace(storage_dir=str(fallback)))
    assert monitor._resolve_disk_path({"disk_path": str(configured)}) == str(configured)
    assert monitor._resolve_disk_path({"disk_path": str(tmp_path / "nope")}) == str(fallback)
    assert monitor._resolve_disk_path({}) == str(fallback)


def test_sample_assembles_container_scoped_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "get_settings", lambda: SimpleNamespace(storage_dir=str(tmp_path)))
    ticks = iter([0.0, 1.0])
    monkeypatch.setattr(monitor.time, "monotonic", lambda: next(ticks))
    usage = iter([0, 1_000_000])
    monkeypatch.setattr(
        monitor, "_cgroup_cpu_usage_usec", lambda root=monitor._CGROUP_ROOT: next(usage)
    )
    monkeypatch.setattr(monitor, "_cgroup_cpu_quota", lambda root=monitor._CGROUP_ROOT: 1.0)
    monkeypatch.setattr(
        monitor,
        "_cgroup_memory",
        lambda root=monitor._CGROUP_ROOT: {
            "memory_pct": 2.0,
            "memory_used_mb": 10,
            "memory_total_mb": 512,
        },
    )
    monkeypatch.setattr(monitor.psutil, "cpu_percent", lambda interval=None: 7.6)
    monkeypatch.setattr(monitor.psutil, "virtual_memory", lambda: _HostMemory())

    got = monitor.sample()

    # 1s of CPU in a 1s window against a 1-core quota, not the host's 7.6%.
    assert got["cpu_pct"] == 100.0
    assert got["memory_pct"] == 2.0
    assert got["memory_total_mb"] == 512
    assert got["disk_path"] == str(tmp_path)


_IMAGE = os.environ.get("LOGVAULT_WORKER_IMAGE", "last9_web_app-worker:prod")


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="needs the Docker CLI to run a limited container",
)
def test_sample_reports_container_limits_in_a_limited_container():
    """A 512 MB container must report 512 MB, not the host's RAM.

    The unit tests above cover the parsing; this proves the real kernel files
    are read the way we expect. It needs Docker and a locally built worker
    image, so it skips in the usual in-container test run.
    """
    if subprocess.run(["docker", "image", "inspect", _IMAGE], capture_output=True).returncode != 0:
        pytest.skip(f"{_IMAGE} is not built")

    worker_dir = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "-v",
            f"{worker_dir}:/app",
            "--entrypoint",
            "python",
            _IMAGE,
            "-c",
            "import json; from app.health_monitor import sample; print(json.dumps(sample()))",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert data["memory_total_mb"] == 512
    assert data["memory_used_mb"] < 512
