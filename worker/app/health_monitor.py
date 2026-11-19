"""System health sampling and threshold alerts.

Runs on the worker (Celery beat schedules it), once per ``HEALTH_CHECK_INTERVAL_SECONDS``:

1. Sample CPU, memory and disk.
2. Publish the sample to Redis so the API/UI can show live numbers.
3. Compare against the thresholds saved in the admin UI and notify Slack and/or
   email â€” once per breach, then again only after the cooldown.
4. Send a recovery notice when a metric returns below its threshold.

Deliberately separate from job alerts: this is about the container or host
running extractions, and disk is the one that takes the whole platform down
(exports and pgdata share the filesystem).

CPU and memory are read from the container's cgroup when one is configured, so
the numbers match what ``docker stats`` shows and a container limit is what the
thresholds actually measure. Without a cgroup limit both fall back to the host,
where host-wide and container-wide are the same thing.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import time
from datetime import UTC, datetime
from typing import Any

import psutil
from sqlalchemy import select

from app import db, notifications
from app.celery_app import celery
from app.config import get_settings

CONFIG_KEY = "health_alerts"
SAMPLE_KEY = "logvault:health:sample"
_LATCH_PREFIX = "logvault:health:breach:"
_LATCH_COOLDOWN_PREFIX = "logvault:health:alerted:"

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "cpu_threshold_pct": 85,
    "memory_threshold_pct": 85,
    "disk_threshold_pct": 85,
    # Blank = the export volume, which is the one whose exhaustion breaks Postgres.
    "disk_path": "",
    "cooldown_minutes": 30,
    "slack": True,
    "email": False,
    "recipients": [],
    "notify_on_recovery": True,
}

_METRIC_LABEL = {
    "cpu": "CPU",
    "memory": "Memory",
    "disk": "Disk",
}


def _redis():
    import redis

    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def load_config() -> dict[str, Any]:
    """Saved thresholds over defaults. Read per tick so the UI applies at once."""
    cfg = dict(DEFAULTS)
    try:
        with db.engine().connect() as conn:
            row = conn.execute(
                select(db.app_settings.c.value).where(db.app_settings.c.key == CONFIG_KEY)
            ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - a config read must not kill the monitor
        return cfg
    if row:
        for key, value in dict(row).items():
            if key in DEFAULTS:
                cfg[key] = value
    return cfg


_CGROUP_ROOT = "/sys/fs/cgroup"


def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="ascii") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _cgroup_memory(root: str = _CGROUP_ROOT) -> dict[str, float] | None:
    """Container memory from cgroup v2, or None when unlimited or unavailable.

    ``memory.current`` includes page cache. Exports are large and mostly written
    once, so a long run fills the cache and a raw reading would look like an
    imminent OOM. ``docker stats`` subtracts the inactive half; so do we. On a
    cgroup v1 host these files are absent and the caller falls back to psutil.
    """
    limit_raw = _read_text(f"{root}/memory.max")
    current_raw = _read_text(f"{root}/memory.current")
    if not limit_raw or not current_raw or limit_raw == "max":
        return None
    try:
        limit = int(limit_raw)
        current = int(current_raw)
    except ValueError:
        return None
    if limit <= 0:
        return None
    inactive = 0
    for line in (_read_text(f"{root}/memory.stat") or "").splitlines():
        if line.startswith("inactive_file "):
            try:
                inactive = int(line.split()[1])
            except (IndexError, ValueError):
                inactive = 0
            break
    used = max(0, current - inactive)
    return {
        "memory_pct": round(used / limit * 100, 1),
        "memory_used_mb": round(used / 1024**2),
        "memory_total_mb": round(limit / 1024**2),
    }


def _cgroup_cpu_quota(root: str = _CGROUP_ROOT) -> float | None:
    """Container CPU quota in cores from cgroup v2, or None when unlimited."""
    raw = _read_text(f"{root}/cpu.max")
    if not raw:
        return None
    parts = raw.split()
    if len(parts) != 2 or parts[0] == "max":
        return None
    try:
        quota, period = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if quota <= 0 or period <= 0:
        return None
    return quota / period


def _cgroup_cpu_usage_usec(root: str = _CGROUP_ROOT) -> int | None:
    for line in (_read_text(f"{root}/cpu.stat") or "").splitlines():
        if line.startswith("usage_usec "):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def _cpu_sample(
    host_pct: float,
    quota: float | None,
    used_before: int | None,
    used_after: int | None,
    elapsed_s: float,
) -> float:
    """Percent of the container's CPU allotment, or of the host when unlimited."""
    if quota and used_before is not None and used_after is not None and elapsed_s > 0:
        pct = (used_after - used_before) / 1e6 / (elapsed_s * quota) * 100
        return round(min(100.0, max(0.0, pct)), 1)
    return round(host_pct, 1)


