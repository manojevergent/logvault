"""Fenced job writes.

PostgreSQL is the execution authority: every mutation of a job row must carry
the lease token the writer won at claim time. A superseded worker's update
matches no row, so it cannot overwrite the current owner's state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy import and_, or_, update

from app import db

TERMINAL = ("completed", "failed", "canceled")


class LeaseLost(RuntimeError):
    """The writer no longer owns the job; it must stop, not retry blindly."""


def claim(conn, job_id: int, owner_id: str, ttl_seconds: int = 60) -> int | None:
    """Win the job, or return None.

    The whole claim is one conditional UPDATE: PostgreSQL decides the winner,
    so duplicate Celery deliveries cannot both proceed. Cancelling intent wins
    over a claim. An expired lease is reclaimable; a live one is not.
    """
    stmt = (
        update(db.jobs)
        .where(
            db.jobs.c.id == job_id,
            db.jobs.c.status.in_(("queued", "running")),
            db.jobs.c.cancel_requested_at.is_(None),
            or_(
                db.jobs.c.status == "queued",
                # Stale: the reconciler fenced it (token bumped, owner and lease
                # cleared) but left it "running". Requiring token > 0 and no
                # owner keeps legacy pre-P1 rows -- which also have a NULL lease
                # -- from being stolen.
                and_(
                    db.jobs.c.status == "running",
                    db.jobs.c.lease_expires_at.is_(None),
                    db.jobs.c.owner_id.is_(None),
                    sa.func.coalesce(db.jobs.c.lease_token, 0) > 0,
                ),
                and_(
                    db.jobs.c.status == "running",
                    db.jobs.c.lease_expires_at.isnot(None),
                    db.jobs.c.lease_expires_at < sa.func.now(),
                ),
            ),
        )
        .values(
            status="running",
            owner_id=owner_id,
            lease_token=sa.func.coalesce(db.jobs.c.lease_token, 0) + 1,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=int(ttl_seconds)),
            heartbeat_at=sa.func.now(),
            progress_at=sa.func.now(),
        )
        .returning(db.jobs.c.lease_token)
    )
    return conn.execute(stmt).scalar_one_or_none()


def fenced_update(conn, job_id: int, token: int, **values) -> bool:
    """Apply ``values`` only if ``token`` is still the current lease token."""
    result = conn.execute(
        update(db.jobs)
        .where(db.jobs.c.id == job_id, db.jobs.c.lease_token == token)
        .values(**values)
    )
    return result.rowcount == 1


def fenced_terminal(conn, job_id: int, token: int, **values) -> bool:
    """Terminal write: fenced, and refused if the job is already terminal."""
    result = conn.execute(
        update(db.jobs)
        .where(
            db.jobs.c.id == job_id,
            db.jobs.c.lease_token == token,
            db.jobs.c.status.not_in(TERMINAL),
        )
        .values(**values)
    )
    return result.rowcount == 1


def renew_progress(conn, job_id: int, token: int, ttl_seconds: int = 60) -> bool:
    """Heartbeat that also extends the lease. Only call when work advanced."""
    result = conn.execute(
        update(db.jobs)
        .where(db.jobs.c.id == job_id, db.jobs.c.lease_token == token)
        .values(
            heartbeat_at=sa.func.now(),
            progress_at=sa.func.now(),
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=int(ttl_seconds)),
        )
    )
    return result.rowcount == 1


def heartbeat_only(conn, job_id: int, token: int) -> bool:
    """Liveness without progress: visible in diagnostics, lease NOT extended."""
    result = conn.execute(
        update(db.jobs)
        .where(db.jobs.c.id == job_id, db.jobs.c.lease_token == token)
        .values(heartbeat_at=sa.func.now())
    )
    return result.rowcount == 1
