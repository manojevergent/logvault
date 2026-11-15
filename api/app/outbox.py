"""Transactional dispatch outbox - API side.

Dispatch intent is written in the same transaction as the job row, so a broker
outage cannot lose work. The worker-side dispatcher republishes from the
database; Celery delivery is never the only record that work is owed.

Called before ``session.commit()`` so the row and the job commit together.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import JobDispatchOutbox

RUN_JOB = "logvault.run_job"


def enqueue(session: Session, job_id: int, task_name: str = RUN_JOB) -> None:
    """Upsert one pending dispatch row for this job and task.

    Idempotent: a resume or retry for the same job reuses the row instead of
    creating a second one, which the unique constraint would reject anyway.
    """
    row = (
        session.query(JobDispatchOutbox)
        .filter(
            JobDispatchOutbox.job_id == job_id,
            JobDispatchOutbox.task_name == task_name,
        )
        .one_or_none()
    )
    if row is None:
        session.add(
            JobDispatchOutbox(job_id=job_id, task_name=task_name, status="pending")
        )
        return
    row.status = "pending"
    row.next_attempt_at = func.now()
    row.locked_by = None
    row.locked_until = None
