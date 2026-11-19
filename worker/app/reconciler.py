"""Lease-expiry reconciliation.

Database-driven, not message-driven: a crashed worker needs no message to be
recovered, because the database knows the lease expired. Each decision is made
inside one transaction with FOR UPDATE SKIP LOCKED, so concurrent reconcilers
cannot double-act.

Order matters: user intent (cancel, pause) beats recovery; recovery beats a
retry cap only when attempts remain.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import and_, select, update

from app import db
from app.celery_app import celery

MAX_REDISPATCHES = 6
TASK_NAME = "logvault.run_job"


def _expired(limit: int):
    return (
        select(db.jobs.c.id, db.jobs.c.lease_token, db.jobs.c.cancel_requested_at,
               db.jobs.c.pause_requested_at)
        .where(
            db.jobs.c.status == "running",
            db.jobs.c.lease_expires_at.isnot(None),
            db.jobs.c.lease_expires_at < sa.func.now(),
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def _outbox_attempts(conn, job_id: int) -> int:
    return conn.execute(
        select(db.job_dispatch_outbox.c.attempts).where(
            db.job_dispatch_outbox.c.job_id == job_id,
            db.job_dispatch_outbox.c.task_name == TASK_NAME,
        )
    ).scalar_one_or_none() or 0


def _reopen_outbox(conn, job_id: int) -> None:
    o = db.job_dispatch_outbox
    conn.execute(
        update(o)
        .where(o.c.job_id == job_id, o.c.task_name == TASK_NAME)
        .values(status="pending", next_attempt_at=sa.func.now(), locked_by=None, locked_until=None)
    )


def reconcile_once(engine, limit: int = 50, max_redispatches: int = MAX_REDISPATCHES) -> dict:
    stats = {"expired": 0, "redispatched": 0, "canceled": 0, "paused": 0, "failed": 0}
    with engine.begin() as conn:
        rows = conn.execute(_expired(limit)).mappings().all()
        stats["expired"] = len(rows)
        for row in rows:
            job_id = row["id"]
            if row["cancel_requested_at"] is not None:
                conn.execute(
                    update(db.jobs)
                    .where(db.jobs.c.id == job_id, db.jobs.c.lease_token == row["lease_token"])
                    .values(status="canceled", owner_id=None, lease_expires_at=None,
                            finished_at=sa.func.now())
                )
                db.add_event(conn, job_id, "Lease expired after cancel request; job canceled", "warn")
                stats["canceled"] += 1
                continue
            if row["pause_requested_at"] is not None:
                conn.execute(
                    update(db.jobs)
                    .where(db.jobs.c.id == job_id, db.jobs.c.lease_token == row["lease_token"])
                    .values(status="paused", owner_id=None, lease_expires_at=None)
                )
                db.add_event(conn, job_id, "Lease expired after pause request; job paused", "warn")
                stats["paused"] += 1
                continue
            if _outbox_attempts(conn, job_id) >= max_redispatches:
                conn.execute(
                    update(db.jobs)
                    .where(db.jobs.c.id == job_id, db.jobs.c.lease_token == row["lease_token"])
                    .values(status="failed", owner_id=None, lease_expires_at=None,
                            error_message="retry_exhausted: lease expired too many times",
                            finished_at=sa.func.now())
                )
                db.add_event(conn, job_id, "Retry exhausted after repeated lease expiry", "error")
                stats["failed"] += 1
                continue
            # Fence the dead owner immediately, before any new claim can occur.
            conn.execute(
                update(db.jobs)
                .where(db.jobs.c.id == job_id, db.jobs.c.lease_token == row["lease_token"])
                .values(lease_token=sa.func.coalesce(db.jobs.c.lease_token, 0) + 1, owner_id=None,
                        lease_expires_at=None)
            )
            _reopen_outbox(conn, job_id)
            db.add_event(conn, job_id, "Lease expired; redispatched", "warn")
            stats["redispatched"] += 1
    return stats


@celery.task(name="logvault.reconcile_leases")
def reconcile_leases() -> dict:
    return reconcile_once(db.engine())
