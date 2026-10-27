"""Periodic beat tasks: run due schedules (F1) and prune expired exports (F4).

ponytail: schedules are interval-based (every N seconds), checked by a single
60s beat tick — no cron parser, no DB-backed beat scheduler. For multi-worker
prod, run one dedicated beat process; here beat is embedded (`-B`).
"""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import func, select

from app import db
from app.celery_app import celery
from app.config import get_settings
from app.last9 import previous_calendar_day_window, store_path

_DAY = 86400

# A schedule re-enabled after a long outage must not queue hundreds of
# multi-hour jobs in one tick. The newest days are kept: they are the ones still
# inside Last9's retention, and the ones anyone is waiting on.
MAX_BACKFILL_DAYS = 14

# Read by the API's /health/ops. Without it a dead worker is invisible: schedules
# simply stop firing and nobody is told until a report never arrives.
BEAT_KEY = "logvault:beat"


@lru_cache
def _redis():
    import redis

    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def _beat() -> None:
    """Record that the beat tick completed.

    Deliberately written at the END of the scan, not the start: if scanning
    raises, schedules are not running, and the heartbeat going stale is the
    correct report. The TTL is longer than the tick so a single blip does not
    look like a death.
    """
    # suppress: a heartbeat that cannot be written must never break the tick it
    # rides on — losing schedules to protect a health signal is backwards.
    with contextlib.suppress(Exception):
        _redis().set(BEAT_KEY, datetime.now(UTC).isoformat(), ex=600)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _owed_windows(s, now: datetime) -> list[tuple[int, int]]:
    """Every ``[start, end)`` window this schedule still owes, oldest first.

    A calendar-day schedule owes one window per completed UTC day since the day
    it last covered. Firing once per tick regardless of how many days elapsed is
    what silently forfeited days whenever the worker was down over a weekend:
    ``last_run_at`` jumped to the restart and the intervening days were never
    extracted, with no event and no alert.

    An interval schedule owes at most one window — "the last N seconds" has no
    fixed range to replay, so a missed tick is simply late, not lost.
    """
    last = _aware(s["last_run_at"])
    now_epoch = int(now.timestamp())

    if not s["calendar_day"]:
        if last is not None and (now - last).total_seconds() < s["interval_seconds"]:
            return []
        return [(now_epoch - s["lookback_seconds"], now_epoch)]

    # UTC explicitly: the boundary must match the zone the logs themselves are
    # timestamped in, not the one users read in.
    newest_start, newest_end = previous_calendar_day_window(now_epoch, "UTC")
    if last is None:
        return [(newest_start, newest_end)]

    covered_start, _ = previous_calendar_day_window(int(last.timestamp()), "UTC")
    owed = [
        (start, start + _DAY) for start in range(covered_start + _DAY, newest_start + _DAY, _DAY)
    ]
    return owed[-MAX_BACKFILL_DAYS:]


def _already_extracted(conn, owner: str, start_epoch: int) -> bool:
    """Whether this schedule already has a job for this exact window.

    Backfill replays past days, so it has to be idempotent: a crash between the
    insert and the ``last_run_at`` update, or a second beat process, must not
    extract the same day twice.
    """
    return (
        conn.execute(
            select(db.jobs.c.id)
            .where(db.jobs.c.created_by == owner, db.jobs.c.start_epoch == start_epoch)
            .limit(1)
        ).first()
        is not None
    )


@celery.task(name="logvault.scan_schedules")
def scan_schedules() -> list[int]:
    from app.tasks import run_job

    now = datetime.now(UTC)
    eng = db.engine()
    created: list[int] = []
    with eng.begin() as conn:
        rows = conn.execute(select(db.schedules).where(db.schedules.c.enabled)).mappings().all()
        for s in rows:
            windows = _owed_windows(s, now)
            if not windows:
                continue
            # The schedule's name labels the run, so its downloads are named for
            # the search rather than a job number.
            filter_spec = dict(s["filter_spec"] or {})
            filter_spec.setdefault("label", s["name"])
            owner = f"schedule:{s['id']}"
            for start, end in windows:
                if _already_extracted(conn, owner, start):
                    continue
                job_id = conn.execute(
                    db.jobs.insert()
                    .values(
                        status="queued",
                        region_code=s["region_code"],
                        index_target_id=s["index_target_id"],
                        credential_id=s["credential_id"],
                        start_epoch=start,
                        end_epoch=end,
                        chunk_hours=s["chunk_hours"],
                        id_batch_size=s["id_batch_size"],
                        filter_spec=filter_spec,
                        output_format=s["output_format"],
                        is_preview=False,
                        rows_written=0,
                        total_chunks=0,
                        completed_chunks=0,
                        created_by=owner,
                    )
                    .returning(db.jobs.c.id)
                ).scalar_one()
                if len(windows) > 1:
                    day = datetime.fromtimestamp(start, UTC).strftime("%Y-%m-%d")
                    db.add_event(
                        conn,
                        job_id,
                        f"Backfill for {day} — this schedule missed its run",
                        level="warn",
                    )
                created.append(job_id)
            conn.execute(
                db.schedules.update().where(db.schedules.c.id == s["id"]).values(last_run_at=now)
            )
    dispatched: list[int] = []
    for jid in created:
        # Per job: one unreachable-broker failure must not strand the whole
        # backfill. A job that fails to dispatch stays `queued` in the database
        # with its window recorded, so it is still visible and re-runnable.
        try:
            run_job.delay(jid)
            dispatched.append(jid)
        except Exception:  # noqa: BLE001 - broker errors are not worth typing out
            continue
    _beat()
    return dispatched


