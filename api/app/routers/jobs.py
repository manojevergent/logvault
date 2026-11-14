"""Jobs: create/list/get, pause/resume/cancel, SSE progress, signed CSV download."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import zipfile
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, s3, signing
from app.aggregation import validate_aggregation
from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.format_registry import register_aggregation_pattern
from app.models import (
    ExtractionGroup,
    FilterTemplate,
    IndexTarget,
    Job,
    JobEvent,
    Last9Credential,
    S3Profile,
    Schedule,
    User,
)
from app.portability import credential_ref, index_ref, resolve_credential, resolve_index
from app.schemas import (
    BatchCreate,
    JobCreate,
    JobEventOut,
    JobExport,
    JobOut,
    JobStats,
    JobStatus,
    RollupCreate,
    S3ProfileRef,
)
from app.tasks_client import dispatch_job, dispatch_s3_upload

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Routes here do their OWN auth instead of the blanket bearer-token dependency
# main.py applies to `router`: /download is a signed URL (the sig/exp params
# ARE the authorization, meant to work as a plain clickable link) and /progress
# is opened via EventSource, which cannot set an Authorization header.
public_router = APIRouter(prefix="/jobs", tags=["jobs"])

_TERMINAL = {"completed", "failed", "canceled"}
# A partial run still has a downloadable file. "running" is excluded: the worker
# holds that file open and is still appending to it.
_DOWNLOADABLE = {"completed", "failed", "canceled", "paused"}

# Progress-stream cadence. A running job gets a live tick; anything else is
# polled less often because its numbers only move when a worker picks it up.
_PROGRESS_POLL_RUNNING = 1.0
_PROGRESS_POLL_IDLE = 3.0


def _to_out(job: Job, credential_label: str | None = None, check_files: bool = True) -> JobOut:
    out = JobOut.model_validate(job)
    # check_files=False skips os.path.exists() calls — safe for list views where the
    # path being set is enough to know the file was written. Single-job fetches keep
    # check_files=True for accurate has_output / file-size metadata.
    if check_files:
        out.has_output = bool(job.output_file_path) and os.path.exists(job.output_file_path or "")
        if out.has_output and job.output_file_path:
            with contextlib.suppress(OSError):
                out.output_size_bytes = os.path.getsize(job.output_file_path)
    else:
        out.has_output = bool(job.output_file_path)
    if job.status in _DOWNLOADABLE and out.has_output:
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
        out.has_unmatched = bool(job.unmatched_file_path) and os.path.exists(
            job.unmatched_file_path or ""
        )
    else:
        out.has_summary = bool(job.summary_file_path)
        out.has_counts = bool(job.counts_file_path)
        out.has_unmatched = bool(job.unmatched_file_path)
    if out.has_summary:
        out.summary_url = signing.make_download_url(job.id) + "&kind=summary"
    if out.has_counts:
        out.counts_url = signing.make_download_url(job.id) + "&kind=counts"
    if out.has_unmatched:
        out.unmatched_url = signing.make_download_url(job.id) + "&kind=unmatched"
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


def download_filename(
    job: Job, kind: str = "raw", *, compressed: bool = True, text: bool = False
) -> str:
    """`<saved search>_<job id>_<timeframe>[_summary|_counts].<ext>[.zip]`, e.g.
    AHA_CGetEntitlements_16_2026-08-30_counts.csv.zip — exported files are
    compressed by default. The job id disambiguates batch runs, where several
    jobs share one search name and one window.

    `compressed` must reflect the actual file on disk, not an assumption: a
    preview ("Test filter") run's raw output is written plain regardless of
    settings, and any file is written plain when `ZIP_EXPORTS` is off. Naming
    a plain-text file `*.zip` is exactly what made Windows (and every other
    zip reader) report the download as a corrupt archive — the bytes never
    were one.

    `text` names the same bytes as `.txt`; the TXT download is always a plain
    file, never a zip, because the caller streams the archive's contents.

    Falls back to the job id when the job wasn't created from a saved search.
    """
    label = (job.filter_spec or {}).get("label")
    if label:
        stem = _UNSAFE_IN_FILENAME.sub("_", label).strip("_") or f"job_{job.id}"
        stem = f"{stem}_{job.id}"
    else:
        stem = f"logvault_job_{job.id}"
    name = f"{stem}_{_timeframe(job.start_epoch, job.end_epoch)}"
    if text:
        if kind in ("summary", "counts", "unmatched"):
            return f"{name}_{kind}.txt"
        return f"{name}.txt"
    suffix = ".zip" if compressed else ""
    if kind in ("summary", "counts", "unmatched"):
        return f"{name}_{kind}.csv{suffix}"
    ext = "jsonl" if job.output_format == "jsonl" else "csv"
    return f"{name}.{ext}{suffix}"


def _get_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job


def _validate_agg_dict(agg: dict | None) -> None:
    """The create_job aggregation check, generalized to stored dicts (batch
    items carry the template's saved config, not a fresh AggregationSpec)."""
    if agg and agg.get("enabled"):
        try:
            validate_aggregation(
                agg.get("regex", ""),
                agg.get("group_by", []),
                agg.get("unique_fields", []),
                agg.get("raw_columns", []),
                agg.get("raw_column_defaults", {}),
                agg.get("use_library", False),
                agg.get("aggregate", True),
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def _new_job_row(
    *,
    credential_id: int,
    index_target_id: int,
    region_code: str,
    start_epoch: int,
    end_epoch: int,
    chunk_hours: int,
    id_batch_size: int,
    phrases: list[str],
    ids: list[str],
    exact_phrases: list[str] | None = None,
    exclude_phrases: list[str] | None = None,
    exclude_exact_phrases: list[str] | None = None,
    message_types: list[str],
    output_format: str,
    is_preview: bool,
    aggregation: dict | None,
    label: str,
    customer: str,
    s3_profile_id: int | None,
    s3_destination: dict | None,
    created_by: str | None,
    group_id: int | None = None,
) -> Job:
    filter_spec: dict = {
        "phrases": phrases,
        "ids": ids,
        "exact_phrases": exact_phrases or [],
        "exclude_phrases": exclude_phrases or [],
        "exclude_exact_phrases": exclude_exact_phrases or [],
        "message_types": message_types,
    }
    if aggregation:
        filter_spec["aggregation"] = aggregation
    if label:
        filter_spec["label"] = label
    if customer:
        filter_spec["customer"] = customer
    return Job(
        status="queued",
        region_code=region_code,
        index_target_id=index_target_id,
        credential_id=credential_id,
        start_epoch=start_epoch,
        end_epoch=end_epoch,
        chunk_hours=chunk_hours,
        id_batch_size=id_batch_size,
        filter_spec=filter_spec,
        output_format=output_format,
        is_preview=is_preview,
        s3_profile_id=s3_profile_id,
        s3_destination=s3_destination,
        # Same column scheduled runs use for "schedule:N". It was left NULL for
        # everything created here, so nothing recorded who ran an extraction —
        # and the worker's failure net tripped over the None.
        created_by=created_by,
        group_id=group_id,
    )


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    body: JobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    if not body.label or not body.label.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Search Name / Extraction Label is required"
        )
    if not (body.phrases or body.ids or body.exact_phrases or body.message_types):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "a filter needs at least one required phrase, exact phrase, ID or message type",
        )
    agg = body.aggregation.model_dump() if body.aggregation else None
    _validate_agg_dict(agg)

    # Fail here, not an hour into the run: a cloned job (or an index target left
    # pointing at a deleted credential) used to queue fine and die in the worker
    # with "missing credential/index".
    if db.get(Last9Credential, body.credential_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "credential no longer exists")
    if db.get(IndexTarget, body.index_target_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "index no longer exists")
    s3_profile = s3.profile_or_422(db, body.s3_profile_id)

    job = _new_job_row(
        credential_id=body.credential_id,
        index_target_id=body.index_target_id,
        region_code=body.region_code,
        start_epoch=body.start_epoch,
        end_epoch=body.end_epoch,
        chunk_hours=body.chunk_hours,
        id_batch_size=body.id_batch_size,
        phrases=body.phrases,
        ids=body.ids,
        exact_phrases=body.exact_phrases,
        exclude_phrases=body.exclude_phrases,
        exclude_exact_phrases=body.exclude_exact_phrases,
        message_types=body.message_types,
        output_format=body.output_format,
        is_preview=body.is_preview,
        aggregation=agg,
        label=body.label,
        customer=body.customer,
        s3_profile_id=body.s3_profile_id,
        s3_destination=s3.destination_snapshot(s3_profile),
        created_by=user.email,
    )
    db.add(job)
    db.flush()
    register_aggregation_pattern(
        db,
        aggregation=agg,
        source_name=body.label,
        source_kind="job",
        source_id=job.id,
        created_by=user.email,
    )
    audit.record(db, "create", "job", job.id, {"region": job.region_code}, user_id=user.email)
    db.commit()
    db.refresh(job)
    dispatch_job(job.id)
    return _to_out(job, credential_label=_cred_label(db, job.credential_id))


