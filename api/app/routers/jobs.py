"""Jobs: create/list/get, pause/resume/cancel, SSE progress, signed CSV download."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, signing
from app.aggregation import validate_aggregation
from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.models import IndexTarget, Job, JobEvent, Last9Credential, Schedule, User
from app.portability import credential_ref, index_ref, resolve_credential, resolve_index
from app.schemas import JobCreate, JobEventOut, JobExport, JobOut, JobStatus, RollupCreate
from app.tasks_client import dispatch_job

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Routes here do their OWN auth instead of the blanket bearer-token dependency
# main.py applies to `router`: /download is a signed URL (the sig/exp params
# ARE the authorization, meant to work as a plain clickable link) and /progress
# is opened via EventSource, which cannot set an Authorization header.
public_router = APIRouter(prefix="/jobs", tags=["jobs"])

_TERMINAL = {"completed", "failed", "canceled"}


def _to_out(job: Job, credential_label: str | None = None, check_files: bool = True) -> JobOut:
    out = JobOut.model_validate(job)
    # check_files=False skips os.path.exists() calls — safe for list views where the
    # path being set is enough to know the file was written. Single-job fetches keep
    # check_files=True for accurate has_output / file-size metadata.
    if check_files:
        out.has_output = bool(job.output_file_path) and os.path.exists(job.output_file_path or "")
        if out.has_output and job.output_file_path:
            try:
                out.output_size_bytes = os.path.getsize(job.output_file_path)
            except OSError:
                pass
    else:
        out.has_output = bool(job.output_file_path)
    if job.status == "completed" and out.has_output:
        out.download_url = signing.make_download_url(job.id)
    if check_files:
        # Single-job fetches only: the list view has no stream to open, and
        # minting a ticket per row would scatter them through every response.
        out.progress_url = signing.make_progress_url(job.id)
    if check_files:
        out.has_summary = bool(job.summary_file_path) and os.path.exists(
            job.summary_file_path or ""
        )
        out.has_counts = bool(job.counts_file_path) and os.path.exists(job.counts_file_path or "")
    else:
        out.has_summary = bool(job.summary_file_path)
        out.has_counts = bool(job.counts_file_path)
    if out.has_summary:
        out.summary_url = signing.make_download_url(job.id) + "&kind=summary"
    if out.has_counts:
        out.counts_url = signing.make_download_url(job.id) + "&kind=counts"
    out.credential_label = credential_label
    return out


def _cred_label(db: Session, credential_id: int) -> str | None:
    c = db.get(Last9Credential, credential_id)
    return c.label if c else None


_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _timeframe(start_epoch: int, end_epoch: int) -> str:
    """The extracted window, as compactly as it can be said without ambiguity.

    Windows are half-open, so the last instant actually covered is ``end - 1``;
    naming a full day after its exclusive end would label 30 Aug's data "31 Aug".
    """
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


def download_filename(job: Job, kind: str = "raw", *, compressed: bool = True) -> str:
    """`<saved search>_<timeframe>[_summary|_counts].<ext>[.zip]`, e.g.
    AHA_CGetEntitlements_2026-08-30_counts.csv.zip — exported files are
    compressed by default.

    `compressed` must reflect the actual file on disk, not an assumption: a
    preview ("Test filter") run's raw output is written plain regardless of
    settings, and any file is written plain when `ZIP_EXPORTS` is off. Naming
    a plain-text file `*.zip` is exactly what made Windows (and every other
    zip reader) report the download as a corrupt archive — the bytes never
    were one.

    Falls back to the job id when the job wasn't created from a saved search.
    """
    label = (job.filter_spec or {}).get("label") or f"logvault_job_{job.id}"
    stem = _UNSAFE_IN_FILENAME.sub("_", label).strip("_") or f"job_{job.id}"
    name = f"{stem}_{_timeframe(job.start_epoch, job.end_epoch)}"
    suffix = ".zip" if compressed else ""
    if kind in ("summary", "counts"):
        return f"{name}_{kind}.csv{suffix}"
    ext = "jsonl" if job.output_format == "jsonl" else "csv"
    return f"{name}.{ext}{suffix}"


def _get_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    body: JobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    agg = body.aggregation
    if agg and agg.enabled:
        try:
            validate_aggregation(
                agg.regex,
                agg.group_by,
                agg.unique_fields,
                agg.raw_columns,
                agg.raw_column_defaults,
                agg.use_library,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # Fail here, not an hour into the run: a cloned job (or an index target left
    # pointing at a deleted credential) used to queue fine and die in the worker
    # with "missing credential/index".
    if db.get(Last9Credential, body.credential_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "credential no longer exists")
    if db.get(IndexTarget, body.index_target_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "index no longer exists")

    filter_spec = {"phrases": body.phrases, "ids": body.ids, "message_types": body.message_types}
    if agg:
        filter_spec["aggregation"] = agg.model_dump()
    if body.label:
        filter_spec["label"] = body.label
    if body.customer:
        filter_spec["customer"] = body.customer

    job = Job(
        status="queued",
        region_code=body.region_code,
        index_target_id=body.index_target_id,
        credential_id=body.credential_id,
        start_epoch=body.start_epoch,
        end_epoch=body.end_epoch,
        chunk_hours=body.chunk_hours,
        id_batch_size=body.id_batch_size,
        filter_spec=filter_spec,
        output_format=body.output_format,
        is_preview=body.is_preview,
        # Same column scheduled runs use for "schedule:N". It was left NULL for
        # everything created here, so nothing recorded who ran an extraction —
        # and the worker's failure net tripped over the None.
        created_by=user.email,
    )
    db.add(job)
    db.flush()
    audit.record(db, "create", "job", job.id, {"region": job.region_code}, user_id=user.email)
    db.commit()
    db.refresh(job)
    dispatch_job(job.id)
    return _to_out(job, credential_label=_cred_label(db, job.credential_id))


@router.get("/{job_id}/export", response_model=JobExport)
def export_job(job_id: int, db: Session = Depends(get_db)) -> JobExport:
    """Portable config for this job — the credential and index are resolved to
    their names, not the ids, so the result can be imported into a different
    environment where those ids won't match."""
    job = _get_or_404(db, job_id)
    cred = db.get(Last9Credential, job.credential_id)
    idx = db.get(IndexTarget, job.index_target_id)
    if cred is None or idx is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this job's credential or index no longer exists"
        )
    fs = job.filter_spec or {}
    return JobExport(
        label=fs.get("label", ""),
        customer=fs.get("customer", ""),
        region_code=job.region_code,
        index=index_ref(idx),
        credential=credential_ref(cred),
        start_epoch=job.start_epoch,
        end_epoch=job.end_epoch,
        chunk_hours=job.chunk_hours,
        id_batch_size=job.id_batch_size,
        output_format=job.output_format,
        phrases=fs.get("phrases", []),
        ids=fs.get("ids", []),
        message_types=fs.get("message_types", []),
        aggregation=fs.get("aggregation"),
    )


