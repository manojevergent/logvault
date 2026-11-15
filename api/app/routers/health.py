"""Liveness, readiness and operational-health endpoints.

- /health      : process is up (liveness). Cheap, no dependencies.
- /ready       : dependencies reachable (readiness). Checks Postgres + Redis.
- /health/ops  : the things that fail silently — worker beat, database backups.

/ops is separate from /ready on purpose. /ready answers "should this process
take traffic"; a dead worker or a missing backup does not make the API unable to
serve, so folding them in would pull a perfectly healthy container out of
rotation. They still need someone told, which is what this endpoint is for.
"""

from __future__ import annotations

import glob
import os
import time
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import text

from app import dispatch_health
from app.config import get_settings
from app.database import engine
from app.redis_client import get_broker_redis, get_redis
from app.tasks_client import worker_ping

# Written by the worker at the end of every beat tick (worker/app/scheduler.py).
BEAT_KEY = "logvault:beat"

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict[str, object]:
    checks: dict[str, str] = {}
    ok = True

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report, don't crash readiness probe
        checks["postgres"] = f"error: {exc.__class__.__name__}"
        ok = False

    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc.__class__.__name__}"
        ok = False

    return {"status": "ok" if ok else "degraded", "checks": checks}


def _worker_check(settings) -> str:
    """Whether beat is still ticking.

    This is the one failure nobody notices on their own: if the worker is down,
    schedules stop firing and the only symptom is a report that never arrives,
    usually spotted days later by the person who needed it.
    """
    try:
        raw = get_redis().get(BEAT_KEY)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        return f"unknown: {exc.__class__.__name__}"
    if not raw:
        return "stale: no heartbeat recorded"
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(raw)).total_seconds()
    except ValueError:
        return "unknown: unreadable heartbeat"
    if age < settings.worker_beat_stale_seconds:
        return "ok"
    return f"stale: {int(age)}s since last beat"


def _backup_check(settings) -> str:
    """Freshness of the newest dump written by the `backup` service."""
    dumps = glob.glob(os.path.join(settings.backup_dir, "*.dump"))
    if not dumps:
        return f"stale: no backups in {settings.backup_dir}"
    age_hours = (time.time() - max(os.path.getmtime(p) for p in dumps)) / 3600
    if age_hours < settings.backup_stale_hours:
        return "ok"
    return f"stale: newest backup is {age_hours:.0f}h old"


@router.get("/health/dispatch")
def dispatch() -> dict[str, object]:
    """Dispatch reliability gauges with their alert thresholds.

    Counts only -- no job ids or customer ids, so cardinality is bounded and a
    scrape cannot leak identifiers.
    """
    try:
        with engine.connect() as conn:
            metrics = dispatch_health.collect(conn)
    except Exception as exc:  # noqa: BLE001 - a metrics outage must not 500 ops
        return {"status": "unknown", "error": type(exc).__name__}

    # Broker telemetry is best-effort: a Redis problem yields None values
    # ("unknown"), never a failed health check and never a misleading zero.
    try:
        # Queue depth and the beat lock live in the Celery broker database, not
        # in REDIS_URL's database; passing both clients is what makes the lock
        # check truthful.
        broker = dispatch_health.collect_broker(
            get_redis(), get_broker_redis(), worker_probe=worker_ping
        )
    except Exception:  # noqa: BLE001
        broker = {"celery_queue_depth": None, "beat_lock_present": None,
                  "beat_lock_ttl_s": None, "beat_heartbeat_age_s": None,
                  "worker_online": None}

    db_part = dispatch_health.evaluate(metrics)
    broker_part = dispatch_health.evaluate_broker(broker)
    order = {"ok": 0, "unknown": 1, "warn": 2, "critical": 3}
    status = max((db_part["status"], broker_part["status"]), key=lambda s: order[s])
    return {
        "status": status,
        "checks": db_part["checks"],
        "broker_checks": broker_part["checks"],
        "metrics": metrics,
        "broker": broker,
    }


@router.get("/health/ops")
def ops() -> dict[str, object]:
    settings = get_settings()
    checks = {
        "worker_beat": _worker_check(settings),
        "backups": _backup_check(settings),
    }
    ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}