# One request queuing dozens of multi-hour extractions is how a mistaken click
# turns into a Last9 bill and a saturated worker pool. Fifty is far above any
# real invoice batch (13 searches) while still catching accidents.
MAX_BATCH_ITEMS = 50


def _resolve_batch_plans(
    db: Session, items, *, created_by: str | None = None
) -> list[tuple[FilterTemplate, dict | None, int, int, str, S3Profile | None]]:
    """Validate every selected search and pin its source before anything runs.

    Shared by the legacy /jobs/batch endpoint and the first-class group launch;
    resolving once is what keeps validation and job creation from disagreeing
    about which index a search runs against. Registration here also catches a
    template whose pattern predates auto-registration or was created while the
    feature was off: launching the group makes the library current.
    """
    plans: list[tuple[FilterTemplate, dict | None, int, int, str, S3Profile | None]] = []
    for item in items:
        tpl = db.get(FilterTemplate, item.template_id)
        if tpl is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"saved search {item.template_id} no longer exists",
            )
        # Explicit per-entry source wins; otherwise the search's remembered
        # source. Anything still missing names the search that needs one.
        credential_id = item.credential_id if item.credential_id is not None else tpl.credential_id
        index_target_id = (
            item.index_target_id if item.index_target_id is not None else tpl.index_target_id
        )
        region_code = item.region_code if item.region_code is not None else tpl.region_code
        if credential_id is None or index_target_id is None or region_code is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"search {tpl.name!r} has no source: pick one per row or save a default on the search",
            )
        if db.get(Last9Credential, credential_id) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"credential no longer exists (search {tpl.name!r})",
            )
        if db.get(IndexTarget, index_target_id) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"index no longer exists (search {tpl.name!r})",
            )
        agg = dict(tpl.aggregation) if tpl.aggregation else None
        _validate_agg_dict(agg)
        s3_profile = s3.profile_or_422(db, tpl.s3_profile_id)
        # Idempotent by regex; no-op for a pattern already in the library.
        register_aggregation_pattern(
            db,
            aggregation=agg,
            source_name=tpl.name,
            source_kind="saved search",
            source_id=tpl.id,
            created_by=created_by,
        )
        plans.append((tpl, agg, credential_id, index_target_id, region_code, s3_profile))
    return plans


