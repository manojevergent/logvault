"""Dispatch accounting: a publish counts only when the database confirms it."""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.outbox import dispatch_once, mark_published


def _outbox_row(conn, job_id=1, status="pending"):
    # next_attempt_at must be due: a NULL value is not <= now() in SQL, so the
    # row would never be claimed and the test would pass vacuously.
    conn.execute(db.job_dispatch_outbox.insert().values(
        job_id=job_id, task_name="logvault.run_job", status=status, attempts=0,
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=5)))


def _claim_all(conn, owner):
    conn.execute(
        sa.update(db.job_dispatch_outbox).values(locked_by=owner)
    )


def test_mark_published_confirms_the_transition(worker_db):
    with worker_db.engine().begin() as conn:
        _outbox_row(conn)
        _claim_all(conn, "d1")
        assert mark_published(conn, 1, "d1") is True
    with worker_db.engine().begin() as conn:
        row = conn.execute(sa.select(db.job_dispatch_outbox)).mappings().one()
    assert row["status"] == "published"
    assert row["published_at"] is not None


def test_mark_published_twice_is_not_counted_twice(worker_db):
    with worker_db.engine().begin() as conn:
        _outbox_row(conn)
        _claim_all(conn, "d1")
        assert mark_published(conn, 1, "d1") is True
        assert mark_published(conn, 1, "d1") is False


def test_mark_published_requires_ownership(worker_db):
    with worker_db.engine().begin() as conn:
        _outbox_row(conn)
        _claim_all(conn, "d1")
        assert mark_published(conn, 1, "someone-else") is False
    with worker_db.engine().begin() as conn:
        row = conn.execute(sa.select(db.job_dispatch_outbox)).mappings().one()
    assert row["status"] == "pending"


def test_dispatch_totals_match_database_state(worker_db):
    with worker_db.engine().begin() as conn:
        for i in range(5):
            _outbox_row(conn, job_id=100 + i)

    sent = []
    stats = dispatch_once(worker_db.engine(), lambda t, j: sent.append(j))
    with worker_db.engine().begin() as conn:
        published = conn.execute(
            sa.select(sa.func.count()).select_from(db.job_dispatch_outbox).where(
                db.job_dispatch_outbox.c.status == "published"
            )
        ).scalar()

    assert stats["failed"] == 0
    assert stats["lost_update"] == 0
    assert stats["published"] == published == 5
    assert len(sent) == 5


def test_failed_conditional_update_is_not_reported_as_published(worker_db, monkeypatch):
    """If the confirmation UPDATE matches nothing, the row is not a publish."""
    import app.outbox as outbox_mod

    with worker_db.engine().begin() as conn:
        _outbox_row(conn)

    monkeypatch.setattr(outbox_mod, "mark_published", lambda conn, row_id, owner: False)
    stats = dispatch_once(worker_db.engine(), lambda t, j: None)

    assert stats["claimed"] == 1
    assert stats["published"] == 0
    assert stats["lost_update"] == 1


def test_publish_failure_increments_attempts_and_stays_pending(worker_db):
    with worker_db.engine().begin() as conn:
        _outbox_row(conn)

    def boom(task, job_id):
        raise RuntimeError("broker down")

    stats = dispatch_once(worker_db.engine(), boom)
    with worker_db.engine().begin() as conn:
        row = conn.execute(sa.select(db.job_dispatch_outbox)).mappings().one()

    assert stats["failed"] == 1 and stats["published"] == 0
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["last_error"].startswith("RuntimeError")
