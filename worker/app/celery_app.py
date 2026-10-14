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
    include=["app.tasks", "app.scheduler"],
)

celery.conf.update(
    task_acks_late=True,  # redelivered if a worker dies mid-task
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # fair queueing — no hoarding of big jobs
    task_track_started=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "scan-schedules": {"task": "logvault.scan_schedules", "schedule": 60.0},
        "cleanup-exports": {"task": "logvault.cleanup_exports", "schedule": 3600.0},
        "reap-stale-jobs": {"task": "logvault.reap_stale_jobs", "schedule": 300.0},
    },
)