@router.post("/batch", response_model=list[JobOut], status_code=status.HTTP_201_CREATED)
def create_batch(
    body: BatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[JobOut]:
    """Run several saved searches over one shared window — one job per search,
    each file named `<search>_<job id>_<window>`. All-or-nothing: every entry
    is validated before the first job queues, so a bad template or a deleted
    credential fails the request instead of half the batch."""
    if not body.items:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "at least one search is required")
    if len(body.items) > MAX_BATCH_ITEMS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"at most {MAX_BATCH_ITEMS} searches per batch",
        )
    if body.end_epoch <= body.start_epoch:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "end must be after start")

    # (template, aggregation, resolved credential/index/region). Resolved once
    # here so validation and creation can't disagree about the source.
    plans = _resolve_batch_plans(db, body.items, created_by=user.email)

    # The batch is also a group, so it can be tracked/canceled/retried as one
    # unit later. One-search batches (the quick-run button on a saved search)
    # stay plain jobs: they are not a group worth listing.
    group: ExtractionGroup | None = None
    if len(plans) > 1:
        group = ExtractionGroup(
            name=f"{'Preview' if body.is_preview else 'Batch'} · {len(plans)} searches · "
            f"{datetime.now(UTC):%d %b %Y %H:%M} UTC",
            created_by=user.email,
            start_epoch=body.start_epoch,
            end_epoch=body.end_epoch,
            chunk_hours=body.chunk_hours,
            id_batch_size=body.id_batch_size,
            output_format=body.output_format,
            is_preview=body.is_preview,
        )
        db.add(group)
        db.flush()

    jobs = [
        _new_job_row(
            credential_id=credential_id,
            index_target_id=index_target_id,
            region_code=region_code,
            start_epoch=body.start_epoch,
            end_epoch=body.end_epoch,
            chunk_hours=body.chunk_hours,
            id_batch_size=body.id_batch_size,
            phrases=list(tpl.phrases),
            ids=list(tpl.ids),
            exact_phrases=list(tpl.exact_phrases),
            exclude_phrases=list(tpl.exclude_phrases),
            exclude_exact_phrases=list(tpl.exclude_exact_phrases),
            message_types=list(tpl.message_types),
            output_format=body.output_format,
            is_preview=body.is_preview,
            aggregation=agg,
            label=tpl.name,
            customer=tpl.customer or "",
            s3_profile_id=s3_profile.id if s3_profile else None,
            s3_destination=s3.destination_snapshot(s3_profile),
            created_by=user.email,
            group_id=group.id if group else None,
        )
        for tpl, agg, credential_id, index_target_id, region_code, s3_profile in plans
    ]
    db.add_all(jobs)
    db.flush()
    for job, (tpl, _agg, _cred, _idx, _region, _s3) in zip(jobs, plans, strict=True):
        audit.record(
            db,
            "create",
            "job",
            job.id,
            {"region": job.region_code, "batch": tpl.name},
            user_id=user.email,
        )
    db.commit()
    for job in jobs:
        db.refresh(job)
    for job in jobs:
        dispatch_job(job.id)
    labels = {
        c.id: c.label
        for c in db.query(Last9Credential).filter(
            Last9Credential.id.in_({j.credential_id for j in jobs})
        )
    }
    return [_to_out(job, credential_label=labels.get(job.credential_id)) for job in jobs]


