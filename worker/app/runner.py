"""Job execution: stream Last9 logs to a CSV, checkpoint per chunk, honor
pause/cancel. Never holds results in memory — rows are written as they arrive.

Resume is exact: each checkpoint records the CSV byte offset, so a mid-chunk
crash truncates the partial chunk and replays it (non-overlapping windows => no
duplicate rows).
"""

from __future__ import annotations

import csv
import dataclasses
import json
import os
import re
import time
import zipfile
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text

from app import crypto, db
from app.config import get_settings
from app.last9 import (
    AggregationError,
    AggregationSpec,
    Aggregator,
    Checkpoint,
    DistinctStore,
    ExtractionSpec,
    FormatMatcher,
    Last9Client,
    Last9Error,
    LogFormat,
    TokenManager,
    TokenSet,
    count_chunks,
    format_log_timestamp,
    iter_extraction,
    parse_bq_row,
    store_path,
)
from app.notifications import send_failure_alert


class _Stopped(Exception):
    def __init__(self, status: str) -> None:
        self.status = status  # "paused" or "canceled"


def _now() -> datetime:
    return datetime.now(UTC)


def _send_alert_if_scheduled(conn, job: dict, error_message: str) -> None:
    """Send alert if this job is from a schedule."""
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
    except Exception:
        # suppress: alerting failure shouldn't affect job failure handling
        pass


# A customer name is free text that becomes a directory, so it has to be reduced
# to exactly one path segment. Anything else — a slash, "..", a drive letter —
# would let a job write outside the export root.
_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _timeframe(start_epoch: int, end_epoch: int) -> str:
    start = datetime.fromtimestamp(start_epoch, UTC)
    last = datetime.fromtimestamp(max(start_epoch, end_epoch - 1), UTC)
    whole_day = end_epoch - start_epoch == 86400 and (start.hour, start.minute, start.second) == (
        0,
        0,
        0,
    )
    if whole_day:
        return start.strftime("%Y-%m-%d")
    if start.date() == last.date():
        return f"{start:%Y-%m-%d_%H%M}-{last:%H%M}"
    return f"{start:%Y-%m-%d_%H%M}-{last:%Y-%m-%d_%H%M}"


def export_entry_name(
    job_id: int,
    label: str | None,
    start_epoch: int,
    end_epoch: int,
    kind: str = "raw",
    fmt: str = "csv",
) -> str:
    """Format the file name inside the .zip archive to match the descriptive download name."""
    if label:
        stem = _UNSAFE_PATH_CHARS.sub("_", label).strip("_") or f"job_{job_id}"
        stem = f"{stem}_{job_id}"
    else:
        stem = f"logvault_job_{job_id}"
    name = f"{stem}_{_timeframe(start_epoch, end_epoch)}"
    if kind in ("summary", "counts"):
        return f"{name}_{kind}.csv"
    ext = "jsonl" if fmt == "jsonl" else "csv"
    return f"{name}.{ext}"


def customer_dir(customer: str | None) -> str:
    """The export directory for a customer, created on demand.

    Falls back to the export root when a job has no customer, so output never
    disappears into a folder nobody expects.
    """
    root = get_settings().storage_dir
    if not customer:
        return root
    segment = _UNSAFE_PATH_CHARS.sub("_", customer).strip("._-")
    if not segment:
        return root
    path = os.path.join(root, segment)
    os.makedirs(path, exist_ok=True)
    return path


def output_path(job_id: int, fmt: str = "csv", customer: str | None = None) -> str:
    if fmt == "jsonl":
        ext = "jsonl"
    elif fmt == "bigquery":
        ext = "bq.csv"
    else:
        ext = "csv"
    return os.path.join(customer_dir(customer), f"job_{job_id}.{ext}")


def summary_path(job_id: int, customer: str | None = None) -> str:
    """Full per-group unique counts. Separate from the raw extract because a
    summary-only job (skip_raw_output) still has one, and because it stays small
    enough to open even when the raw extract is hundreds of GB."""
    return os.path.join(customer_dir(customer), f"job_{job_id}.summary.csv")


def value_counts_path(job_id: int, customer: str | None = None) -> str:
    """Per-value occurrence counts — the pivot-table view, already pivoted."""
    return os.path.join(customer_dir(customer), f"job_{job_id}.counts.csv")


