"""Celery application.

Phase 1 provides a configured app plus a `ping` task so the worker, broker, and
result backend can be verified end-to-end. The extraction tasks (Phase 4) build
on this same app.
"""

from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery = Celery(
    "logvault",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks", "app.scheduler", "app.health_monitor", "app.outbox", "app.reconciler"],
)

celery.conf.update(
    task_acks_late=True,  # redelivered if a worker dies mid-task
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # fair queueing — no hoarding of big jobs
    # Slots per worker process. Set here (not only on the command line) so every
    # way of starting the worker honours WORKER_CONCURRENCY, and the API's live
    # grow/shrink targets the same number.
    worker_concurrency=settings.worker_concurrency,
    task_track_started=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        # Durable dispatch: republish anything the outbox still owes, including
        # work created while the broker was unreachable.
        "publish-outbox": {"task": "logvault.publish_outbox", "schedule": 5.0},
        # Recovery does not depend on a message arriving: expired leases are
        # found in the database and redispatched here.
        "reconcile-leases": {"task": "logvault.reconcile_leases", "schedule": 15.0},
        "scan-schedules": {"task": "logvault.scan_schedules", "schedule": 60.0},
        "cleanup-exports": {"task": "logvault.cleanup_exports", "schedule": 3600.0},
        "reap-stale-jobs": {"task": "logvault.reap_stale_jobs", "schedule": 300.0},
        "system-health": {
            "task": "logvault.check_system_health",
            "schedule": float(settings.health_check_interval_seconds),
        },
    },
)