@router.post("/{job_id}/s3-upload", response_model=JobOut)
def retry_s3_upload(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    """Queue a retry of S3 delivery without re-running the extraction."""
    job = _get_or_404(db, job_id)
    if job.is_preview:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "previews are not uploaded to S3")
    if not job.s3_profile_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "this job has no S3 destination")
    if job.status != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, f"cannot upload a {job.status} job")
    dispatch_s3_upload(job.id)
    audit.record(
        db, "s3_upload", "job", job.id, {"profile_id": job.s3_profile_id}, user_id=user.email
    )
    db.commit()
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
    s3_profile = db.get(S3Profile, job.s3_profile_id) if job.s3_profile_id else None
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
        exact_phrases=fs.get("exact_phrases", []),
        exclude_phrases=fs.get("exclude_phrases", []),
        exclude_exact_phrases=fs.get("exclude_exact_phrases", []),
        message_types=fs.get("message_types", []),
        aggregation=fs.get("aggregation"),
        s3_profile=S3ProfileRef(name=s3_profile.name) if s3_profile else None,
    )


@router.post("/import", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def import_job(body: JobExport, db: Session = Depends(get_db)) -> JobOut:
    """Create a job from an export — reuses create_job so the same validation
    (aggregation regex, etc.) applies as a job made through the wizard."""
    cred = resolve_credential(db, body.credential)
    idx = resolve_index(db, body.index)
    s3_profile = None
    if body.s3_profile:
        s3_profile = s3.profile_by_name(db, body.s3_profile.name)
        if s3_profile is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"S3 profile {body.s3_profile.name!r} does not exist",
            )
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
        exact_phrases=body.exact_phrases,
        exclude_phrases=body.exclude_phrases,
        exclude_exact_phrases=body.exclude_exact_phrases,
        message_types=body.message_types,
        output_format=cast(Literal["csv", "jsonl"], body.output_format),
        aggregation=body.aggregation,
        label=body.label,
        customer=body.customer,
        s3_profile_id=s3_profile.id if s3_profile else None,
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
# `filter_spec.ids` routinely holds thousands of account IDs (the largest job
# here carries a 12 kB spec). List views only ever read the label and the
# customer, so the query extracts just those two keys instead of shipping and
# deserializing the whole document on every poll.
_LIST_COLUMNS = (
    Job.id,
    Job.group_id,
    Job.status,
    Job.region_code,
    Job.index_target_id,
    Job.credential_id,
    Job.start_epoch,
    Job.end_epoch,
    Job.chunk_hours,
    Job.id_batch_size,
    Job.filter_spec["label"].as_string().label("filter_label"),
    Job.filter_spec["customer"].as_string().label("filter_customer"),
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
    Job.unmatched_file_path,
    Job.s3_profile_id,
    Job.s3_destination,
    Job.s3_uri,
    Job.s3_error,
)

