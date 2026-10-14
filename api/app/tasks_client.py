"""Dispatch jobs to the Celery worker by task name (no worker import needed)."""

from __future__ import annotations

from functools import lru_cache

from celery import Celery

from app.config import get_settings


@lru_cache
def _celery() -> Celery:
    return Celery("logvault-dispatch", broker=get_settings().celery_broker_url)


def dispatch_job(job_id: int) -> None:
    _celery().send_task("logvault.run_job", args=[job_id])
