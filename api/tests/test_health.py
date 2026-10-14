"""Smoke tests for the health/meta endpoints (no external deps required)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import health

client = TestClient(app)


class _FakeRedis:
    def __init__(self, beat: str | None) -> None:
        self._beat = beat

    def get(self, _key: str) -> str | None:
        if self._beat is None:
            raise ConnectionError("redis is down")
        return self._beat


@pytest.fixture
def ops(tmp_path, monkeypatch):
    """/health/ops with a throwaway backup directory and a scriptable heartbeat."""
    settings = health.get_settings()
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path), raising=False)

    def run(*, beat: str | None, backup_age_hours: float | None):
        monkeypatch.setattr(health, "get_redis", lambda: _FakeRedis(beat))
        if backup_age_hours is not None:
            dump = tmp_path / "logvault-20260924-000000.dump"
            dump.write_bytes(b"x")
            old = time.time() - backup_age_hours * 3600
            os.utime(dump, (old, old))
        return client.get("/health/ops").json()

    return run


def test_health_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_root_meta() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "LogVault API"
    assert "version" in body


def _iso(**delta) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat()


def test_ops_ok_when_beat_is_fresh_and_a_recent_backup_exists(ops) -> None:
    body = ops(beat=_iso(seconds=30), backup_age_hours=2)
    assert body == {"status": "ok", "checks": {"worker_beat": "ok", "backups": "ok"}}


def test_ops_reports_a_dead_worker(ops) -> None:
    """The failure nobody notices otherwise: schedules just stop firing."""
    body = ops(beat=_iso(hours=2), backup_age_hours=2)
    assert body["status"] == "degraded"
    assert body["checks"]["worker_beat"].startswith("stale:")


def test_ops_reports_a_missing_heartbeat(ops) -> None:
    body = ops(beat="", backup_age_hours=2)
    assert body["checks"]["worker_beat"] == "stale: no heartbeat recorded"


def test_ops_reports_an_unreachable_redis_without_crashing(ops) -> None:
    body = ops(beat=None, backup_age_hours=2)
    assert body["checks"]["worker_beat"].startswith("unknown:")
    assert body["status"] == "degraded"


def test_ops_reports_missing_and_stale_backups(ops) -> None:
    assert ops(beat=_iso(seconds=5), backup_age_hours=None)["checks"]["backups"].startswith(
        "stale: no backups"
    )


def test_ops_reports_a_stale_backup(ops) -> None:
    body = ops(beat=_iso(seconds=5), backup_age_hours=72)
    assert body["checks"]["backups"] == "stale: newest backup is 72h old"
    assert body["status"] == "degraded"