# `filter_spec.ids` routinely holds thousands of account IDs. List views only
# ever read the label and the customer, so the rest never leaves the database.
_LIST_FILTER_KEYS = ("label", "customer")


def _row_to_out(row, credential_label: str | None) -> JobOut:
    """Build a JobOut from a column row — the list-view counterpart of _to_out.

    Mirrors _to_out(check_files=False): a path being set is enough to know the
    file was written, so no os.stat() per row.
    """
    # The two keys were extracted in SQL; rebuild the sparse dict the list
    # response has always carried instead of the full stored document.
    spec = {
        key: row[f"filter_{key}"] for key in _LIST_FILTER_KEYS if row[f"filter_{key}"] is not None
    }
    out = JobOut(
        id=row["id"],
        group_id=row["group_id"],
        status=row["status"],
        region_code=row["region_code"],
        index_target_id=row["index_target_id"],
        credential_id=row["credential_id"],
        start_epoch=row["start_epoch"],
        end_epoch=row["end_epoch"],
        chunk_hours=row["chunk_hours"],
        id_batch_size=row["id_batch_size"],
        filter_spec=spec,
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
        has_unmatched=bool(row["unmatched_file_path"]),
        s3_profile_id=row["s3_profile_id"],
        s3_destination=row["s3_destination"],
        s3_uri=row["s3_uri"],
        s3_error=row["s3_error"],
    )
    if out.status in _DOWNLOADABLE and out.has_output:
        out.download_url = signing.make_download_url(out.id)
    if out.has_summary:
        out.summary_url = signing.make_download_url(out.id) + "&kind=summary"
    if out.has_counts:
        out.counts_url = signing.make_download_url(out.id) + "&kind=counts"
    if out.has_unmatched:
        out.unmatched_url = signing.make_download_url(out.id) + "&kind=unmatched"
    return out


@router.get("", response_model=list[JobOut])
def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    include_previews: bool = Query(default=False),
    previews_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    # Bounded by default: a daily schedule left running for a year is ~365 rows
    # on its own, and this list is re-polled every few seconds by every open tab.
    # Filter-test previews stay out unless asked: they would drown the real
    # extractions otherwise (every "Test filter" click is a job row).
    stmt = select(*_LIST_COLUMNS).order_by(Job.created_at.desc()).limit(limit).offset(offset)
    if previews_only:
        stmt = stmt.where(Job.is_preview.is_(True))
    elif not include_previews:
        stmt = stmt.where(Job.is_preview.is_(False))
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


@router.get("/stats", response_model=JobStats)
def job_stats(db: Session = Depends(get_db)) -> JobStats:
    """Whole-table aggregates for the dashboard and tab counts.

    Must be declared before `/{job_id}` so the literal path wins.
    """
    real = Job.is_preview.is_(False)
    total, rows = db.execute(
        select(func.count(Job.id), func.coalesce(func.sum(Job.rows_written), 0)).where(real)
    ).one()
    by_status = dict(
        db.execute(select(Job.status, func.count(Job.id)).where(real).group_by(Job.status)).all()
    )
    previews = db.scalar(select(func.count(Job.id)).where(Job.is_preview.is_(True))) or 0
    return JobStats(
        total=int(total or 0),
        rows_written=int(rows or 0),
        by_status={str(k): int(v) for k, v in by_status.items()},
        previews=int(previews),
    )


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
    job.status = "paused"  # the worker notices within ~10s
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