@router.post("/import", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def import_job(body: JobExport, db: Session = Depends(get_db)) -> JobOut:
    """Create a job from an export — reuses create_job so the same validation
    (aggregation regex, etc.) applies as a job made through the wizard."""
    cred = resolve_credential(db, body.credential)
    idx = resolve_index(db, body.index)
    if body.output_format not in ("csv", "jsonl"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"invalid output_format {body.output_format!r} (expected csv or jsonl)",
        )
    job_in = JobCreate(
        credential_id=cred.id,
        index_target_id=idx.id,
        region_code=body.region_code,
        start_epoch=body.start_epoch,
        end_epoch=body.end_epoch,
        # A fresh job always starts at a whole-hour chunk size — adaptive
        # sizing (see runner.py) re-derives any fraction during the run.
        chunk_hours=int(body.chunk_hours) or 1,
        id_batch_size=body.id_batch_size,
        phrases=body.phrases,
        ids=body.ids,
        message_types=body.message_types,
        output_format=cast(Literal["csv", "jsonl"], body.output_format),
        aggregation=body.aggregation,
        label=body.label,
        customer=body.customer,
    )
    return create_job(job_in, db)


@router.post("/rollup", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_rollup(
    body: RollupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    """Combine a schedule's runs over a period into one job with exact
    cross-period unique counts.

    Unique counts don't add — anything recurring across days would be counted
    once per day it appeared — so this merges the runs' underlying distinct
    values rather than summing their totals.
    """
    sched = db.get(Schedule, body.schedule_id)
    if sched is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "schedule not found")
    if body.end_epoch <= body.start_epoch:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "end must be after start")
    agg = (sched.filter_spec or {}).get("aggregation")
    if not agg or not agg.get("enabled"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "schedule has no parse & aggregate config — nothing to roll up",
        )

    sources = db.scalars(
        select(Job.id)
        .where(Job.created_by == f"schedule:{body.schedule_id}")
        .where(Job.status == "completed")
        .where(Job.start_epoch >= body.start_epoch)
        .where(Job.start_epoch < body.end_epoch)
    ).all()
    if not sources:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "no completed runs from this schedule in that period",
        )

    job = Job(
        status="queued",
        region_code=sched.region_code,
        index_target_id=sched.index_target_id,
        credential_id=sched.credential_id,
        start_epoch=body.start_epoch,
        end_epoch=body.end_epoch,
        chunk_hours=sched.chunk_hours,
        id_batch_size=sched.id_batch_size,
        filter_spec=sched.filter_spec,
        output_format="csv",
        is_preview=False,
        created_by=f"rollup:{body.schedule_id}",
        rollup_of={
            "schedule_id": body.schedule_id,
            "label": body.label or sched.name,
            "source_job_ids": list(sources),
        },
    )
    db.add(job)
    db.flush()
    audit.record(
        db, "create", "rollup", job.id, {"schedule_id": body.schedule_id}, user_id=user.email
    )
    db.commit()
    db.refresh(job)
    dispatch_job(job.id)
    return _to_out(job, credential_label=_cred_label(db, job.credential_id))


