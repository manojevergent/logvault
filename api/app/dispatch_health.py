"""Dispatch reliability metrics for the operations endpoints.

Low cardinality by design: every value is a count or an age, never a job id,
customer id or request id. Identifiers stay in job rows and logs.

Thresholds are part of this module so the alert contract is testable rather
than prose. `evaluate()` is pure, so the thresholds can be asserted without a
database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy import func, select

# (warn, critical). Ages are seconds.
THRESHOLDS: dict[str, tuple[float, float]] = {
    "outbox_oldest_pending_age_s": (60, 300),
    "outbox_dead": (1, 5),
    "leases_expired": (1, 10),
    "jobs_running_without_lease": (1, 5),
    "partial_jobs_24h": (1, 50),
    "completed_without_pointer_24h": (1, 5),
}

ALERTS = {
    "outbox_oldest_pending_age_s": "Dispatch is stalled: pending outbox rows are ageing. Check the beat service, the dispatcher task and broker reachability.",
    "outbox_dead": "Dead-lettered dispatch rows need replay. Inspect last_error, fix the cause, then reset status to pending.",
    "leases_expired": "Worker leases are expiring. Check worker health, Redis reachability and task time limits.",
    "jobs_running_without_lease": "Running jobs have no lease: the reconciler cleared them but nothing reclaimed them. Check the dispatcher.",
    "partial_jobs_24h": "Jobs are completing partially. Inspect gap_reason for Last9 API failures or skipped ID batches.",
    "completed_without_pointer_24h": "Jobs completed without a publication pointer. Treat as artifact drift; check runner logs.",
    "celery_queue_depth": "Broker backlog. Check worker count/health and Redis memory; scale workers or reduce churn.",
    "beat_heartbeat_age_s": "No scheduler tick. Check the beat service, its guard lock and Redis reachability.",
    "beat_lock_present": "No beat lock exists, so no scheduler owns the clock. Start exactly one beat instance.",
    "worker_online": "No worker heartbeat. Check worker containers and their database/Redis connectivity.",
}


def evaluate(metrics: dict[str, float]) -> dict[str, object]:
    """Return per-key state plus an overall status. Pure function."""
    states: dict[str, dict[str, object]] = {}
    overall = "ok"
    for key, (warn, critical) in THRESHOLDS.items():
        value = metrics.get(key, 0) or 0
        if value >= critical:
            state = "critical"
        elif value >= warn:
            state = "warn"
        else:
            state = "ok"
        states[key] = {
            "value": value,
            "state": state,
            "warn_at": warn,
            "critical_at": critical,
            "alert": ALERTS.get(key),
        }
        if state == "critical":
            overall = "critical"
        elif state == "warn" and overall == "ok":
            overall = "warn"
    return {"status": overall, "checks": states}


BROKER_THRESHOLDS: dict[str, tuple[float, float]] = {
    "celery_queue_depth": (100, 1000),
    "beat_heartbeat_age_s": (120, 300),
}

BEAT_LOCK_KEY = "logvault:beat:lock"
BEAT_HEARTBEAT_KEY = "logvault:beat"


def evaluate_broker(metrics: dict[str, float]) -> dict[str, object]:
    """Broker-side gauges. ``None`` means telemetry was unavailable, not zero."""
    checks: dict[str, dict[str, object]] = {}
    overall = "ok"
    unknown = 0

    for key, (warn, critical) in BROKER_THRESHOLDS.items():
        value = metrics.get(key)
        if value is None:
            checks[key] = {"value": None, "state": "unknown", "alert": ALERTS.get(key)}
            unknown += 1
            continue
        state = "critical" if value >= critical else "warn" if value >= warn else "ok"
        checks[key] = {"value": value, "state": state, "warn_at": warn,
                       "critical_at": critical, "alert": ALERTS.get(key)}
        if state == "critical":
            overall = "critical"
        elif state == "warn" and overall == "ok":
            overall = "warn"

    lock = metrics.get("beat_lock_present")
    ttl = metrics.get("beat_lock_ttl_s")
    if lock is None:
        lock_state = "unknown"
    elif lock == 0:
        lock_state = "critical"
    elif ttl is not None and ttl < 30:
        lock_state = "warn"
    else:
        lock_state = "ok"
    checks["beat_lock"] = {"value": lock, "ttl_s": ttl, "state": lock_state,
                           "alert": ALERTS.get("beat_lock_present")}
    if lock_state == "critical":
        overall = "critical"
    elif lock_state == "warn" and overall == "ok":
        overall = "warn"

    workers = metrics.get("worker_online")
    checks["worker_online"] = {"value": workers,
                               "state": "unknown" if workers is None
                               else "ok" if workers else "critical",
                               "alert": ALERTS.get("worker_online")}
    if workers == 0:
        overall = "critical"
    if workers is None:
        unknown += 1

    # Nothing measurable is not the same as healthy: report unknown, so an
    # outage in telemetry cannot masquerade as a clean bill of health.
    if overall == "ok" and unknown:
        overall = "unknown"

    return {"status": overall, "checks": checks}


def parse_heartbeat(value) -> datetime | None:
    """Parse the scheduler's ISO-8601 heartbeat into an aware UTC datetime.

    The writer stores ``datetime.now(UTC).isoformat()``, which yields ``+00:00``
    or ``Z`` depending on version, and may carry any offset. A naive value is
    treated as UTC; anything unparseable is ``None`` so callers report unknown
    rather than a healthy-looking zero.
    """
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode()
        except UnicodeDecodeError:
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def heartbeat_age(value, *, now: datetime | None = None) -> float | None:
    """Age of the heartbeat in seconds, or None when it cannot be trusted.

    A timestamp far in the future means clock skew, not freshness, so it is
    reported as unknown instead of a healthy zero.
    """
    parsed = parse_heartbeat(value)
    if parsed is None:
        return None
    reference = now or datetime.now(UTC)
    age = (reference - parsed).total_seconds()
    if age < -5:
        return None
    return max(0.0, age)


def collect_broker(
    client,
    broker_client=None,
    heartbeat_max_age: float = 300.0,
    worker_probe=None,
) -> dict[str, float | None]:
    """Best-effort broker telemetry. Never raises; missing values are None.

    ``client`` is the general Redis database (worker/beat heartbeat keys).
    ``broker_client`` is the Celery broker database, where the queue and the
    beat singleton lock actually live. Defaulting it to ``client`` keeps the
    function usable when both are the same instance.
    """
    broker = broker_client if broker_client is not None else client
    out: dict[str, float | None] = {
        "celery_queue_depth": None,
        "beat_lock_present": None,
        "beat_lock_ttl_s": None,
        "beat_heartbeat_age_s": None,
        "worker_online": None,
    }
    try:
        out["celery_queue_depth"] = float(broker.llen("celery"))
    except Exception:  # noqa: BLE001 - telemetry must not break the endpoint
        pass
    try:
        ttl = broker.ttl(BEAT_LOCK_KEY)
        if ttl is not None:
            out["beat_lock_present"] = 0.0 if ttl == -2 else 1.0
            out["beat_lock_ttl_s"] = float(max(0, ttl)) if ttl >= 0 else None
    except Exception:  # noqa: BLE001
        pass
    try:
        # The scheduler writes an ISO-8601 string, not an epoch. Age is computed
        # in aware UTC; an unparseable or future timestamp stays None (unknown).
        out["beat_heartbeat_age_s"] = heartbeat_age(client.get(BEAT_HEARTBEAT_KEY))
    except Exception:  # noqa: BLE001
        pass

    # Worker availability is independent of Beat: it is a live probe against the
    # Celery workers, so a healthy scheduler cannot mask a dead worker pool.
    if worker_probe is not None:
        try:
            result = worker_probe()
        except Exception:  # noqa: BLE001 - broker/timeout -> unknown
            result = None
        out["worker_online"] = None if result is None else (1.0 if result else 0.0)

    return out


def collect(conn) -> dict[str, float]:
    """Gather the gauges. One round of small indexed queries, no job ids."""
    from app.models import Job, JobDispatchOutbox

    now = datetime.now(UTC)
    day_ago = now.replace(hour=0, minute=0, second=0, microsecond=0)

    outbox_pending = conn.execute(
        select(func.count()).select_from(JobDispatchOutbox).where(
            JobDispatchOutbox.status == "pending"
        )
    ).scalar_one()
    oldest = conn.execute(
        select(func.min(JobDispatchOutbox.next_attempt_at)).where(
            JobDispatchOutbox.status == "pending"
        )
    ).scalar_one()
    dead = conn.execute(
        select(func.count()).select_from(JobDispatchOutbox).where(
            JobDispatchOutbox.status == "dead"
        )
    ).scalar_one()
    running = conn.execute(
        select(func.count()).select_from(Job).where(Job.status == "running")
    ).scalar_one()
    expired = conn.execute(
        select(func.count()).select_from(Job).where(
            Job.status == "running",
            Job.lease_expires_at.isnot(None),
            Job.lease_expires_at < func.now(),
        )
    ).scalar_one()
    running_no_lease = conn.execute(
        select(func.count()).select_from(Job).where(
            Job.status == "running", Job.lease_expires_at.is_(None)
        )
    ).scalar_one()
    partial = conn.execute(
        select(func.count()).select_from(Job).where(
            Job.completion_state == "partial", Job.finished_at >= day_ago
        )
    ).scalar_one()
    no_pointer = conn.execute(
        select(func.count()).select_from(Job).where(
            Job.status == "completed",
            Job.output_file_path.is_(None),
            Job.finished_at >= day_ago,
        )
    ).scalar_one()

    age = 0.0
    if oldest is not None:
        age = max(0.0, (now - oldest).total_seconds())

    return {
        "outbox_pending": float(outbox_pending or 0),
        "outbox_oldest_pending_age_s": float(age),
        "outbox_dead": float(dead or 0),
        "jobs_running": float(running or 0),
        "leases_expired": float(expired or 0),
        "jobs_running_without_lease": float(running_no_lease or 0),
        "partial_jobs_24h": float(partial or 0),
        "completed_without_pointer_24h": float(no_pointer or 0),
    }