@router.delete("/{job_id}/files", response_model=JobOut)
def delete_job_files(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    """Delete extracted output files (CSV/ZIP, summary, counts) for a job from disk."""
    job = _get_or_404(db, job_id)
    if job.status in ("queued", "running", "paused"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"cannot delete files of an active/paused job (status: {job.status})",
        )

    paths_to_remove = [
        job.output_file_path,
        job.summary_file_path,
        job.counts_file_path,
        job.unmatched_file_path,
    ]

    for file_path in paths_to_remove:
        if file_path:
            candidates = {file_path}
            if file_path.endswith(".zip"):
                candidates.add(file_path[:-4])
            else:
                candidates.add(f"{file_path}.zip")
            for path in candidates:
                if os.path.exists(path):
                    with contextlib.suppress(OSError):
                        os.remove(path)

    job.output_file_path = None
    job.summary_file_path = None
    job.counts_file_path = None
    job.unmatched_file_path = None

    db.add(JobEvent(job_id=job.id, message="Extracted output files deleted from disk"))
    audit.record(db, "delete_files", "job", job.id, user_id=user.email)
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
        s3_profile_id=orig.s3_profile_id,
        s3_destination=orig.s3_destination,
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


_TEXT_CHUNK_SIZE = 64 * 1024


def _validate_text_archive(path: str) -> None:
    """A TXT download streams a zip's member, so reject a corrupt archive
    before the response starts instead of failing halfway through the body."""
    if not path.endswith(".zip"):
        return
    try:
        with zipfile.ZipFile(path) as zf:
            if not any(not name.endswith("/") for name in zf.namelist()):
                raise HTTPException(status.HTTP_409_CONFLICT, "stored archive is empty")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "stored archive is corrupt") from exc


def _text_download_stream(path: str) -> Iterator[bytes]:
    """Yield the stored comma-separated bytes, decompressing on the fly.

    The TXT download is deliberately not a `.txt.zip`: the caller asked for a
    text file, so a zipped extract is opened and streamed member by member.
    Chunked reads keep a multi-GB extract out of memory.
    """
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                with zf.open(name) as member:
                    while chunk := member.read(_TEXT_CHUNK_SIZE):
                        yield chunk
        return
    with open(path, "rb") as fh:
        while chunk := fh.read(_TEXT_CHUNK_SIZE):
            yield chunk


@public_router.get("/{job_id}/download", response_model=None)
def download(
    job_id: int,
    exp: int,
    sig: str,
    kind: str = "raw",
    file_format: Literal["csv", "txt"] = Query(default="csv", alias="format"),
    db: Session = Depends(get_db),
) -> FileResponse | StreamingResponse:
    # `kind` and `format` are deliberately outside the signature: both
    # artifacts and both names describe the same authorized bytes, so flipping
    # them grants nothing a valid link didn't already grant.
    if not signing.verify(job_id, exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid or expired link")
    job = _get_or_404(db, job_id)
    if kind in ("summary", "counts", "unmatched"):
        attr = {
            "summary": "summary_file_path",
            "counts": "counts_file_path",
            "unmatched": "unmatched_file_path",
        }[kind]
        path = getattr(job, attr)
        if not path or not os.path.exists(path):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no {kind} file")
    else:
        path = job.output_file_path
        if not path or not os.path.exists(path):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no output file")
        if file_format == "txt" and (
            job.output_format == "jsonl" or path.endswith(".jsonl") or path.endswith(".jsonl.zip")
        ):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "TXT download is only available for comma-separated extracts",
            )

    # Whether it's actually a zip is a fact about the file, not the kind —
    # ZIP_EXPORTS=false writes every artifact plain, previews included.
    compressed = path.endswith(".zip")
    if file_format == "txt":
        _validate_text_archive(path)
        filename = download_filename(job, kind, text=True)
        return StreamingResponse(
            _text_download_stream(path),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    return FileResponse(
        path,
        media_type="application/zip" if compressed else "text/csv",
        filename=download_filename(job, kind, compressed=compressed),
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
            # Two queries per tick, per open page. A running job needs the live
            # feel; a queued or paused one changes at most once per worker slot,
            # so polling it a second apart is pure load. The next tick after a
            # status change picks up the faster cadence automatically.
            running = (prog or {}).get("status") == "running"
            await asyncio.sleep(_PROGRESS_POLL_RUNNING if running else _PROGRESS_POLL_IDLE)

    return StreamingResponse(stream(), media_type="text/event-stream")
