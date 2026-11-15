"""Attempt-scoped artifacts and atomic publication.

A worker's attempt identity is ``(job_id, lease_token)``. The token is already
monotonic per job, so it doubles as the attempt number without an extra column.

Two rules make publication safe:

* Every attempt writes into its own directory, so a retry can never overwrite
  the previous attempt's output.
* The database pointer update is the commit. A file on disk or an object in S3
  is unpublished until that guarded UPDATE succeeds, and the same UPDATE is
  what marks the job terminal - so a crash between the two leaves the previous
  published pointer intact.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import update

from app import db

# Columns a publication may write. Anything else is ignored rather than
# silently broadening what a publish can change.
PUBLISHABLE = frozenset(
    {
        "status",
        "finished_at",
        "output_file_path",
        "summary_file_path",
        "counts_file_path",
        "unmatched_file_path",
        "s3_uri",
        "s3_summary_uri",
        "s3_counts_uri",
        "s3_error",
        "s3_uploaded_at",
        "s3_manifest_uri",
        "s3_published_attempt",
        "preview",
        "rows_written",
        "completed_chunks",
        "total_chunks",
        "aggregation_result",
        "store_path",
        "completion_state",
        "gap_count",
        "gap_reason",
        "error_message",
    }
)


def attempt_dir(storage_dir: str, job_id: int, token: int) -> str:
    """Directory for one attempt. Never shared between tokens."""
    return os.path.join(storage_dir, "exports", f"job_{job_id}", f"a{int(token)}")


def artifact_path(storage_dir: str, job_id: int, token: int, kind: str, ext: str = "csv") -> str:
    """Path for one artifact within an attempt namespace."""
    if kind == "raw":
        name = f"job_{job_id}.{ext}"
    else:
        name = f"job_{job_id}.{kind}.csv"
    return os.path.join(attempt_dir(storage_dir, job_id, token), name)


def ensure_attempt_dir(storage_dir: str, job_id: int, token: int) -> str:
    path = Path(attempt_dir(storage_dir, job_id, token))
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def publish(conn, job_id: int, token: int, owner: str | None, **pointers) -> bool:
    """Commit the publication, or return False.

    Guarded by lease token, owner, and a non-terminal status, so a stale worker,
    a superseded token, or a second publisher all affect zero rows. Callers must
    not claim completion when this returns False.
    """
    payload = {k: v for k, v in pointers.items() if k in PUBLISHABLE}
    if not payload:
        return False
    stmt = (
        update(db.jobs)
        .where(
            db.jobs.c.id == job_id,
            db.jobs.c.lease_token == token,
            db.jobs.c.status == "running",
        )
    )
    if owner is not None:
        stmt = stmt.where(db.jobs.c.owner_id == owner)
    result = conn.execute(stmt.values(**payload))
    return result.rowcount == 1