@celery.task(name="logvault.reap_stale_jobs")
def reap_stale_jobs() -> list[int]:
    """Fail `running` jobs that have stopped reporting.

    `task_acks_late` + `task_reject_on_worker_lost` only cover a worker that
    dies cleanly enough for the broker to notice. An OOM-kill, a wedged socket
    or a `docker kill` raises nothing anywhere: the row stays `running` for
    good, no alert fires, and in the UI it is indistinguishable from a job that
    is merely slow.

    Progress is judged by the job's last event rather than `updated_at` — the
    worker writes through SQLAlchemy Core, which does not fire the ORM's
    `onupdate`, so `updated_at` does not move during a run.
    """
    from app.tasks import _send_alert_if_scheduled

    settings = get_settings()
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=settings.stale_job_minutes)
    message = (
        f"No progress for over {settings.stale_job_minutes} minutes — "
        "worker presumed dead. Retry to resume from the last checkpoint."
    )

    last_event = (
        select(db.job_events.c.job_id, func.max(db.job_events.c.ts).label("ts"))
        .group_by(db.job_events.c.job_id)
        .subquery()
    )
    reaped: list[int] = []
    with db.engine().begin() as conn:
        rows = (
            conn.execute(
                select(db.jobs.c.id, db.jobs.c.started_at, last_event.c.ts)
                .select_from(db.jobs.outerjoin(last_event, last_event.c.job_id == db.jobs.c.id))
                .where(db.jobs.c.status == "running")
            )
            .mappings()
            .all()
        )
        for j in rows:
            last_seen = _aware(j["ts"]) or _aware(j["started_at"])
            # No timestamp at all is no evidence of death: leave it alone rather
            # than kill a job on a guess.
            if last_seen is None or last_seen > cutoff:
                continue
            job = db.load(conn, db.jobs, j["id"])
            db.update_job(
                conn,
                j["id"],
                status="failed",
                error_message=message,
                finished_at=now,
            )
            db.add_event(conn, j["id"], message, level="error")
            _send_alert_if_scheduled(conn, job, message)
            reaped.append(j["id"])
    return reaped


@celery.task(name="logvault.cleanup_exports")
def cleanup_exports() -> int:
    settings = get_settings()
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=settings.export_retention_days)
    # A distinct-value store is the input to the month-end rollup, so it has to
    # outlive the raw extract: deleting day 1 on a 30-day clock would silently
    # under-count the month that is still being rolled up. Held for a full extra
    # month past the raw retention, then dropped (they are never downloaded —
    # only merged, and the summary CSV carries the numbers).
    store_cutoff = now - timedelta(days=settings.export_retention_days + 31)
    eng = db.engine()
    removed = 0
    with eng.begin() as conn:
        # Bounded in SQL rather than in Python: this used to load every finished
        # job ever and then stat two paths per row — tens of thousands of
        # filesystem calls on a bind-mounted volume, inside an open write
        # transaction. `store_cutoff` is the older of the two, so it is the one
        # that decides which rows can still be interesting.
        rows = (
            conn.execute(
                select(
                    db.jobs.c.id,
                    db.jobs.c.output_file_path,
                    db.jobs.c.summary_file_path,
                    db.jobs.c.counts_file_path,
                    db.jobs.c.finished_at,
                ).where(
                    db.jobs.c.finished_at.is_not(None),
                    db.jobs.c.finished_at < max(cutoff, store_cutoff),
                )
            )
            .mappings()
            .all()
        )
        for j in rows:
            fin = _aware(j["finished_at"])
            if not fin:
                continue
            if fin < cutoff:
                for path_key in ("output_file_path", "summary_file_path", "counts_file_path"):
                    p = j[path_key]
                    if p and os.path.exists(p):
                        with contextlib.suppress(OSError):
                            os.remove(p)
                        removed += 1
                if j["output_file_path"] or j["summary_file_path"] or j["counts_file_path"]:
                    conn.execute(
                        db.jobs.update()
                        .where(db.jobs.c.id == j["id"])
                        .values(
                            output_file_path=None,
                            summary_file_path=None,
                            counts_file_path=None,
                        )
                    )
                    db.add_event(conn, j["id"], "Output files expired and deleted", level="warn")

            store = store_path(settings.storage_dir, j["id"])
            if fin < store_cutoff and os.path.exists(store):
                with contextlib.suppress(OSError):
                    os.remove(store)
                db.add_event(conn, j["id"], "Distinct-value store expired", level="warn")
                removed += 1

        # Low-disk-space emergency purge: if free disk drops below threshold, purge oldest exports
        try:
            stat = os.statvfs(settings.storage_dir)
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
            if free_gb < settings.min_free_disk_gb:
                oldest_jobs = (
                    conn.execute(
                        select(
                            db.jobs.c.id,
                            db.jobs.c.output_file_path,
                            db.jobs.c.summary_file_path,
                            db.jobs.c.counts_file_path,
                        )
                        .where(
                            db.jobs.c.status == "completed",
                            db.jobs.c.output_file_path.is_not(None),
                        )
                        .order_by(db.jobs.c.finished_at.asc())
                        .limit(20)
                    )
                    .mappings()
                    .all()
                )
                for oj in oldest_jobs:
                    for p in [
                        oj["output_file_path"],
                        oj["summary_file_path"],
                        oj["counts_file_path"],
                    ]:
                        if p and os.path.exists(p):
                            with contextlib.suppress(OSError):
                                os.remove(p)
                    conn.execute(
                        db.jobs.update()
                        .where(db.jobs.c.id == oj["id"])
                        .values(
                            output_file_path=None, summary_file_path=None, counts_file_path=None
                        )
                    )
                    db.add_event(conn, oj["id"], "Purged early due to low disk space", level="warn")
                    removed += 1
        except Exception:  # noqa: BLE001
            pass
    return removed
