"""Celery tasks.

Phase 1: a single `ping` health task. Extraction tasks land in Phase 4.
"""

from __future__ import annotations

import contextlib
import os
import shutil
from datetime import UTC, datetime

from sqlalchemy import text

from app.celery_app import celery
from app.config import get_settings
from app.notifications import send_failure_alert


@celery.task(name="logvault.ping")
def ping() -> str:
    """Trivial task to verify broker + roundtrips."""
    return "pong"


def _require_disk_space() -> None:
    """Refuse to start a job when the export volume is nearly full.

    Exports and `pgdata` live on the same host filesystem, so a run that fills
    the disk does not merely fail itself: Postgres stops being able to write and
    every other job, every schedule and every login fails with it. Failing one
    job early is the cheap outcome.

    ponytail: one flat threshold rather than a per-job size estimate — the row
    count is not knowable before the run, and the point is only to leave
    Postgres room to breathe.
    """
    settings = get_settings()
    os.makedirs(settings.storage_dir, exist_ok=True)
    free = shutil.disk_usage(settings.storage_dir).free
    if free < settings.min_free_disk_gb * 1024**3:
        raise RuntimeError(
            f"refusing to start: only {free / 1024**3:.1f} GB free on "
            f"{settings.storage_dir}, minimum is {settings.min_free_disk_gb} GB"
        )


def _send_alert_if_scheduled(conn, job: dict, error_message: str) -> None:
    """Send alert if this job is from a schedule."""
    # `or ""` rather than a .get default: created_by is NULL for every job
    # created through the UI, and .get returns that None rather than the default.
    # This raised AttributeError inside _mark_failed's `suppress(Exception)`,
    # which swallowed it — so the very jobs the net exists for stayed `queued`
    # forever with no error and no events.
    created_by = job.get("created_by") or ""
    if not created_by.startswith("schedule:"):
        return

    try:
        schedule_id = int(created_by.split(":")[1])
        result = (
            conn.execute(
                text("SELECT id, name, alert_recipients FROM schedules WHERE id = :id"),
                {"id": schedule_id},
            )
            .mappings()
            .first()
        )
        if result and result["alert_recipients"]:
            send_failure_alert(
                result["alert_recipients"],
                result["name"],
                job["id"],
                error_message,
            )
    except Exception as exc:
        # suppress: alerting failure shouldn't affect job failure handling
        from app.logging_config import get_logger

        log = get_logger("logvault.worker.tasks")
        log.exception("alert.error", exc_info=exc)


def _mark_failed(db, job_id: int, exc: BaseException) -> None:
    """Surface a failure that happened before the runner could report one itself.

    ``run_extraction`` and ``run_rollup`` record their own errors, but anything
    that goes wrong *before* they start — a bad import, an unreachable database,
    a worker killed mid-dispatch — used to leave the row sitting in ``queued``
    with an empty error and no events, which reads in the UI as a job that is
    merely slow. It would wait there forever.
    """
    # suppress is best-effort by design: if this fails too (DB down), there is
    # nothing further to try, and the original exception still reaches Celery.
    with contextlib.suppress(Exception), db.engine().begin() as conn:
        # Only claim jobs the runner never got to. A job it already moved to
        # paused/canceled/failed/completed has a better story than this one.
        if db.current_status(conn, job_id) in ("queued", "running"):
            job = db.load(conn, db.jobs, job_id)
            db.update_job(
                conn,
                job_id,
                status="failed",
                error_message=f"worker: {exc}",
                finished_at=datetime.now(UTC),
            )
            db.add_event(conn, job_id, f"Failed before starting: {exc}", level="error")
            _send_alert_if_scheduled(conn, job, str(exc))


@celery.task(name="logvault.run_job")
def run_job(job_id: int) -> None:
    """Run (or resume) a job. The API dispatches this by name.

    A job whose `rollup_of` is set merges other jobs' distinct-value stores
    instead of querying Last9 — same lifecycle, different source.
    """
    # Imported before the try so the failure handler is usable even when the
    # imports below are what break.
    from app import db

    try:
        from app.rollup import run_rollup
        from app.runner import run_extraction

        _require_disk_space()

        with db.engine().begin() as conn:
            job = db.load(conn, db.jobs, job_id)
            is_rollup = bool(job and job["rollup_of"])

        if is_rollup:
            run_rollup(job_id)
        else:
            run_extraction(job_id)
    except Exception as exc:
        _mark_failed(db, job_id, exc)
        raise  # let Celery record the task failure too
