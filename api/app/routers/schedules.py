"""Recurring extraction schedules (F1). The worker beat scans these every minute."""

from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, s3
from app.aggregation import validate_aggregation
from app.database import get_db
from app.deps import get_current_user
from app.format_registry import register_aggregation_pattern
from app.models import IndexTarget, Job, Last9Credential, S3Profile, Schedule, User
from app.portability import credential_ref, index_ref, resolve_credential, resolve_index
from app.schemas import (
    BQConfig,
    S3ProfileRef,
    ScheduleCreate,
    ScheduleExport,
    ScheduleOut,
    ScheduleUpdate,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _get_or_404(db: Session, sid: int) -> Schedule:
    s = db.get(Schedule, sid)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "schedule not found")
    return s


def _check_aggregation(agg) -> None:
    if agg and agg.enabled:
        try:
            validate_aggregation(
                agg.regex,
                agg.group_by,
                agg.unique_fields,
                agg.raw_columns,
                agg.raw_column_defaults,
                agg.use_library,
                agg.aggregate,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(
    body: ScheduleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScheduleOut:
    if not (body.phrases or body.ids or body.exact_phrases):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "a schedule needs at least one required phrase, exact phrase or ID",
        )
    _check_aggregation(body.aggregation)
    filter_spec = {
        "phrases": body.phrases,
        "ids": body.ids,
        "exact_phrases": body.exact_phrases,
        "exclude_phrases": body.exclude_phrases,
        "exclude_exact_phrases": body.exclude_exact_phrases,
    }
    if body.aggregation:
        filter_spec["aggregation"] = body.aggregation.model_dump()
    if body.customer:
        filter_spec["customer"] = body.customer
    s3_profile = s3.profile_or_422(db, body.s3_profile_id)

    sched = Schedule(
        name=body.name,
        enabled=body.enabled,
        interval_seconds=body.interval_seconds,
        lookback_seconds=body.lookback_seconds,
        calendar_day=body.calendar_day,
        region_code=body.region_code,
        index_target_id=body.index_target_id,
        credential_id=body.credential_id,
        chunk_hours=body.chunk_hours,
        id_batch_size=body.id_batch_size,
        output_format=body.output_format,
        filter_spec=filter_spec,
        s3_profile_id=s3_profile.id if s3_profile else None,
        alert_recipients=body.alert_recipients,
        bq_config=body.bq_config.model_dump() if body.bq_config else None,
    )
    db.add(sched)
    db.flush()
    register_aggregation_pattern(
        db,
        aggregation=body.aggregation.model_dump() if body.aggregation else None,
        source_name=sched.name,
        source_kind="schedule",
        source_id=sched.id,
        created_by=user.email,
    )
    audit.record(db, "create", "schedule", sched.id, {"name": sched.name}, user_id=user.email)
    db.commit()
    db.refresh(sched)
    return _with_last_job([sched], db)[0]


def _with_last_job(schedules: list[Schedule], db: Session) -> list[ScheduleOut]:
    profile_ids = {s.s3_profile_id for s in schedules if s.s3_profile_id}
    labels = (
        dict(
            db.execute(
                select(S3Profile.id, S3Profile.name).where(S3Profile.id.in_(profile_ids))
            ).all()
        )
        if profile_ids
        else {}
    )
    # One grouped query instead of one "newest job for this schedule" query per
    # row: the schedules page polls this list and each query was a scan of the
    # jobs table.
    owner_ids = [f"schedule:{s.id}" for s in schedules]
    last_jobs = (
        dict(
            db.execute(
                select(Job.created_by, func.max(Job.id))
                .where(Job.created_by.in_(owner_ids))
                .group_by(Job.created_by)
            ).all()
        )
        if owner_ids
        else {}
    )
    outs = []
    for s in schedules:
        out = ScheduleOut.model_validate(s)
        out.s3_profile_label = labels.get(s.s3_profile_id)
        out.last_run_job_id = last_jobs.get(f"schedule:{s.id}")
        outs.append(out)
    return outs


@router.get("", response_model=list[ScheduleOut])
def list_schedules(db: Session = Depends(get_db)) -> list[ScheduleOut]:
    schedules = list(db.scalars(select(Schedule).order_by(Schedule.created_at.desc())))
    return _with_last_job(schedules, db)


@router.post("/import", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def import_schedule(body: ScheduleExport, db: Session = Depends(get_db)) -> ScheduleOut:
    """Create a schedule from an export — reuses create_schedule so the same
    validation (aggregation regex, etc.) applies as a schedule made in the UI."""
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
    if body.output_format not in ("csv", "jsonl", "bigquery"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"invalid output_format {body.output_format!r} (expected csv, jsonl, or bigquery)",
        )
    sched_in = ScheduleCreate(
        name=body.name,
        interval_seconds=body.interval_seconds,
        lookback_seconds=body.lookback_seconds,
        calendar_day=body.calendar_day,
        credential_id=cred.id,
        index_target_id=idx.id,
        region_code=body.region_code,
        chunk_hours=body.chunk_hours,
        id_batch_size=body.id_batch_size,
        output_format=cast(Literal["csv", "jsonl", "bigquery"], body.output_format),
        phrases=body.phrases,
        ids=body.ids,
        exact_phrases=body.exact_phrases,
        exclude_phrases=body.exclude_phrases,
        exclude_exact_phrases=body.exclude_exact_phrases,
        enabled=body.enabled,
        aggregation=body.aggregation,
        customer=body.customer,
        alert_recipients=body.alert_recipients,
        bq_config=body.bq_config,
        s3_profile_id=s3_profile.id if s3_profile else None,
    )
    return create_schedule(sched_in, db)


@router.get("/{sid}/export", response_model=ScheduleExport)
def export_schedule(sid: int, db: Session = Depends(get_db)) -> ScheduleExport:
    """Portable config for this schedule — the credential and index are
    resolved to their names, not the ids, so the result can be imported into a
    different environment where those ids won't match."""
    s = _get_or_404(db, sid)
    cred = db.get(Last9Credential, s.credential_id)
    idx = db.get(IndexTarget, s.index_target_id)
    if cred is None or idx is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this schedule's credential or index no longer exists"
        )
    fs = s.filter_spec or {}
    s3_profile = db.get(S3Profile, s.s3_profile_id) if s.s3_profile_id else None
    return ScheduleExport(
        name=s.name,
        enabled=s.enabled,
        interval_seconds=s.interval_seconds,
        lookback_seconds=s.lookback_seconds,
        calendar_day=s.calendar_day,
        region_code=s.region_code,
        index=index_ref(idx),
        credential=credential_ref(cred),
        chunk_hours=s.chunk_hours,
        id_batch_size=s.id_batch_size,
        output_format=s.output_format,
        phrases=fs.get("phrases", []),
        ids=fs.get("ids", []),
        exact_phrases=fs.get("exact_phrases", []),
        exclude_phrases=fs.get("exclude_phrases", []),
        exclude_exact_phrases=fs.get("exclude_exact_phrases", []),
        customer=fs.get("customer", ""),
        aggregation=fs.get("aggregation"),
        alert_recipients=s.alert_recipients,
        bq_config=BQConfig(**s.bq_config) if s.bq_config else None,
        s3_profile=S3ProfileRef(name=s3_profile.name) if s3_profile else None,
    )


@router.patch("/{sid}", response_model=ScheduleOut)
def update_schedule(sid: int, body: ScheduleUpdate, db: Session = Depends(get_db)) -> ScheduleOut:
    s = _get_or_404(db, sid)
    if body.name is not None:
        s.name = body.name
    if body.interval_seconds is not None:
        s.interval_seconds = body.interval_seconds
    if body.lookback_seconds is not None:
        s.lookback_seconds = body.lookback_seconds
    if body.calendar_day is not None:
        s.calendar_day = body.calendar_day
    if body.alert_recipients is not None:
        s.alert_recipients = body.alert_recipients
    if body.bq_config is not None:
        s.bq_config = body.bq_config.model_dump()
    if "s3_profile_id" in body.model_fields_set:
        profile = s3.profile_or_422(db, body.s3_profile_id)
        s.s3_profile_id = profile.id if profile else None
    if body.aggregation is not None:
        _check_aggregation(body.aggregation)
    if (
        body.phrases is not None
        or body.ids is not None
        or body.exclude_phrases is not None
        or body.exclude_exact_phrases is not None
        or body.aggregation is not None
    ):
        spec = dict(s.filter_spec)
        if body.phrases is not None:
            spec["phrases"] = body.phrases
        if body.ids is not None:
            spec["ids"] = body.ids
        if body.exclude_phrases is not None:
            spec["exclude_phrases"] = body.exclude_phrases
        if body.exclude_exact_phrases is not None:
            spec["exclude_exact_phrases"] = body.exclude_exact_phrases
        if body.aggregation is not None:
            spec["aggregation"] = body.aggregation.model_dump()
        s.filter_spec = spec
        register_aggregation_pattern(
            db,
            aggregation=body.aggregation.model_dump() if body.aggregation else None,
            source_name=s.name,
            source_kind="schedule",
            source_id=s.id,
        )
    db.commit()
    db.refresh(s)
    return _with_last_job([s], db)[0]


@router.post("/{sid}/toggle", response_model=ScheduleOut)
def toggle_schedule(sid: int, db: Session = Depends(get_db)) -> Schedule:
    s = _get_or_404(db, sid)
    s.enabled = not s.enabled
    db.commit()
    db.refresh(s)
    return s


@router.delete("/{sid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    sid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    db.delete(_get_or_404(db, sid))
    audit.record(db, "delete", "schedule", sid, user_id=user.email)
    db.commit()
