"""LeaseKeeper: renewal that does not depend on row delivery.

The defect these tests exist for: renewal used to happen only when the runner
yielded a row, so a blocking extraction call longer than the TTL let the lease
expire while the worker was healthy.
"""

import time

from app import db, fenced
from app.heartbeat import LeaseKeeper

JOB = 1


def _seed(engine):
    with engine.begin() as c:
        c.execute(db.jobs.delete().where(db.jobs.c.id == JOB))
        c.execute(db.jobs.insert().values(
            id=JOB, status="queued", region_code="r", index_target_id=1,
            credential_id=1, start_epoch=0, end_epoch=1, chunk_hours=1,
            id_batch_size=100, filter_spec={}, rows_written=0, total_chunks=1,
            completed_chunks=0, output_format="csv", is_preview=False,
            lease_token=0, completion_state="unknown", gap_count=0,
            checkpoint_version=1))


def _row(engine):
    with engine.begin() as c:
        return c.execute(db.jobs.select().where(db.jobs.c.id == JOB)).mappings().one()


def _claim(engine, owner="w1"):
    with engine.begin() as c:
        return fenced.claim(c, JOB, owner)


def test_keeper_renews_without_any_rows_being_delivered(worker_db):
    _seed(worker_db.engine())
    token = _claim(worker_db.engine())

    before = _row(worker_db.engine())["lease_expires_at"]
    # ttl must exceed the claim's 60s default, otherwise "renewal" legitimately
    # shortens the expiry and the comparison proves nothing.
    keeper = LeaseKeeper(worker_db.engine(), JOB, token, ttl=120, interval=0.05)
    keeper.start()
    time.sleep(0.4)          # no rows, no progress() call, just wall clock
    keeper.stop()
    keeper.join(2)

    after = _row(worker_db.engine())["lease_expires_at"]
    assert after > before, "the lease must extend without row delivery"
    assert not keeper.lost.is_set()
    assert not keeper.is_alive(), "the keeper must not leak a thread"


def test_stale_token_stops_the_keeper(worker_db):
    _seed(worker_db.engine())
    first = _claim(worker_db.engine(), "w1")

    # A newer owner takes the job (expired lease -> reclaim).
    with worker_db.engine().begin() as c:
        c.execute(db.jobs.update().where(db.jobs.c.id == JOB).values(
            lease_expires_at=None, owner_id=None))
    second = _claim(worker_db.engine(), "w2")
    assert second == first + 1

    keeper = LeaseKeeper(worker_db.engine(), JOB, first, ttl=5, interval=0.05)
    keeper.start()
    keeper.join(2)

    assert keeper.lost.is_set(), "a superseded token must stop the keeper"
    assert not keeper.is_alive()


def test_terminal_job_lease_cannot_be_resurrected(worker_db):
    _seed(worker_db.engine())
    token = _claim(worker_db.engine())
    with worker_db.engine().begin() as c:
        fenced.fenced_terminal(c, JOB, token, status="completed",
                               lease_expires_at=None, owner_id=None)

    keeper = LeaseKeeper(worker_db.engine(), JOB, token, ttl=5, interval=0.05)
    keeper.start()
    keeper.join(2)

    row = _row(worker_db.engine())
    assert row["status"] == "completed"
    assert row["lease_expires_at"] is None, "a finished job must not get a lease back"
    assert keeper.lost.is_set()


def test_database_error_is_not_treated_as_lost_ownership(worker_db, monkeypatch):
    _seed(worker_db.engine())
    token = _claim(worker_db.engine())

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(fenced, "renew_progress", boom)
    keeper = LeaseKeeper(worker_db.engine(), JOB, token, ttl=5, interval=0.05)
    assert keeper.tick() is True
    assert not keeper.lost.is_set(), "a transient DB error is not proof of loss"