def _zip_file(file_path: str, arcname: str | None = None) -> str:
    """Compress a file in-place; return zipped path. ponytail: delete raw after zipping."""
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


def run_extraction(job_id: int, *, reclaim: bool = False) -> None:
    eng = db.engine()

    with eng.begin() as conn:
        job = db.load(conn, db.jobs, job_id)
        if job is None:
            return
        cred = db.load(conn, db.last9_credentials, job["credential_id"])
        idx = db.load(conn, db.index_targets, job["index_target_id"])
        if cred is None or idx is None:
            error_msg = "missing credential/index"
            db.update_job(conn, job_id, status="failed", error_message=error_msg)
            _send_alert_if_scheduled(conn, job, error_msg)
            return
        # Claim before doing anything: the conditional UPDATE is what stops a
        # second worker joining a job already in flight, and what makes a cancel
        # or pause issued while the job was still queued actually stick.
        #
        # `reclaim` is passed only when Celery reports the message was
        # REDELIVERED, i.e. the previous worker died holding it. The row still
        # says `running`, so without this the new delivery bowed out and the job
        # idled until the reaper failed it an hour later. Requiring the
        # redelivery flag — rather than just a quiet job — means a live run can
        # never be taken over, even if it is stuck in a long retry chain.
        was_running = job["status"] == "running"
        reclaim_before = (
            _now() - timedelta(minutes=get_settings().stale_reclaim_minutes) if reclaim else None
        )
        if not db.claim_job(
            conn,
            job_id,
            started_at=_now(),
            error_message=None,
            reclaim_before=reclaim_before,
        ):
            return
        db.add_event(
            conn,
            job_id,
            "Resumed by a new worker after it went quiet" if was_running else "Job started",
        )
        job = dict(job)
        cred = dict(cred)
        idx = dict(idx)

    settings = get_settings()
    excel_escape = settings.excel_escape
    spec = ExtractionSpec(
        region=job["region_code"],
        index=idx["full_index_string"],
        start_epoch=job["start_epoch"],
        end_epoch=job["end_epoch"],
        phrases=(job["filter_spec"] or {}).get("phrases", [])
        + (job["filter_spec"] or {}).get("message_types", []),
        exact_phrases=(job["filter_spec"] or {}).get("exact_phrases", []),
        ids=(job["filter_spec"] or {}).get("ids", []),
        chunk_hours=job["chunk_hours"],
        id_batch_size=job["id_batch_size"],
    )

    fmt = job["output_format"] or "csv"
    is_preview = bool(job["is_preview"])
    if is_preview:
        # Filter test-run: only the first chunk, capped rows (see ROW_CAP below).
        spec.end_epoch = min(spec.end_epoch, spec.start_epoch + int(spec.chunk_hours * 3600))

    checkpoint_json = job["checkpoint"] or {}
    cp = Checkpoint.from_dict(checkpoint_json)
    file_offset = checkpoint_json.get("file_offset", 0)
    # Restore effective chunk_hours from the last checkpoint so adaptive sizing
    # survives pause/resume cycles.
    effective_chunk_hours = checkpoint_json.get("chunk_hours", spec.chunk_hours)
    spec.chunk_hours = effective_chunk_hours
    resuming = cp.completed_chunks > 0

    agg_config = (job["filter_spec"] or {}).get("aggregation")
    aggregator: Aggregator | None = None
    distinct_store: DistinctStore | None = None
    skip_raw_output = False
    if agg_config and agg_config.get("enabled"):
        skip_raw_output = bool(agg_config.get("skip_raw_output"))
        try:
            # Not resuming means starting the counts over, so drop any store left
            # behind by a previous attempt — otherwise its values would survive
            # into the new run and inflate every count.
            distinct_store = DistinctStore(
                store_path(settings.storage_dir, job_id), fresh=not resuming
            )
            # NOT `spec` — that name already holds the ExtractionSpec this
            # function needs afterwards for chunking.
            agg_spec = AggregationSpec(
                regex=agg_config.get("regex", ""),
                group_by=agg_config.get("group_by", []),
                unique_fields=agg_config.get("unique_fields", []),
                use_library=bool(agg_config.get("use_library")),
                raw_columns=agg_config.get("raw_columns", []),
                raw_column_defaults=agg_config.get("raw_column_defaults", {}),
                include_log_format=agg_config.get("include_log_format", True),
                include_message=agg_config.get("include_message", True),
                timestamp_column=agg_config.get("timestamp_column", "timestamp_utc"),
                column_labels=agg_config.get("column_labels", {}),
                # Deployment-wide switch: off = warehouse-ready plain values.
                excel_escape=settings.excel_escape,
            )
            matcher = None
            if agg_spec.use_library:
                # Read once per job: the library is small and static for a run,
                # and every row is matched against it.
                with eng.begin() as conn:
                    library = db.load_log_formats(conn)
                if not library:
                    raise AggregationError(
                        "no enabled log formats — add one under Log Formats, "
                        "or give this job its own parse pattern"
                    )
                matcher = FormatMatcher(
                    [
                        LogFormat(
                            name=f["name"],
                            regex=f["regex"],
                            hint=f["hint"] or None,
                            priority=f["priority"] if f["priority"] is not None else 100,
                        )
                        for f in library
                    ]
                )
            aggregator = Aggregator(agg_spec, distinct_store, matcher)
        except AggregationError as exc:
            if distinct_store is not None:
                distinct_store.close()
            with eng.begin() as conn:
                db.update_job(
                    conn,
                    job_id,
                    status="failed",
                    error_message=f"aggregation config: {exc}",
                    finished_at=_now(),
                )
                db.add_event(conn, job_id, f"Failed: aggregation config: {exc}", level="error")
            return

    customer = (job["filter_spec"] or {}).get("customer")
    path = (
        None if skip_raw_output else (job["output_file_path"] or output_path(job_id, fmt, customer))
    )
    # Chunks already done, plus an estimate of what is left at the size now in
    # use. Measuring the whole range at the restored (adapted) size counted work
    # already finished as though it still had to be done at the smaller size —
    # a job past halfway reported 14%.
    resume_from = cp.next_chunk_start if resuming and cp.next_chunk_start is not None else None
    total = cp.completed_chunks + count_chunks(
        resume_from if resume_from is not None else spec.start_epoch,
        spec.end_epoch,
        spec.chunk_hours,
    )

    with eng.begin() as conn:
        db.update_job(conn, job_id, total_chunks=total, output_file_path=path)

    http = httpx.Client(timeout=60.0)

    def on_rotate(ts: TokenSet) -> None:
        with eng.begin() as conn:
            conn.execute(
                db.last9_credentials.update()
                .where(db.last9_credentials.c.id == cred["id"])
                .values(
                    encrypted_access_token=crypto.encrypt(ts.access_token),
                    access_token_expires_at=ts.expires_at,
                    encrypted_refresh_token=crypto.encrypt(ts.refresh_token),
                    refresh_token_last4=ts.refresh_token[-4:],
                )
            )

    tokens = TokenManager(
        TokenSet(
            refresh_token=crypto.decrypt(cred["encrypted_refresh_token"]),
            access_token=(
                crypto.decrypt(cred["encrypted_access_token"])
                if cred["encrypted_access_token"]
                else None
            ),
            expires_at=cred["access_token_expires_at"],
        ),
        api_base=settings.last9_api_base,
        http=http,
        on_rotate=on_rotate,
    )
    client = Last9Client(
        token_manager=tokens, org_slug=cred["org_slug"], api_base=settings.last9_api_base, http=http
    )

    os.makedirs(settings.storage_dir, exist_ok=True)
    f = None
    csv_writer = None
    if path is not None:
        if resuming and os.path.exists(path):
            f = open(  # noqa: SIM115 - spans streaming loop
                path, "r+", newline="", encoding="utf-8"
            )
            f.seek(file_offset)
            f.truncate()
        else:
            f = open(path, "w", newline="", encoding="utf-8")  # noqa: SIM115 - spans streaming loop
            if fmt == "csv":
                # UTC, matching the zone the application writes its logs in, so
                # the column can be checked directly against the job's window.
                # When a parse pattern is configured its named groups become real
                # columns, so reaching a field never requires splitting the
                # message in Excel — Text-to-Columns re-parses the fragments and
                # turns a numeric id into 2.30702E+23 whatever the file said.
                ts_header = (
                    aggregator.timestamp_column if aggregator is not None else "timestamp_utc"
                )
                header = [ts_header]
                if aggregator is not None:
                    header += aggregator.parsed_field_labels
                if aggregator is None or aggregator.include_message:
                    header.append("message")
                csv.writer(f).writerow(header)
            elif fmt == "bigquery":
                csv.writer(f).writerow(
                    [
                        "bu_name",
                        "timestamp",
                        "session_token",
                        "sp_account_id",
                        "api_name",
                        "channel_partner_id",
                    ]
                )
            f.flush()
        csv_writer = csv.writer(f)

    PREVIEW_CAP = 20  # rows surfaced live in the UI
    ROW_CAP = 100  # total rows for a preview/test-run job
    preview_sample: list[dict] = []
    bq_unmatched = 0

    # A chunk can legitimately take hours: India/Frankfurt volumes reach millions
    # of rows per chunk and Last9's 502s add retry time. Progress used to be
    # recorded only when a chunk FINISHED, so `reap_stale_jobs` — which judges
    # liveness by the newest job event — declared a working job dead after 60
    # quiet minutes. This heartbeat keeps the event fresh (and the Live feed
    # visibly moving) while rows are still streaming.
    HEARTBEAT_SECONDS = 300

    def write_row(row) -> None:
        nonlocal bq_unmatched
        # Formatted once here rather than at each sink, so the file, the preview
        # and the UI all agree on what a row's time says. UTC — the zone the log
        # line was written in, and the zone the job's window is aligned to.
        ts = format_log_timestamp(row.timestamp, "UTC")
        # Matches, counts and returns the columns in one pass — see
        # Aggregator.process. Splitting it would run every regex twice per row
        # and double every per-format tally.
        parsed = aggregator.process(row.message) if aggregator is not None else None
        if f is not None:
            include_message = aggregator is None or aggregator.include_message
            if fmt == "jsonl":
                record = {"timestamp": ts}
                if aggregator is not None:
                    record.update(
                        dict(zip(aggregator.parsed_field_labels, parsed or [], strict=False))
                    )
                if include_message:
                    record["message"] = row.message
                f.write(json.dumps(record) + "\n")
            elif fmt == "bigquery":
                bq = parse_bq_row(row.message, ts)
                if bq is not None:
                    csv_writer.writerow(dataclasses.astuple(bq))
                else:
                    bq_unmatched += 1
            else:
                # EXCEL_ESCAPE only: Excel auto-parses a bare
                # "YYYY-MM-DD HH:MM:SS.mmm" cell as a date, reformatting it to
                # the sheet's locale and dropping the milliseconds, so the
                # `="..."` wrapper is used to keep it literal. It is left off by
                # default because those quotes and the `=` are real data: a
                # warehouse loading this CSV ingests `="2026-10-26 ..."`.
                cols = [f'="{ts}"' if excel_escape else ts]
                if aggregator is not None:
                    # A row the pattern didn't match still gets its columns, left
                    # blank — dropping it here would make the file disagree with
                    # rows_written and hide what failed to parse.
                    cols += parsed or [""] * len(aggregator.parsed_fields)
                if include_message:
                    cols.append(row.message)
                csv_writer.writerow(cols)
        if len(preview_sample) < PREVIEW_CAP:
            preview_sample.append({"timestamp": ts, "message": row.message})

    last_rows = cp.rows_written
    # ponytail: global lock on chunk_hours — per-job, single-threaded worker
    _chunk_hours = [effective_chunk_hours]

    _SPARSE = 50  # rows/chunk below this → double chunk_hours (up to 4 h)
    _DENSE = 5000  # rows/chunk above this → halve chunk_hours (down to 0.25 h)

    def on_chunk(cp: Checkpoint, rows_in_chunk: int) -> float | None:
        nonlocal last_rows, total
        if f is not None:
            f.flush()
            os.fsync(f.fileno())
        delta = cp.rows_written - last_rows
        last_rows = cp.rows_written

        # Adapt chunk size for the next chunk.
        previous_hours = _chunk_hours[0]
        h = previous_hours
        if rows_in_chunk < _SPARSE:
            h = min(h * 2, 4.0)
        elif rows_in_chunk > _DENSE:
            h = max(h / 2, 0.25)
        _chunk_hours[0] = h

        # Re-estimate the remaining chunk count at the size actually in use.
        # `total` was computed once from the starting size; adaptive sizing then
        # doubles chunks on sparse data, so a 25-hour window queued as 25 chunks
        # finished in 13 and the bar stopped at 52%. Recomputing each boundary
        # keeps the denominator in step with the work that remains.
        nxt = cp.next_chunk_start
        remaining = (
            count_chunks(nxt, spec.end_epoch, h) if nxt is not None and nxt < spec.end_epoch else 0
        )
        total = cp.completed_chunks + remaining

        checkpoint_extra = {"file_offset": f.tell() if f is not None else 0, "chunk_hours": h}
        update_fields: dict = {
            "completed_chunks": cp.completed_chunks,
            "total_chunks": total,
            "rows_written": cp.rows_written,
            "current_chunk_start": cp.current_chunk_start,
            "preview": preview_sample,
        }
        if aggregator is not None:
            # Commit this chunk's values to the store file. Nothing aggregation-
            # related goes into the checkpoint: the file is the state. The chunk
            # index makes the commit idempotent — occurrence counts add, so a
            # chunk replayed after a crash must not be counted a second time.
            aggregator.flush(cp.completed_chunks - 1)
            update_fields["aggregation_result"] = aggregator.snapshot()
        update_fields["checkpoint"] = {**cp.to_dict(), **checkpoint_extra}

        with eng.begin() as conn:
            db.update_job(conn, job_id, **update_fields)
            db.add_event(
                conn, job_id, f"Chunk {cp.completed_chunks}/{total} done", rows_delta=delta
            )
            status = db.current_status(conn, job_id)
        if status in ("paused", "canceled"):
            raise _Stopped(status)
        # Compared against the size the iterator is actually using, not the one
        # the job started with: after 1h -> 2h -> 1h the second change is still a
        # change, and returning None there left the iterator on 2h while the
        # checkpoint said 1h.
        return h if h != previous_hours else None

    written = 0
    last_beat = time.monotonic()
    try:
        for row in iter_extraction(client, spec, checkpoint=cp, on_chunk_complete=on_chunk):
            write_row(row)
            written += 1
            # Keep the job looking alive while one large chunk streams. The
            # reaper reads job_events, and a chunk that takes longer than
            # STALE_JOB_MINUTES otherwise looks like a dead worker.
            if not is_preview and time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
                last_beat = time.monotonic()
                with eng.begin() as conn:
                    db.add_event(
                        conn,
                        job_id,
                        f"Still scanning — {written:,} rows written so far "
                        f"(chunk {cp.completed_chunks + 1}/{total})",
                    )
            if is_preview and written >= ROW_CAP:
                break
    except _Stopped as stop:
        if f is not None:
            f.flush()
            f.close()
        if distinct_store is not None:
            distinct_store.close()
        http.close()
        with eng.begin() as conn:
            if stop.status == "canceled":
                db.update_job(conn, job_id, status="canceled", finished_at=_now())
                db.add_event(conn, job_id, "Job canceled", level="warn")
            else:
                db.update_job(conn, job_id, status="paused")
                db.add_event(conn, job_id, "Job paused")
        return
    except (Last9Error, Exception) as exc:  # noqa: BLE001 - record any failure on the job
        if f is not None:
            f.flush()
            f.close()
        if distinct_store is not None:
            distinct_store.close()
        http.close()
        error_msg = str(exc)
        with eng.begin() as conn:
            job = db.load(conn, db.jobs, job_id)
            db.update_job(
                conn, job_id, status="failed", error_message=error_msg, finished_at=_now()
            )
            db.add_event(conn, job_id, f"Failed: {exc}", level="error")
            if job:
                _send_alert_if_scheduled(conn, job, error_msg)
        return

    if f is not None:
        f.flush()
        f.close()
    http.close()

    summary = None
    counts = None
    if aggregator is not None:
        aggregator.flush()
        summary = summary_path(job_id, customer)
        aggregator.write_summary_csv(summary)
        counts = value_counts_path(job_id, customer)
        aggregator.write_value_counts_csv(counts)

    # BigQuery load — must happen before compression so we have a plain CSV
    if (
        fmt == "bigquery"
        and path is not None
        and not is_preview
        and (job.get("created_by") or "").startswith("schedule:")
    ):
        try:
            schedule_id = int(job["created_by"].split(":")[1])
            with eng.begin() as conn:
                sched = db.load(conn, db.schedules, schedule_id)
            bq_cfg = (sched or {}).get("bq_config")
            if bq_cfg:
                from app.bq_loader import load_csv_to_bigquery

                rows_loaded = load_csv_to_bigquery(path, bq_cfg)
                with eng.begin() as conn:
                    db.add_event(
                        conn,
                        job_id,
                        f"BigQuery load complete: {rows_loaded} rows → "
                        f"{bq_cfg['project_id']}.{bq_cfg['dataset_id']}.{bq_cfg['table_id']}",
                    )
        except Exception as exc:  # noqa: BLE001
            with eng.begin() as conn:
                db.add_event(conn, job_id, f"BigQuery load failed: {exc}", level="warn")

    # Compress raw output and summaries to save space (full extractions only)
    search_label = (job["filter_spec"] or {}).get("label")
    raw_arcname = export_entry_name(
        job_id, search_label, spec.start_epoch, spec.end_epoch, "raw", fmt
    )
    summary_arcname = export_entry_name(
        job_id, search_label, spec.start_epoch, spec.end_epoch, "summary", "csv"
    )
    counts_arcname = export_entry_name(
        job_id, search_label, spec.start_epoch, spec.end_epoch, "counts", "csv"
    )

    if f is not None and not is_preview:
        path = _zip_file(path, arcname=raw_arcname)
    if summary is not None and not is_preview:
        summary = _zip_file(summary, arcname=summary_arcname)
    if counts is not None and not is_preview:
        counts = _zip_file(counts, arcname=counts_arcname)

    with eng.begin() as conn:
        final: dict = {"status": "completed", "finished_at": _now(), "preview": preview_sample}
        if is_preview:
            final.update(rows_written=written, completed_chunks=1, total_chunks=1)
        else:
            final["output_file_path"] = path
            # Only when the checkpoint actually reached the end: that is the
            # "finished" case, where the bar must read N / N. A run that ends
            # without covering the range keeps its estimate instead of
            # pretending the little it did was all of the work.
            covered = cp.next_chunk_start is not None and cp.next_chunk_start >= spec.end_epoch
            if covered:
                final["total_chunks"] = cp.completed_chunks
        msg = "Preview ready" if is_preview else "Job completed"
        if cp.skipped_batches:
            # A short output that reports itself as clean is the dangerous case:
            # this is reconciliation data, so the gap is recorded on the job row
            # as well as the event feed.
            # ponytail: no new job status — a `completed_with_gaps` state would
            # touch the schema, the API and the UI. Add one if anything ever needs
            # to branch on it programmatically.
            gap = (
                f"{cp.skipped_batches} ID batch(es) skipped after repeated HTTP 400 — "
                f"up to {cp.skipped_batches * job['id_batch_size']} IDs are missing from this output"
            )
            msg += f" — {gap}"
            final["error_message"] = gap
        if fmt == "bigquery" and bq_unmatched > 0:
            msg += f" — {bq_unmatched} row(s) didn't match any BQ log pattern"
        if aggregator is not None:
            snap = aggregator.snapshot()
            final["aggregation_result"] = snap
            final["summary_file_path"] = summary
            final["counts_file_path"] = counts
            msg += (
                f" — parsed {snap['rows_matched']} matching row(s) "
                f"across {snap['total_groups']} group(s)"
            )
            if snap["rows_unmatched"]:
                msg += f", {snap['rows_unmatched']} row(s) didn't match the parse pattern"
        db.update_job(conn, job_id, **final)
        db.add_event(conn, job_id, msg)

    # Kept open until here: the summary CSV is written from it. The file itself
    # survives the job — the month-end rollup merges it.
    if distinct_store is not None:
        distinct_store.close()
