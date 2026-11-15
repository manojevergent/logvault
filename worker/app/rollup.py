"""Month-end rollup: merge the distinct-value stores of many completed jobs
into one, and report true cross-period unique counts.

Why this exists: unique counts do not add. A customer seen on 10 days appears in
10 daily jobs, so summing their daily counts reports them 10 times. The only way
to a correct monthly number is to union the underlying values — which is exactly
what each job left on disk (see last9/distinct_store.py).

A rollup reuses the job lifecycle (status, events, progress, download, retention)
rather than inventing a parallel one; the only difference is where its input
comes from. `jobs.rollup_of` marks it.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import select, text

from app import db, fenced
from app.config import get_settings
from app.last9 import AggregationSpec, Aggregator, DistinctStore, store_path
from app.notifications import send_failure_alert
from app.runner import customer_dir, export_entry_name, summary_path, value_counts_path


def _now() -> datetime:
    return datetime.now(UTC)


def _zip_file(file_path: str | None, arcname: str | None = None) -> str | None:
    """Compress a file in-place; return zipped path or None. ponytail: delete raw after zipping."""
    if not file_path or not os.path.exists(file_path):
        return file_path

    settings = get_settings()
    if not settings.zip_exports:
        return file_path

    zip_path = f"{file_path}.zip"
    entry_name = arcname or os.path.basename(file_path)
    # compresslevel=3 cuts zipping CPU time by ~70% while keeping ~92% compression ratio
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
        zf.write(file_path, arcname=entry_name)
    os.remove(file_path)
    return zip_path


def find_source_jobs(conn, schedule_id: int, start_epoch: int, end_epoch: int) -> list[dict]:
    """Completed jobs this schedule produced whose window starts in [start, end)."""
    rows = (
        conn.execute(
            select(
                db.jobs.c.id,
                db.jobs.c.status,
                db.jobs.c.start_epoch,
                db.jobs.c.end_epoch,
                db.jobs.c.filter_spec,
                db.jobs.c.output_file_path,
            )
            .where(db.jobs.c.created_by == f"schedule:{schedule_id}")
            .where(db.jobs.c.start_epoch >= start_epoch)
            .where(db.jobs.c.start_epoch < end_epoch)
            .order_by(db.jobs.c.start_epoch)
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def run_rollup(job_id: int) -> None:
    eng = db.engine()
    settings = get_settings()

    with eng.begin() as conn:
        job = db.load(conn, db.jobs, job_id)
        if job is None:
            return
        job = dict(job)
        # Atomic claim, same ownership model as extraction. Two workers can no
        # longer run the same rollup, and a duplicate delivery bows out instead
        # of marking a live job running again.
        lease_token = db.claim_job(
            conn,
            job_id,
            owner_id="rollup",
            started_at=_now(),
            error_message=None,
        )
        if not lease_token:
            return
        db.add_event(conn, job_id, "Rollup started")

    def save(conn, _job_id, **values):
        """Fenced write: a superseded rollup cannot overwrite newer state."""
        return fenced.fenced_update(conn, job_id, lease_token, **values)

    customer = (job["filter_spec"] or {}).get("customer")
    spec_json = job["rollup_of"] or {}
    schedule_id = spec_json.get("schedule_id")
    agg_config = (job["filter_spec"] or {}).get("aggregation") or {}

    if not schedule_id or not agg_config.get("regex"):
        error_msg = "rollup needs a schedule_id and an aggregation spec"
        with eng.begin() as conn:
            applied = save(
                conn,
                job_id,
                status="failed",
                error_message=error_msg,
                finished_at=_now(),
            )
            # F-02a-1: the fenced write is the authority on ownership. A refused
            # write means another worker owns this job, so it must not inherit
            # this worker's failure event or a false alert.
            if applied:
                db.add_event(conn, job_id, "Failed: incomplete rollup spec", level="error")
                # Try to alert the schedule owner
                try:
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
                            job_id,
                            error_msg,
                        )
                except Exception:
                    pass
        return

    with eng.begin() as conn:
        sources = find_source_jobs(conn, schedule_id, job["start_epoch"], job["end_epoch"])

    usable, skipped = [], []
    for s in sources:
        path = store_path(settings.storage_dir, s["id"])
        if s["status"] != "completed":
            skipped.append((s, f"status={s['status']}"))
        elif not os.path.exists(path):
            # Most likely retention deleted it before the rollup ran.
            skipped.append((s, "distinct-value store missing"))
        else:
            usable.append((s, path))

    dest = DistinctStore(store_path(settings.storage_dir, job_id), fresh=True)
    aggregator = Aggregator(
        AggregationSpec(
            regex=agg_config["regex"],
            group_by=agg_config.get("group_by", []),
            unique_fields=agg_config.get("unique_fields", []),
        ),
        dest,
    )

    try:
        for i, (s, path) in enumerate(usable, start=1):
            dest.merge_from(path)
            with eng.begin() as conn:
                save(
                    conn,
                    job_id,
                    completed_chunks=i,
                    total_chunks=len(usable),
                    aggregation_result=aggregator.snapshot(),
                )
                db.add_event(conn, job_id, f"Merged job {s['id']} ({i}/{len(usable)})")

        summary = summary_path(job_id, customer)
        aggregator.write_summary_csv(summary)
        counts = value_counts_path(job_id, customer)
        aggregator.write_value_counts_csv(counts)
        combined = _concat_raw(job_id, customer, usable)
        snap = aggregator.snapshot()

        # Compress outputs to save space
        label = (job["rollup_of"] or {}).get("label") or (job["filter_spec"] or {}).get("label")
        start_epoch = job["start_epoch"]
        end_epoch = job["end_epoch"]
        fmt = job["output_format"]
        raw_arcname = export_entry_name(job_id, label, start_epoch, end_epoch, "raw", fmt)
        summary_arcname = export_entry_name(job_id, label, start_epoch, end_epoch, "summary", "csv")
        counts_arcname = export_entry_name(job_id, label, start_epoch, end_epoch, "counts", "csv")

        summary = _zip_file(summary, arcname=summary_arcname)
        counts = _zip_file(counts, arcname=counts_arcname)
        combined = _zip_file(combined, arcname=raw_arcname)
    except Exception as exc:  # noqa: BLE001 - record any failure on the job
        dest.close()
        error_msg = str(exc)
        with eng.begin() as conn:
            job = db.load(conn, db.jobs, job_id)
            applied = save(
                conn, job_id, status="failed", error_message=error_msg, finished_at=_now()
            )
            # F-02a-1: only the owner may narrate the outcome. If the fenced
            # write was refused, the new owner will report its own result; a
            # "Failed" event or a failure email from this worker would be false.
            if applied:
                db.add_event(conn, job_id, f"Failed: {exc}", level="error")
                # Try to alert the schedule owner
                if job:
                    try:
                        result = (
                            conn.execute(
                                text(
                                    "SELECT id, name, alert_recipients "
                                    "FROM schedules WHERE id = :id"
                                ),
                                {"id": schedule_id},
                            )
                            .mappings()
                            .first()
                        )
                        if result and result["alert_recipients"]:
                            send_failure_alert(
                                result["alert_recipients"],
                                result["name"],
                                job_id,
                                error_msg,
                            )
                    except Exception:
                        pass
        return

    with eng.begin() as conn:
        msg = (
            f"Rollup completed — {snap['total_groups']} group(s) across "
            f"{len(usable)} run(s), {snap['rows_matched']} matching row(s)"
        )
        if skipped:
            msg += f"; {len(skipped)} run(s) skipped — counts are incomplete"
        applied = save(
            conn,
            job_id,
            status="completed",
            finished_at=_now(),
            aggregation_result=snap,
            summary_file_path=summary,
            counts_file_path=counts,
            output_file_path=combined,
            rows_written=snap["rows_matched"],
            completed_chunks=len(usable),
            total_chunks=len(usable),
        )
        # F-02a-1: the fenced write is the authority on ownership. When it is
        # refused another worker owns this job and will publish its own result,
        # so announcing a completion (or the gaps) here would be false.
        if applied:
            # A gap must be loud: a rollup that silently drops a day looks clean
            # and under-reports, which is worse than one that says what it missed.
            for s, why in skipped:
                db.add_event(
                    conn,
                    job_id,
                    f"Skipped job {s['id']} ({_day(s['start_epoch'])}): {why}",
                    level="warn",
                )
            db.add_event(conn, job_id, msg, level="warn" if skipped else "info")

    dest.close()


@contextmanager
def _open_export(path: str):
    """A binary reader over a day's rows, compressed or not.

    Exports are zipped the moment a day completes (`zip_exports`), so in
    practice every source path here ends in `.zip`. Opening those bytes directly
    is what turned a month-end rollup into a `.csv` holding concatenated ZIP
    containers, each missing a leading line-worth of bytes stripped as a header.
    """
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            members = zf.namelist()
            if not members:
                raise ValueError(f"empty archive, nothing to merge: {path}")
            with zf.open(members[0]) as fh:
                yield fh
    else:
        with open(path, "rb") as fh:
            yield fh


def _concat_raw(job_id: int, customer: str | None, usable: list) -> str | None:
    """Every day's rows in one file, header written once.

    Copied rather than re-queried: each day's extract is already on disk and is
    the authoritative record of that day. Streamed with copyfileobj so a month
    of large extracts is bounded by disk, not memory.

    Days whose raw file has aged out of retention are skipped — the aggregates
    still cover them, because those come from the value stores.
    """
    sources = []
    for s, _store in usable:
        path = s.get("output_file_path")
        if path and os.path.exists(path):
            sources.append((s["id"], path))
    if not sources:
        return None

    dest = os.path.join(customer_dir(customer), f"job_{job_id}.csv")
    with open(dest, "wb") as out:
        for i, (_jid, path) in enumerate(sources):
            with _open_export(path) as fh:
                header = fh.readline()
                if i == 0:
                    out.write(header)
                # Subsequent headers dropped: one file, one header row.
                shutil.copyfileobj(fh, out, length=1024 * 1024)
    return dest


def _day(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d")
