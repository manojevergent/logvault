"""Celery tasks.

Phase 1: a single `ping` health task. Extraction tasks land in Phase 4.
"""

from __future__ import annotations

import contextlib
import json
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


def _as_dict(value: object) -> dict:
    """JSON column value as a dict, whichever driver decoded it.

    The raw SELECT below bypasses SQLAlchemy's JSON result processor, and
    drivers differ: some return a dict, others the stored text. A string here
    used to turn the customer lookup into an AttributeError, which the caller
    suppresses — so alerts silently stopped instead of failing loudly.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        with contextlib.suppress(Exception):
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
    return {}


def _as_list(value: object) -> list[str]:
    """JSON list column from a raw SELECT, whichever driver decoded it."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value:
        with contextlib.suppress(Exception):
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
    return []


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
                text(
                    "SELECT id, name, alert_recipients, filter_spec "
                    "FROM schedules WHERE id = :id"
                ),
                {"id": schedule_id},
            )
            .mappings()
            .first()
        )
        recipients = _as_list(result.get("alert_recipients")) if result else []
        if result and recipients:
            spec = _as_dict(result.get("filter_spec"))
            customer = str(spec.get("customer") or "").strip()
            if not customer:
                job_spec = _as_dict(job.get("filter_spec"))
                customer = str(job_spec.get("customer") or "").strip()
            send_failure_alert(
                recipients,
                result["name"],
                job["id"],
                error_message,
                customer,
            )
    except Exception as exc:
        # suppress: alerting failure shouldn't affect job failure handling
        from app.logging_config import get_logger

        log = get_logger("logvault.worker.tasks")
        log.exception("alert.error", exc_info=exc)


def _send_schedule_anomaly_if_needed(job_id: int) -> None:
    """Evaluate and send the per-schedule anomaly alerts after completion.

    The event marker makes this idempotent across Celery redeliveries. The
    notification itself runs after the transaction so a slow SMTP server cannot
    hold a database transaction open.
    """
    from app import db
    from app.notifications import send_anomaly_alert
    from app.schedule_alerts import evaluate_anomaly

    send_payload: dict | None = None
    try:
        with db.engine().begin() as conn:
            job = db.load(conn, db.jobs, job_id)
            if not job or job.get("status") != "completed":
                return
            created_by = str(job.get("created_by") or "")
            if not created_by.startswith("schedule:"):
                return
            schedule_id = int(created_by.split(":", 1)[1])
            sched = (
                conn.execute(
                    text(
                        "SELECT id, name, alert_recipients, alert_on_row_drop, "
                        "row_drop_threshold_pct, alert_on_unmatched, unmatched_threshold, "
                        "filter_spec FROM schedules WHERE id = :id"
                    ),
                    {"id": schedule_id},
                )
                .mappings()
                .first()
            )
            if not sched:
                return

            already = conn.execute(
                text(
                    "SELECT 1 FROM job_events "
                    "WHERE job_id = :id AND message LIKE 'Anomaly detected%' LIMIT 1"
                ),
                {"id": job_id},
            ).first()
            if already:
                return

            agg = _as_dict(job.get("aggregation_result"))
            current_rows = int(job.get("rows_written") or 0)
            previous_rows = conn.execute(
                text(
                    "SELECT rows_written FROM jobs "
                    "WHERE created_by = :owner AND status = 'completed' "
                    "AND id <> :id AND start_epoch < :start AND rows_written > 0 "
                    "ORDER BY start_epoch DESC, id DESC LIMIT 1"
                ),
                {
                    "owner": created_by,
                    "id": job_id,
                    "start": int(job.get("start_epoch") or 0),
                },
            ).scalar()

            evaluation = evaluate_anomaly(
                current_rows=current_rows,
                previous_rows=previous_rows,
                rows_matched=agg.get("rows_matched"),
                rows_unmatched=agg.get("rows_unmatched"),
                alert_on_row_drop=bool(sched.get("alert_on_row_drop")),
                row_drop_threshold_pct=int(sched.get("row_drop_threshold_pct") or 20),
                alert_on_unmatched=bool(sched.get("alert_on_unmatched")),
                unmatched_threshold=int(sched.get("unmatched_threshold") or 100),
            )
            if not evaluation.reasons:
                return

            db.add_event(
                conn,
                job_id,
                "Anomaly detected: " + "; ".join(evaluation.reasons),
                level="warn",
            )
            spec = _as_dict(sched.get("filter_spec"))
            customer = str(spec.get("customer") or "").strip()
            if not customer:
                customer = str(_as_dict(job.get("filter_spec")).get("customer") or "").strip()
            send_payload = {
                "recipients": _as_list(sched.get("alert_recipients")),
                "schedule_name": sched["name"],
                "job_id": job_id,
                "customer": customer,
                "reasons": evaluation.reasons,
                "current_rows": evaluation.current_rows,
                "previous_rows": evaluation.previous_rows,
                "drop_pct": evaluation.drop_pct,
                "rows_unmatched": evaluation.rows_unmatched,
                "parsed_rows": evaluation.parsed_rows,
                "unmatched_pct": evaluation.unmatched_pct,
                "row_drop_threshold_pct": int(sched.get("row_drop_threshold_pct") or 20),
                "unmatched_threshold": int(sched.get("unmatched_threshold") or 100),
            }
    except Exception as exc:
        # Alerting must never change the outcome of an already completed job.
        from app.logging_config import get_logger

        get_logger("logvault.worker.tasks").exception("schedule_anomaly.error", exc_info=exc)
        return

    if send_payload is not None:
        try:
            send_anomaly_alert(**send_payload)
        except Exception as exc:
            from app.logging_config import get_logger

            get_logger("logvault.worker.tasks").exception(
                "schedule_anomaly.send_failed", exc_info=exc
            )


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
        # Only jobs the runner never got to. "running" is deliberately excluded:
        # a live worker owns that row, and a failed duplicate delivery used to be
        # able to mark a healthy job failed. Stale running rows are the
        # reconciler's job, not this fallback's.
        if db.current_status(conn, job_id) == "queued":
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
    from celery import current_task

    from app import db

    # True when the broker handed this message to us again because the previous
    # worker died holding it. Only then may the runner take over a job row that
    # still says `running`; anything else would risk two workers on one file.
    # Guarded: outside a worker (direct calls, tests) there is no current task.
    try:
        redelivered = bool(current_task.request.redelivered)
    except Exception:  # noqa: BLE001 - no task context means "first delivery"
        redelivered = False

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
            run_extraction(job_id, reclaim=redelivered)
        _send_schedule_anomaly_if_needed(job_id)
    except Exception as exc:
        _mark_failed(db, job_id, exc)
        raise  # let Celery record the task failure too


