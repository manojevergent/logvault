"""Customers.

A customer is not a table: it is the `filter_spec.customer` written on a job
(falling back to the search label, which is how the Customers page groups them).
Deleting one therefore means deleting that customer's jobs, along with the
files and distinct-value stores those jobs left on disk.
"""

from __future__ import annotations

import contextlib
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Job, JobEvent, User
from app.schemas import CustomerDeleteResult

router = APIRouter(prefix="/customers", tags=["customers"])

# Same derivation as web/app/customers/page.tsx, so "delete this row" removes
# exactly the jobs the row was counting.
UNASSIGNED = "(unassigned)"
_ACTIVE = ("queued", "running", "paused")


def customer_of(job: Job) -> str:
    spec = job.filter_spec or {}
    return (spec.get("customer") or "").strip() or (spec.get("label") or "").strip() or UNASSIGNED


def _remove_file(path: str | None) -> int:
    """Delete a path and its compressed/plain twin. Returns files removed."""
    if not path:
        return 0
    candidates = {path}
    candidates.add(path[:-4] if path.endswith(".zip") else f"{path}.zip")
    removed = 0
    for candidate in candidates:
        if os.path.exists(candidate):
            with contextlib.suppress(OSError):
                os.remove(candidate)
                removed += 1
    return removed


# Mirrors worker/app/runner.py: a customer name is reduced to one path segment
# before it is ever used as a directory.
_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _customer_segment(customer: str) -> str:
    return _UNSAFE_PATH_CHARS.sub("_", customer).strip("._-")


def _remove_job_artifacts(job: Job, customer: str, storage_dir: str) -> int:
    """Everything a job wrote: the recorded paths plus the conventional names.

    Preview runs never store `output_file_path`, so relying on the column alone
    would leave their CSV on disk forever.
    """
    removed = 0
    for path in (job.output_file_path, job.summary_file_path, job.counts_file_path):
        removed += _remove_file(path)

    bases = [storage_dir]
    segment = _customer_segment(customer)
    if segment:
        bases.append(os.path.join(storage_dir, segment))
    for base in bases:
        for name in (
            f"job_{job.id}.csv",
            f"job_{job.id}.jsonl",
            f"job_{job.id}.summary.csv",
            f"job_{job.id}.counts.csv",
            f"job_{job.id}.distinct.sqlite",
        ):
            removed += _remove_file(os.path.join(base, name))
    return removed


@router.delete("", response_model=CustomerDeleteResult)
def delete_customer(
    name: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CustomerDeleteResult:
    customer = name.strip()
    if not customer:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "customer name is required")
    if customer == UNASSIGNED:
        # It is a bucket, not a customer: deleting it would wipe every job that
        # simply has no customer set.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "the unassigned bucket is not a customer — delete those jobs individually",
        )

    jobs = db.scalars(select(Job).order_by(Job.id)).all()
    targets = [j for j in jobs if customer_of(j) == customer]
    if not targets:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no jobs belong to customer {customer!r}")

    active = [j for j in targets if j.status in _ACTIVE]
    if active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{len(active)} job(s) for {customer!r} are still queued, running or paused — "
            "cancel them first",
        )

    storage_dir = get_settings().storage_dir
    files = 0
    for job in targets:
        files += _remove_job_artifacts(job, customer, storage_dir)
        db.query(JobEvent).filter(JobEvent.job_id == job.id).delete(synchronize_session=False)
        db.delete(job)

    audit.record(
        db,
        "delete",
        "customer",
        None,
        {"customer": customer, "jobs": len(targets), "files": files},
        user_id=user.email,
    )
    db.commit()
    return CustomerDeleteResult(customer=customer, deleted_jobs=len(targets), deleted_files=files)