def _memory_sample(host: Any, cgroup: dict[str, float] | None) -> dict[str, float]:
    if cgroup is not None:
        return cgroup
    return {
        "memory_pct": round(host.percent, 1),
        "memory_used_mb": round((host.total - host.available) / 1024**2),
        "memory_total_mb": round(host.total / 1024**2),
    }


def _resolve_disk_path(cfg: dict[str, Any] | None) -> str:
    """The configured path when it exists, else the export volume.

    Falling back rather than creating the directory keeps a typo in the admin
    UI from quietly measuring an empty directory in the container layer.
    """
    configured = str((cfg or {}).get("disk_path") or "").strip()
    if configured and os.path.isdir(configured):
        return configured
    return get_settings().storage_dir


def sample(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Current metrics. ``cpu`` is a 1-second sample, not a since-boot mean.

    The same second used by ``psutil.cpu_percent`` also brackets the cgroup CPU
    counter, so the sample costs one sleep rather than two.
    """
    disk_path = _resolve_disk_path(cfg)
    os.makedirs(disk_path, exist_ok=True)
    usage = shutil.disk_usage(disk_path)

    usage_before = _cgroup_cpu_usage_usec()
    started = time.monotonic()
    host_cpu = psutil.cpu_percent(interval=1.0)
    elapsed = time.monotonic() - started
    usage_after = _cgroup_cpu_usage_usec()

    memory = _memory_sample(psutil.virtual_memory(), _cgroup_memory())
    return {
        "ts": datetime.now(UTC).isoformat(),
        "cpu_pct": _cpu_sample(host_cpu, _cgroup_cpu_quota(), usage_before, usage_after, elapsed),
        **memory,
        "disk_pct": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        "disk_free_gb": round(usage.free / 1024**3, 1),
        "disk_total_gb": round(usage.total / 1024**3, 1),
        "disk_path": disk_path,
        "load1": round(os.getloadavg()[0], 2) if hasattr(os, "getloadavg") else None,
    }


def _breaches(cfg: dict[str, Any], metrics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    thresholds = {
        "cpu": float(cfg.get("cpu_threshold_pct") or 0),
        "memory": float(cfg.get("memory_threshold_pct") or 0),
        "disk": float(cfg.get("disk_threshold_pct") or 0),
    }
    found: dict[str, dict[str, Any]] = {}
    for metric, threshold in thresholds.items():
        if threshold <= 0:
            continue
        value = float(metrics.get(f"{metric}_pct") or 0)
        if value >= threshold:
            found[metric] = {"value": value, "threshold": threshold}
    return found


def _format_breach(metric: str, detail: dict[str, Any], metrics: dict[str, Any]) -> tuple[str, str]:
    label = _METRIC_LABEL[metric]
    subject = f"LogVault: {label} at {detail['value']:.1f}% (threshold {detail['threshold']:.0f}%)"
    if metric == "cpu":
        body = (
            f"CPU usage is {detail['value']:.1f}% against a {detail['threshold']:.0f}% threshold.\n"
            f"Host load average (1m): {metrics.get('load1')}\n\n"
            "Extraction throughput will drop while the worker's CPU allotment is saturated. "
            "Consider reducing WORKER_CONCURRENCY or giving the worker more CPU."
        )
    elif metric == "memory":
        body = (
            f"Memory usage is {detail['value']:.1f}% against a {detail['threshold']:.0f}% threshold.\n"
            f"Used {metrics.get('memory_used_mb')} MB of {metrics.get('memory_total_mb')} MB.\n\n"
            "A worker killed for OOM leaves jobs to be reaped and retried."
        )
    else:
        body = (
            f"Disk usage is {detail['value']:.1f}% against a {detail['threshold']:.0f}% threshold.\n"
            f"Free {metrics.get('disk_free_gb')} GB of {metrics.get('disk_total_gb')} GB on "
            f"{metrics.get('disk_path')}.\n\n"
            "Exports are written here. When this filesystem fills, jobs stop being written — "
            "and if Postgres shares it, the whole platform becomes read-only."
        )
    return subject, body


@celery.task(name="logvault.check_system_health")
def check_system_health() -> dict[str, Any]:
    cfg = load_config()
    metrics = sample(cfg)

    try:
        r = _redis()
        r.set(SAMPLE_KEY, json.dumps(metrics), ex=900)
    except Exception:  # noqa: BLE001 - publishing is best-effort
        r = None

    if not cfg.get("enabled", True):
        return {"metrics": metrics, "alerts": []}

    active = _breaches(cfg, metrics)
    cooldown = max(1, int(cfg.get("cooldown_minutes") or 30))
    sent: list[str] = []

    for metric, detail in active.items():
        subject, body = _format_breach(metric, detail, metrics)
        # Latch: notify on the transition into breach, then again after cooldown.
        first = True
        if r is not None:
            try:
                first = bool(
                    r.set(f"{_LATCH_COOLDOWN_PREFIX}{metric}", "1", nx=True, ex=cooldown * 60)
                )
                r.set(f"{_LATCH_PREFIX}{metric}", json.dumps(detail), ex=7 * 86400)
            except Exception:  # noqa: BLE001
                first = True
        if not first:
            continue
        results = notifications.send_health_alert(
            subject=subject,
            body=body,
            slack=bool(cfg.get("slack")),
            email=bool(cfg.get("email")),
            recipients=[str(x).strip() for x in (cfg.get("recipients") or []) if str(x).strip()],
        )
        delivered = [name for name, detail in results.items() if detail.get("ok")]
        # Recorded per metric so a silent channel is visible in the task result
        # instead of looking like a successful alert.
        sent.append(f"{metric}:{'/'.join(delivered) or 'undelivered'}")

    # Recovery: a metric that had a latched breach and is now below threshold.
    if cfg.get("notify_on_recovery", True) and r is not None:
        for metric in _METRIC_LABEL:
            if metric in active:
                continue
            try:
                latched = r.getdel(f"{_LATCH_PREFIX}{metric}")
            except Exception:  # noqa: BLE001
                latched = None
            if not latched:
                continue
            with contextlib.suppress(Exception):
                r.delete(f"{_LATCH_COOLDOWN_PREFIX}{metric}")
            label = _METRIC_LABEL[metric]
            recovery = notifications.send_health_alert(
                subject=f"LogVault: {label} recovered",
                body=(
                    f"{label} usage is back below its threshold "
                    f"({metrics.get(f'{metric}_pct')}%)."
                ),
                slack=bool(cfg.get("slack")),
                email=bool(cfg.get("email")),
                recipients=[
                    str(x).strip() for x in (cfg.get("recipients") or []) if str(x).strip()
                ],
            )
            delivered = [name for name, detail in recovery.items() if detail.get("ok")]
            sent.append(f"{metric}:recovered:{'/'.join(delivered) or 'undelivered'}")

    return {"metrics": metrics, "alerts": sent}