@celery.task(name="logvault.upload_job_s3")
def upload_job_s3(job_id: int) -> None:
    """Retry S3 delivery for a completed job without re-querying Last9."""
    from app import db
    from app.s3 import upload_job_artifacts

    eng = db.engine()
    with eng.begin() as conn:
        job = db.load(conn, db.jobs, job_id)
        if job is None:
            return
        if not job.get("s3_profile_id"):
            db.update_job(conn, job_id, s3_error="no S3 destination on this job")
            db.add_event(conn, job_id, "S3 upload failed: no destination", level="warn")
            return
        profile = db.load(conn, db.s3_profiles, job["s3_profile_id"])
        if profile is None:
            message = "S3 profile no longer exists"
            db.update_job(conn, job_id, s3_error=message)
            db.add_event(conn, job_id, f"S3 upload failed: {message}", level="warn")
            _send_alert_if_scheduled(conn, job, f"S3 upload failed: {message}")
            return
        db.add_event(conn, job_id, "S3 upload retry started")
        job = dict(job)
        profile = dict(profile)

    try:
        uris, errors = upload_job_artifacts(job, profile)
        error = "; ".join(errors) if errors else None
        if not uris and not error:
            error = "no final artifacts found to upload"
    except Exception as exc:  # noqa: BLE001
        uris, error = {}, str(exc)

    with eng.begin() as conn:
        db.update_job(
            conn,
            job_id,
            s3_uri=uris.get("raw"),
            s3_summary_uri=uris.get("summary"),
            s3_counts_uri=uris.get("counts"),
            s3_error=error,
            s3_uploaded_at=datetime.now(UTC) if uris else None,
        )
        if uris:
            db.add_event(conn, job_id, "S3 upload complete: " + ", ".join(uris.values()))
        if error:
            db.add_event(conn, job_id, f"S3 upload failed: {error}", level="warn")
            _send_alert_if_scheduled(conn, job, f"S3 upload failed: {error}")
