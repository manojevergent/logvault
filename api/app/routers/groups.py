"""Group extraction: one shared window, one job per saved search.

The group is deliberately thin: it stores the shared window/settings and is the
id its jobs point at. Status, counts and rows are always derived from those
jobs, so a group can never claim more than its runs actually did.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, s3
from app.database import get_db
from app.deps import get_current_user
from app.models import ExtractionGroup, IndexTarget, Job, Last9Credential, User
from app.routers.jobs import (
    MAX_BATCH_ITEMS,
    _new_job_row,
    _resolve_batch_plans,
    _to_out,
)
from app.schemas import (
    GroupCreate,
    GroupDetail,
    GroupStatus,
    GroupSummary,
)

router = APIRouter(prefix="/groups", tags=["groups"])

ACTIVE_STATUSES = ("queued", "running", "paused")


def _group_status(jobs: list[Job]) -> GroupStatus:
    statuses = [job.status for job in jobs]
    if any(s in ("running", "paused") for s in statuses):
        return "running"
    if any(s == "queued" for s in statuses):
        return "queued"
    if statuses and all(s == "failed" for s in statuses):
        return "failed"
    if statuses and all(s == "canceled" for s in statuses):
        return "canceled"
    if any(s in ("failed", "canceled") for s in statuses):
        return "partial"
    return "completed"


def _summary(group: ExtractionGroup, jobs: list[Job]) -> GroupSummary:
    return GroupSummary(
        id=group.id,
        name=group.name,
        status=_group_status(jobs),
        created_by=group.created_by,
        created_at=group.created_at,
        start_epoch=group.start_epoch,
        end_epoch=group.end_epoch,
        is_preview=bool(group.is_preview),
        parent_group_id=group.parent_group_id,
        total_jobs=len(jobs),
        completed=sum(1 for job in jobs if job.status == "completed"),
        failed=sum(1 for job in jobs if job.status == "failed"),
        canceled=sum(1 for job in jobs if job.status == "canceled"),
        running=sum(1 for job in jobs if job.status in ("running", "paused")),
        queued=sum(1 for job in jobs if job.status == "queued"),
        rows_written=sum(int(job.rows_written or 0) for job in jobs),
    )


def _jobs_for(db: Session, group_id: int) -> list[Job]:
    return list(db.scalars(select(Job).where(Job.group_id == group_id).order_by(Job.id)))


def _detail(db: Session, group: ExtractionGroup) -> GroupDetail:
    jobs = _jobs_for(db, group.id)
    cred_ids = {job.credential_id for job in jobs}
    labels: dict[int, str] = {}
    if cred_ids:
        labels = dict(
            db.execute(
                select(Last9Credential.id, Last9Credential.label).where(
                    Last9Credential.id.in_(cred_ids)
                )
            ).all()
        )
    return GroupDetail(
        **_summary(group, jobs).model_dump(),
        jobs=[_to_out(job, credential_label=labels.get(job.credential_id)) for job in jobs],
    )


def _get_or_404(db: Session, group_id: int) -> ExtractionGroup:
    group = db.get(ExtractionGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "group not found")
    return group


@router.get("", response_model=list[GroupSummary])
def list_groups(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[GroupSummary]:
    groups = (
        db.query(ExtractionGroup)
        .order_by(ExtractionGroup.created_at.desc(), ExtractionGroup.id.desc())
        .limit(limit)
        .all()
    )
    if not groups:
        return []
    jobs = list(
        db.scalars(select(Job).where(Job.group_id.in_([group.id for group in groups])))
    )
    by_group: dict[int, list[Job]] = {}
    for job in jobs:
        by_group.setdefault(job.group_id or 0, []).append(job)
    return [_summary(group, by_group.get(group.id, [])) for group in groups]


@router.get("/{group_id}", response_model=GroupDetail)
def get_group(group_id: int, db: Session = Depends(get_db)) -> GroupDetail:
    return _detail(db, _get_or_404(db, group_id))


@router.post("", response_model=GroupDetail, status_code=status.HTTP_201_CREATED)
def create_group(
    body: GroupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GroupDetail:
    if not body.items:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "select at least one saved search"
        )
    if len(body.items) > MAX_BATCH_ITEMS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"at most {MAX_BATCH_ITEMS} searches per group",
        )
    if body.end_epoch <= body.start_epoch:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "end must be after start")

    # Everything is validated before the group or any job exists, so a bad
    # source never leaves a half-created group behind.
    plans = _resolve_batch_plans(db, body.items, created_by=user.email)

    name = body.name.strip() or (
        f"Group · {len(plans)} search{'' if len(plans) == 1 else 'es'} · "
        f"{datetime.now(UTC):%d %b %Y %H:%M} UTC"
    )
    group = ExtractionGroup(
        name=name[:160],
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
            group_id=group.id,
        )
        for tpl, agg, credential_id, index_target_id, region_code, s3_profile in plans
    ]
    db.add_all(jobs)
    db.flush()

    audit.record(
        db,
        "create",
        "group",
        group.id,
        {"name": group.name, "jobs": len(jobs)},
        user_id=user.email,
    )
    for job in jobs:
        audit.record(
            db,
            "create",
            "job",
            job.id,
            {"group_id": group.id, "label": (job.filter_spec or {}).get("label")},
            user_id=user.email,
        )
    from app.outbox import enqueue as enqueue_dispatch

    for job in jobs:
        enqueue_dispatch(db, job.id)
    db.commit()
    db.refresh(group)
    for job in jobs:
        db.refresh(job)

    from app.tasks_client import dispatch_job  # local: keeps this router import-light

    for job in jobs:
        dispatch_job(job.id)
    return _detail(db, group)


@router.post("/{group_id}/cancel", response_model=GroupDetail)
def cancel_group(
    group_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GroupDetail:
    group = _get_or_404(db, group_id)
    canceled = 0
    for job in _jobs_for(db, group.id):
        if job.status not in ACTIVE_STATUSES:
            continue
        job.status = "canceled"
        audit.record(db, "cancel", "job", job.id, {"group_id": group.id}, user_id=user.email)
        canceled += 1
    audit.record(
        db,
        "cancel",
        "group",
        group.id,
        {"jobs": canceled},
        user_id=user.email,
    )
    db.commit()
    db.refresh(group)
    return _detail(db, group)


@router.post("/{group_id}/retry", response_model=GroupDetail, status_code=status.HTTP_201_CREATED)
def retry_group(
    group_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GroupDetail:
    """Re-run the failed/canceled jobs as a new group with the same settings.

    A new group rather than reusing this one: the original failures stay in the
    history, and the retry has its own progress and parent link.
    """
    group = _get_or_404(db, group_id)
    failed = [
        job for job in _jobs_for(db, group.id) if job.status in ("failed", "canceled")
    ]
    if not failed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "this group has no failed or canceled jobs to retry",
        )

    plans: list[tuple[Job, int]] = []
    for job in failed:
        idx = db.get(IndexTarget, job.index_target_id)
        if idx is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"index for {(job.filter_spec or {}).get('label') or f'job {job.id}'} no longer exists",
            )
        credential_id = job.credential_id
        if db.get(Last9Credential, credential_id) is None:
            credential_id = idx.credential_id
        if credential_id is None or db.get(Last9Credential, credential_id) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"credential for {(job.filter_spec or {}).get('label') or f'job {job.id}'} no longer exists",
            )
        plans.append((job, credential_id))

    retry = ExtractionGroup(
        name=f"{group.name} (retry)"[:160],
        created_by=user.email,
        start_epoch=group.start_epoch,
        end_epoch=group.end_epoch,
        chunk_hours=group.chunk_hours,
        id_batch_size=group.id_batch_size,
        output_format=group.output_format,
        is_preview=group.is_preview,
        parent_group_id=group.id,
    )
    db.add(retry)
    db.flush()

    clones = [
        Job(
            status="queued",
            region_code=job.region_code,
            index_target_id=job.index_target_id,
            credential_id=credential_id,
            start_epoch=job.start_epoch,
            end_epoch=job.end_epoch,
            chunk_hours=job.chunk_hours,
            id_batch_size=job.id_batch_size,
            filter_spec=job.filter_spec,
            output_format=job.output_format,
            is_preview=job.is_preview,
            s3_profile_id=job.s3_profile_id,
            s3_destination=job.s3_destination,
            created_by=user.email,
            group_id=retry.id,
        )
        for job, credential_id in plans
    ]
    db.add_all(clones)
    db.flush()

    audit.record(
        db,
        "retry",
        "group",
        retry.id,
        {"from_group": group.id, "jobs": len(clones)},
        user_id=user.email,
    )
    for clone, (original, _cred) in zip(clones, plans, strict=True):
        audit.record(
            db,
            "retry",
            "job",
            clone.id,
            {"from_job": original.id, "group_id": retry.id},
            user_id=user.email,
        )
    from app.outbox import enqueue as enqueue_dispatch

    for clone in clones:
        enqueue_dispatch(db, clone.id)
    db.commit()
    db.refresh(retry)
    for clone in clones:
        db.refresh(clone)

    from app.tasks_client import dispatch_job

    for clone in clones:
        dispatch_job(clone.id)
    return _detail(db, retry)