# The columns list views actually render. `preview` (~20 whole log rows),
# `aggregation_result`, `rollup_of` and `checkpoint` are job-detail-only and can
# each run to megabytes, so the list query never reads them off disk. Selecting
# columns rather than entities also skips ORM instance construction entirely.
_LIST_COLUMNS = (
    Job.id,
    Job.status,
    Job.region_code,
    Job.index_target_id,
    Job.credential_id,
    Job.start_epoch,
    Job.end_epoch,
    Job.chunk_hours,
    Job.id_batch_size,
    Job.filter_spec,
    Job.rows_written,
    Job.total_chunks,
    Job.completed_chunks,
    Job.current_chunk_start,
    Job.error_message,
    Job.created_at,
    Job.started_at,
    Job.finished_at,
    Job.output_format,
    Job.is_preview,
    Job.created_by,
    Job.output_file_path,
    Job.summary_file_path,
    Job.counts_file_path,
)

# `filter_spec.ids` routinely holds thousands of account IDs. List views only
# ever read the label and the customer, so the rest never leaves the database.
_LIST_FILTER_KEYS = ("label", "customer")


def _row_to_out(row, credential_label: str | None) -> JobOut:
    """Build a JobOut from a column row — the list-view counterpart of _to_out.

    Mirrors _to_out(check_files=False): a path being set is enough to know the
    file was written, so no os.stat() per row.
    """
    spec = row["filter_spec"] or {}
    out = JobOut(
        id=row["id"],
        status=row["status"],
        region_code=row["region_code"],
        index_target_id=row["index_target_id"],
        credential_id=row["credential_id"],
        start_epoch=row["start_epoch"],
        end_epoch=row["end_epoch"],
        chunk_hours=row["chunk_hours"],
        id_batch_size=row["id_batch_size"],
        filter_spec={k: spec[k] for k in _LIST_FILTER_KEYS if k in spec},
        rows_written=row["rows_written"],
        total_chunks=row["total_chunks"],
        completed_chunks=row["completed_chunks"],
        current_chunk_start=row["current_chunk_start"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        output_format=row["output_format"],
        is_preview=row["is_preview"],
        created_by=row["created_by"],
        credential_label=credential_label,
        has_output=bool(row["output_file_path"]),
        has_summary=bool(row["summary_file_path"]),
        has_counts=bool(row["counts_file_path"]),
    )
    if out.status == "completed" and out.has_output:
        out.download_url = signing.make_download_url(out.id)
    if out.has_summary:
        out.summary_url = signing.make_download_url(out.id) + "&kind=summary"
    if out.has_counts:
        out.counts_url = signing.make_download_url(out.id) + "&kind=counts"
    return out


@router.get("", response_model=list[JobOut])
def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    # Bounded by default: a daily schedule left running for a year is ~365 rows
    # on its own, and this list is re-polled every few seconds by every open tab.
    stmt = (
        select(*_LIST_COLUMNS)
        .where(Job.is_preview.is_(False))
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        stmt = stmt.where(Job.status == status_filter)
    rows = db.execute(stmt).mappings().all()
    # Batch-load credential labels — one extra query, not N.
    cred_ids = {r["credential_id"] for r in rows}
    labels: dict[int, str] = {}
    if cred_ids:
        labels = dict(
            db.execute(
                select(Last9Credential.id, Last9Credential.label).where(
                    Last9Credential.id.in_(cred_ids)
                )
            ).all()
        )
    return [_row_to_out(r, labels.get(r["credential_id"])) for r in rows]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    job = _get_or_404(db, job_id)
    return _to_out(job, credential_label=_cred_label(db, job.credential_id))


@router.get("/{job_id}/events", response_model=list[JobEventOut])
def list_events(job_id: int, db: Session = Depends(get_db)) -> list[JobEvent]:
    _get_or_404(db, job_id)
    return list(db.scalars(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id)))


@router.post("/{job_id}/pause", response_model=JobOut)
def pause_job(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    job = _get_or_404(db, job_id)
    if job.status not in ("queued", "running"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"cannot pause a {job.status} job")
    job.status = "paused"  # worker stops at the next chunk boundary
    db.commit()
    db.refresh(job)
    return _to_out(job, credential_label=_cred_label(db, job.credential_id))


@router.post("/{job_id}/resume", response_model=JobOut)
def resume_job(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    job = _get_or_404(db, job_id)
    if job.status != "paused":
        raise HTTPException(status.HTTP_409_CONFLICT, f"cannot resume a {job.status} job")
    job.status = "queued"
    db.commit()
    db.refresh(job)
    dispatch_job(job.id)  # resumes from checkpoint
    return _to_out(job, credential_label=_cred_label(db, job.credential_id))


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    job = _get_or_404(db, job_id)
    if job.status in _TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, f"job already {job.status}")
    job.status = "canceled"  # running worker finalizes partial output; queued never starts
    audit.record(db, "cancel", "job", job_id, user_id=user.email)
    db.commit()
    db.refresh(job)
    return _to_out(job, credential_label=_cred_label(db, job.credential_id))


class BulkCancelRequest(BaseModel):
    job_ids: list[int]


class BulkCancelResult(BaseModel):
    canceled: list[int]
    # Each entry names why that id didn't cancel — already terminal (with its
    # actual status) or never existed — so a stale selection reports cleanly
    # instead of the whole batch failing on one job that finished in the
    # meantime.
    skipped: dict[int, str]


@router.post("/bulk-cancel", response_model=BulkCancelResult)
def bulk_cancel_jobs(
    body: BulkCancelRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BulkCancelResult:
    canceled: list[int] = []
    skipped: dict[int, str] = {}
    # One id at a time rather than a single bulk UPDATE: each cancellation is
    # audited individually, same as the single-job endpoint, and a job that
    # finished between selection and click is reported rather than silently
    # skipped or failing the whole request.
    for job_id in dict.fromkeys(body.job_ids):  # de-dupe, keep selection order
        job = db.get(Job, job_id)
        if job is None:
            skipped[job_id] = "not_found"
            continue
        if job.status in _TERMINAL:
            skipped[job_id] = job.status
            continue
        job.status = "canceled"
        audit.record(db, "cancel", "job", job_id, user_id=user.email)
        canceled.append(job_id)
    db.commit()
    return BulkCancelResult(canceled=canceled, skipped=skipped)


@router.post("/{job_id}/retry", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    orig = _get_or_404(db, job_id)
    if orig.status not in ("failed", "canceled"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"cannot retry a {orig.status} job")
    # An old job's credential may since have been deleted; the source profile
    # knows the current one. Without this, retrying such a job just re-fails
    # with "missing credential/index", forever.
    credential_id = orig.credential_id
    if db.get(Last9Credential, credential_id) is None:
        idx = db.get(IndexTarget, orig.index_target_id)
        credential_id = idx.credential_id if idx else None
        if credential_id is None or db.get(Last9Credential, credential_id) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "credential no longer exists and this source has none — set one on the index",
            )

    job = Job(
        status="queued",
        region_code=orig.region_code,
        index_target_id=orig.index_target_id,
        credential_id=credential_id,
        start_epoch=orig.start_epoch,
        end_epoch=orig.end_epoch,
        chunk_hours=orig.chunk_hours,
        id_batch_size=orig.id_batch_size,
        filter_spec=orig.filter_spec,
        output_format=orig.output_format,
        is_preview=orig.is_preview,
        # Both carried deliberately. Dropping `created_by` detached a retried
        # scheduled day from its schedule, so the month-end rollup's
        # `schedule:N` filter skipped it and under-reported. Dropping
        # `rollup_of` turned a retried rollup back into a plain extraction,
        # which re-queries Last9 for the whole month instead of merging.
        created_by=orig.created_by,
        rollup_of=orig.rollup_of,
    )
    db.add(job)
    db.flush()
    audit.record(db, "retry", "job", job.id, {"from_job": job_id}, user_id=user.email)
    db.commit()
    db.refresh(job)
    dispatch_job(job.id)
    return _to_out(job, credential_label=_cred_label(db, job.credential_id))


@public_router.get("/{job_id}/download")
def download(
    job_id: int,
    exp: int,
    sig: str,
    kind: str = "raw",
    db: Session = Depends(get_db),
) -> FileResponse:
    # `kind` is deliberately outside the signature: both artifacts belong to the
    # same job and carry the same authorization decision, so being able to flip
    # between them grants nothing a valid link didn't already grant.
    if not signing.verify(job_id, exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid or expired link")
    job = _get_or_404(db, job_id)
    if kind in ("summary", "counts"):
        attr = "summary_file_path" if kind == "summary" else "counts_file_path"
        path = getattr(job, attr)
        if not path or not os.path.exists(path):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no {kind} file")
        # Whether it's actually a zip is a fact about the file, not the kind —
        # ZIP_EXPORTS=false writes every artifact plain, previews included.
        compressed = path.endswith(".zip")
        return FileResponse(
            path,
            media_type="application/zip" if compressed else "text/csv",
            filename=download_filename(job, kind, compressed=compressed),
        )
    if not job.output_file_path or not os.path.exists(job.output_file_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no output file")
    compressed = job.output_file_path.endswith(".zip")
    return FileResponse(
        job.output_file_path,
        media_type="application/zip" if compressed else "text/csv",
        filename=download_filename(job, compressed=compressed),
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _poll(job_id: int, last_event_id: int) -> tuple[list[dict], int, dict | None, str | None]:
    """One DB tick: new events, the high-water event id, current progress, and the
    terminal status if the job has finished. Runs in a worker thread, so it holds
    a Postgres connection for milliseconds rather than for the whole stream."""
    with SessionLocal() as db:
        # Four scalars, not the whole row: `db.get` loaded filter_spec too, which
        # routinely holds thousands of account IDs (~125 KB), plus preview,
        # checkpoint and aggregation_result — fetched and deserialized once a
        # second per open job page, to read four integers.
        row = db.execute(
            select(Job.status, Job.rows_written, Job.completed_chunks, Job.total_chunks).where(
                Job.id == job_id
            )
        ).first()
        if row is None:
            return ([{"type": "error", "message": "job not found"}], last_event_id, None, "gone")
        job_status, rows_written, completed_chunks, total_chunks = row
        events = db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.id > last_event_id)
            .order_by(JobEvent.id)
        ).all()
        payloads = [
            {
                "type": "event",
                "level": ev.level,
                "message": ev.message,
                "rows_delta": ev.rows_delta,
                "ts": ev.ts.isoformat() if ev.ts else None,
            }
            for ev in events
        ]
        if events:
            last_event_id = events[-1].id
        progress = {
            "type": "progress",
            "status": job_status,
            "rows_written": rows_written,
            "completed_chunks": completed_chunks,
            "total_chunks": total_chunks,
        }
        terminal = job_status if job_status in _TERMINAL else None
        return payloads, last_event_id, progress, terminal


@public_router.get("/{job_id}/progress")
async def progress(job_id: int, exp: int, sig: str) -> StreamingResponse:
    """Server-Sent Events: live progress + event feed. ponytail: polls the DB every
    second (no pub/sub); fine at this scale and survives refresh via the DB.

    Async on purpose. A sync generator here is iterated through Starlette's
    thread pool, and the `time.sleep(1)` inside it held one of those ~40 threads
    for the entire life of the connection — enough open job pages starved every
    other endpoint, which all run in that same pool.

    Authorized by a job-scoped signed ticket rather than the caller's session
    JWT: EventSource cannot set headers, and the token used to travel in the URL
    straight into access logs and browser history.
    """
    if not signing.verify_progress(job_id, exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid or expired progress link")

    async def stream() -> AsyncIterator[str]:
        last_event_id = 0
        last_progress: dict | None = None
        while True:
            payloads, last_event_id, prog, terminal = await run_in_threadpool(
                _poll, job_id, last_event_id
            )
            for payload in payloads:
                yield _sse(payload)
            if terminal == "gone":
                return
            if prog is not None and prog != last_progress:
                yield _sse(prog)
                last_progress = prog
            if terminal:
                yield _sse({"type": terminal})
                return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")
