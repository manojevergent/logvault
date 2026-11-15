"""Dispatch jobs to the Celery worker by task name (no worker import needed)."""

from __future__ import annotations

import time
from functools import lru_cache

from celery import Celery

from app.config import get_settings


@lru_cache
def _celery() -> Celery:
    return Celery("logvault-dispatch", broker=get_settings().celery_broker_url)


def dispatch_job(job_id: int) -> None:
    _celery().send_task("logvault.run_job", args=[job_id])


def dispatch_s3_upload(job_id: int) -> None:
    _celery().send_task("logvault.upload_job_s3", args=[job_id])


def _stats() -> dict:
    """Live worker stats, or {} when no worker answers within the timeout."""
    try:
        return _celery().control.inspect(timeout=3.0).stats() or {}
    except Exception:  # noqa: BLE001 - broker hiccup must not 500 the admin page
        return {}


def worker_ping(timeout: float = 1.5) -> bool | None:
    """True when at least one Celery worker answers a control ping.

    This is a live broker round-trip, deliberately independent of the beat
    heartbeat: a healthy scheduler says nothing about the worker pool. Returns
    None when the answer cannot be established (broker down, timeout), which
    callers must report as unknown rather than as a healthy or dead worker.
    """
    try:
        replies = _celery().control.inspect(timeout=timeout).ping()
    except Exception:  # noqa: BLE001 - a broker hiccup is not a worker verdict
        return None
    if replies is None:
        return False
    return bool(replies)


def _control():
    """The Celery control channel (patched in tests)."""
    return _celery().control


# Resize is a broadcast, so the new size is only visible after the worker
# applies it. Poll briefly; tests set the delay to 0.
_RESIZE_POLL_ATTEMPTS = 6
_RESIZE_POLL_DELAY = 1.0


def worker_capacity() -> dict:
    """Current slot count and queue depth, for the admin capacity card.

    The live size is ``len(pool.processes)``: Celery's ``max-concurrency`` is the
    limit the worker *started* with and does not change on pool_grow/pool_shrink,
    so reading it made a successful resize look like a no-op.
    """
    stats = _stats()
    live = 0
    started_with = None
    for node in stats.values():
        pool = node.get("pool") or {}
        processes = pool.get("processes") or []
        if processes:
            live += len(processes)
        limit = pool.get("max-concurrency")
        if limit is not None:
            started_with = max(started_with or 0, int(limit))

    active = 0
    if stats:
        try:
            active_tasks = _celery().control.inspect(timeout=3.0).active() or {}
            active = sum(len(tasks) for tasks in active_tasks.values())
        except Exception:  # noqa: BLE001
            active = 0

    configured = get_settings().worker_concurrency
    return {
        "configured": configured,
        "running": live or started_with,
        "started_with": started_with,
        "active_jobs": active,
        "nodes": len(stats),
        "available": bool(stats),
    }


def set_worker_concurrency(target: int) -> dict:
    """Grow or shrink the live pool.

    Celery has no "set absolute" control, only relative grow/shrink, so the
    current size is read first. `WORKER_CONCURRENCY` still governs the next
    restart — this changes the running process until then.
    """
    current = worker_capacity()
    running = current.get("running")
    if running is None:
        return {
            "ok": False,
            "applied": False,
            "previous": None,
            "message": (
                "No worker is answering. The change will take effect after restart "
                f"if WORKER_CONCURRENCY is set to {target}."
            ),
        }

    delta = target - int(running)
    if delta == 0:
        return {
            "ok": True,
            "applied": False,
            "previous": running,
            "running": running,
            "message": f"Already running {running} slot(s).",
        }

    try:
        if delta > 0:
            _control().pool_grow(n=delta)
        else:
            _control().pool_shrink(n=-delta)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "applied": False,
            "previous": running,
            "message": f"Could not resize the pool: {exc}",
        }

    # The control command is a broadcast: the worker applies it asynchronously,
    # so reading the pool immediately returns the old size. Poll briefly rather
    # than reporting a resize that visibly did nothing.
    after_running = running
    for _ in range(_RESIZE_POLL_ATTEMPTS):
        time.sleep(_RESIZE_POLL_DELAY)
        after_running = worker_capacity().get("running") or after_running
        if after_running == target:
            break

    return {
        "ok": True,
        "applied": after_running != running,
        "previous": running,
        "running": after_running,
        "message": (
            f"Pool resized from {running} to {after_running}. "
            "Set WORKER_CONCURRENCY to make it survive a restart."
            if after_running != running
            else (
                f"Resize command sent, but the pool still reports {after_running} slot(s). "
                "Check the worker log; set WORKER_CONCURRENCY for a restart-safe change."
            )
        ),
    }
