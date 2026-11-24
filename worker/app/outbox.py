"""Dispatch outbox - worker side.

The dispatcher is the only component that turns durable intent into a Celery
message. It claims due rows with FOR UPDATE SKIP LOCKED, publishes outside the
transaction, then records the result. A crash between publish and mark leaves a
row reclaimable once ``locked_until`` expires, so the message is re-sent rather
than lost -- and duplicate messages are harmless because the worker claim is
fenced.
"""

from __future__ import annotations

import os
import random
import socket
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy import and_, or_, select, update

from app import db
from app.celery_app import celery

MAX_ATTEMPTS = 12
BASE_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 300


def _owner_id() -> str:
    return f"dispatcher:{socket.gethostname()}:{os.getpid()}"[:128]


def _backoff(attempts: int) -> timedelta:
    raw = min(BASE_BACKOFF_SECONDS * (2 ** max(0, attempts - 1)), MAX_BACKOFF_SECONDS)
    jitter = raw * random.uniform(-0.2, 0.2)
    return timedelta(seconds=max(1.0, raw + jitter))


def enqueue(conn, job_id: int, task_name: str = "logvault.run_job") -> None:
    """Write dispatch intent for a job inside the caller's transaction.

    The API has its own copy (``api/app/outbox.py``); the worker needs one too,
    because ``scan_schedules`` creates jobs without going through the API. A
    scheduled job used to be nothing but a Celery ``delay()``, so a broker hiccup
    left the row ``queued`` with no redelivery owed and the window silently
    skipped. Committing the intent with the job makes the obligation durable.
    """
    o = db.job_dispatch_outbox
    now = datetime.now(UTC)
    conn.execute(
        o.insert().values(
            job_id=job_id,
            task_name=task_name,
            payload={},
            status="pending",
            attempts=0,
            next_attempt_at=now,
            created_at=now,
        )
    )


def claim_due(conn, owner: str, batch: int = 100, lock_seconds: int = 60) -> list[dict]:
    """Reserve up to ``batch`` due rows. Postgres only; SKIP LOCKED is the point."""
    o = db.job_dispatch_outbox
    now = sa.func.now()
    due = and_(
        o.c.status == "pending",
        o.c.next_attempt_at <= now,
        or_(o.c.locked_until.is_(None), o.c.locked_until < now),
    )
    stmt = select(o.c.id).where(due).order_by(o.c.next_attempt_at).limit(batch)
    if conn.dialect.name == "postgresql":
        # SKIP LOCKED is the point on Postgres; SQLite (test database) has no
        # FOR UPDATE and would reject the statement outright.
        stmt = stmt.with_for_update(skip_locked=True)
    ids = conn.execute(stmt).scalars().all()
    if not ids:
        return []
    conn.execute(
        update(o)
        .where(o.c.id.in_(ids))
        .values(
            locked_by=owner,
            locked_until=datetime.now(UTC) + timedelta(seconds=int(lock_seconds)),
        )
    )
    return [
        dict(r)
        for r in conn.execute(
            select(o.c.id, o.c.job_id, o.c.task_name).where(o.c.id.in_(ids))
        ).mappings()
    ]


def mark_published(conn, row_id: int, owner: str) -> bool:
    """Confirm the publish transition. False means the database disagreed.

    The conditional UPDATE is the authority: if the row was already published,
    re-locked by another dispatcher, or never held by ``owner``, zero rows change
    and the caller must not count it as a success.
    """
    o = db.job_dispatch_outbox
    result = conn.execute(
        update(o)
        .where(
            o.c.id == row_id,
            o.c.locked_by == owner,
            o.c.status == "pending",
        )
        .values(status="published", published_at=sa.func.now(), last_error=None, locked_by=None, locked_until=None)
    )
    return result.rowcount == 1


def mark_failed(conn, row_id: int, owner: str, error: str) -> bool:
    """Record a publish failure. False means the row was no longer ours.

    The UPDATE is the authority: it only touches a row this dispatcher still
    holds and that is still pending. Without those two conditions a row another
    dispatcher already published could be pushed back to ``pending`` and sent
    twice. ``attempts`` is incremented in the database so two failing dispatchers
    cannot both read the same value and write the same total.
    """
    o = db.job_dispatch_outbox
    # The backoff interval is computed from the previous count; only the rare
    # case of two dispatchers failing the same row can make it one step short,
    # which delays the next try by less than intended rather than losing one.
    attempts = conn.execute(select(o.c.attempts).where(o.c.id == row_id)).scalar_one()
    result = conn.execute(
        update(o)
        .where(o.c.id == row_id, o.c.locked_by == owner, o.c.status == "pending")
        .values(
            attempts=o.c.attempts + 1,
            status=sa.case(
                (o.c.attempts + 1 >= MAX_ATTEMPTS, "dead"),
                else_="pending",
            ),
            last_error=error[:2000],
            next_attempt_at=datetime.now(UTC) + _backoff(attempts + 1),
            locked_by=None,
            locked_until=None,
        )
    )
    return result.rowcount == 1


def dispatch_once(engine, publisher, batch: int = 100) -> dict:
    """One dispatcher tick. ``publisher`` is injectable so this is testable."""
    owner = _owner_id()
    # `lost_update` is a row the broker accepted but the database refused to
    # confirm. It must never be reported as published.
    stats = {"claimed": 0, "published": 0, "failed": 0, "lost_update": 0, "not_owned": 0}
    with engine.begin() as conn:
        rows = claim_due(conn, owner, batch=batch)
    stats["claimed"] = len(rows)
    for row in rows:
        try:
            publisher(row["task_name"], row["job_id"])
        except Exception as exc:  # noqa: BLE001 - a publish failure must not stop the batch
            with engine.begin() as conn:
                owned = mark_failed(conn, row["id"], owner, f"{type(exc).__name__}: {exc}")
            stats["failed"] += 1
            if not owned:
                # The row was published or re-claimed by another dispatcher while
                # this attempt was failing. The obligation is no longer ours.
                stats["not_owned"] += 1
        else:
            with engine.begin() as conn:
                confirmed = mark_published(conn, row["id"], owner)
            if confirmed:
                stats["published"] += 1
            else:
                stats["lost_update"] += 1
    return stats


def publish(task_name: str, job_id: int) -> None:
    celery.send_task(task_name, args=[job_id])


@celery.task(name="logvault.publish_outbox")
def publish_outbox() -> dict:
    return dispatch_once(db.engine(), publish)
