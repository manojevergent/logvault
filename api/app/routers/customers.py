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


def _remove_job_artifacts(
    job_id: int,
    recorded_paths: tuple[str | None, ...],
    customer: str,
    storage_dir: str,
) -> int:
    """Everything a job wrote: the recorded paths plus the conventional names.

    Preview runs never store `output_file_path`, so relying on the column alone
    would leave their CSV on disk forever.
    """
    removed = 0
    for path in recorded_paths:
        removed += _remove_file(path)

    bases = [storage_dir]
    segment = _customer_segment(customer)
    if segment:
        bases.append(os.path.join(storage_dir, segment))
    for base in bases:
        for name in (
            f"job_{job_id}.csv",
            f"job_{job_id}.jsonl",
            f"job_{job_id}.summary.csv",
            f"job_{job_id}.counts.csv",
            f"job_{job_id}.unmatched.csv",
            f"job_{job_id}.distinct.sqlite",
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

    # Only the columns the match and the file cleanup need. Loading whole Job
    # entities pulled filter_spec, preview, aggregation_result and checkpoint for
    # every row — tens of MB once the job table is large — to delete one customer.
    rows = (
        db.execute(
            select(
                Job.id,
                Job.status,
                Job.output_file_path,
                Job.summary_file_path,
                Job.counts_file_path,
                Job.unmatched_file_path,
                Job.filter_spec["customer"].as_string().label("filter_customer"),
                Job.filter_spec["label"].as_string().label("filter_label"),
            ).order_by(Job.id)
        )
        .mappings()
        .all()
    )

    def customer_of_row(row) -> str:
        return (
            (row["filter_customer"] or "").strip()
            or (row["filter_label"] or "").strip()
            or UNASSIGNED
        )

    targets = [r for r in rows if customer_of_row(r) == customer]
    if not targets:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no jobs belong to customer {customer!r}")

    active = [r for r in targets if r["status"] in _ACTIVE]
    if active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{len(active)} job(s) for {customer!r} are still queued, running or paused — "
            "cancel them first",
        )

    storage_dir = get_settings().storage_dir
    files = 0
    target_ids = [r["id"] for r in targets]
    for row in targets:
        files += _remove_job_artifacts(
            row["id"],
            (
                row["output_file_path"],
                row["summary_file_path"],
                row["counts_file_path"],
                row["unmatched_file_path"],
            ),
            customer,
            storage_dir,
        )
    # One delete per table instead of one per job.
    db.query(JobEvent).filter(JobEvent.job_id.in_(target_ids)).delete(synchronize_session=False)
    db.query(Job).filter(Job.id.in_(target_ids)).delete(synchronize_session=False)

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
