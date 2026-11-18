"""Rollup ownership (F-02a): one owner, fenced writes, no duplicate execution.

Before this correction ``run_rollup`` moved the job to ``running`` with an
unguarded UPDATE and wrote every later state change the same way. Two
deliveries of the same task could therefore both run, and a rollup whose lease
had been reassigned could still overwrite the new owner's state — last writer
wins.

The seven tests below are the scenarios the review asked for:

1. normal claim and completion
2. duplicate delivery while an owner is live
3. concurrent claims have exactly one winner                (PostgreSQL)
4. a superseded rollup cannot write its result
5. worker crash after claim is recovered, not lost
6. retry after lease expiry reclaims the job
7. a failure in a superseded rollup cannot fail the new owner's job

Test 3 needs a real PostgreSQL: SQLite serialises writers, so instead of one
clean winner the loser sees "database is locked". Run it with
``WORKER_TEST_PG_URL=postgresql+psycopg://... pytest tests/test_rollup_ownership.py``.

The F-02a-1 tests at the end cover the other half: a superseded rollup must not
narrate an outcome (success event, failure event or failure alert) that the
fenced write refused to record, while the current owner still must.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

import app.rollup as rollup
from app import db as wdb
from app import fenced, reconciler
from tests.test_rollup import (
    _epoch,
    _events,
    _job,
    _seed_day,
    _seed_rollup_job,
)

PG_URL = os.environ.get("WORKER_TEST_PG_URL")


def _now() -> datetime:
    return datetime.now(UTC)


def _write(conn, job_id: int, **values) -> None:
    conn.execute(wdb.jobs.update().where(wdb.jobs.c.id == job_id).values(**values))


def _supersede(job_id: int, owner: str = "rescue-worker") -> None:
    """Another worker takes the lease over: new owner, bumped token, live lease."""
    with wdb.engine().begin() as conn:
        conn.execute(
            wdb.jobs.update()
            .where(wdb.jobs.c.id == job_id)
            .values(
                status="running",
                owner_id=owner,
                lease_token=wdb.jobs.c.lease_token + 1,
                lease_expires_at=_now() + timedelta(seconds=120),
            )
        )


# 1 -------------------------------------------------------------------------
def test_normal_claim_and_completion_under_one_owner(worker_db):
    _seed_day(worker_db, 1, 7, 1, ["1001", "1002"])
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))

    rollup.run_rollup(99)

    job = _job(worker_db, 99)
    assert job["status"] == "completed"
    assert job["owner_id"] == "rollup"
    assert job["lease_token"] == 1
    assert job["finished_at"] is not None
    assert job["rows_written"] == 2
    assert job["completed_chunks"] == job["total_chunks"] == 1
    assert _events(worker_db, 99)[0] == "Rollup started"
    groups = {
        tuple(g["key"].values()): g["unique_counts"] for g in job["aggregation_result"]["groups"]
    }
    assert groups[("AHA INDIA",)] == {"spid": 2}


# 2 -------------------------------------------------------------------------
def test_duplicate_delivery_bows_out_while_an_owner_is_live(worker_db):
    """A second delivery must not restart, clear or fail a job someone owns."""
    _seed_day(worker_db, 1, 7, 1, ["1001", "1002"])
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))
    with worker_db.engine().begin() as conn:
        token = worker_db.claim_job(conn, 99, owner_id="rollup", ttl_seconds=120)
        worker_db.add_event(conn, 99, "Rollup started")
    assert token == 1

    rollup.run_rollup(99)  # the duplicate delivery

    job = _job(worker_db, 99)
    assert job["status"] == "running"
    assert job["owner_id"] == "rollup"
    assert job["lease_token"] == 1
    assert job["completed_chunks"] == 0
    assert job["rows_written"] == 0
    assert job["aggregation_result"] is None
    assert job["summary_file_path"] is None
    assert [e for e in _events(worker_db, 99) if e.startswith("Failed")] == []
    assert _events(worker_db, 99).count("Rollup started") == 1


# 3 -------------------------------------------------------------------------
@pytest.mark.skipif(
    not PG_URL,
    reason="needs PostgreSQL for a real concurrent claim; SQLite raises 'database is locked'",
)
def test_concurrent_rollup_claims_have_exactly_one_winner():
    # Defense in depth, mirroring conftest's refusal to touch a non-test
    # database: this test drops and recreates every table.
    database = PG_URL.rsplit("/", 1)[-1].split("?")[0]
    assert database.endswith("test"), f"refusing to wipe a non-test database: {database}"
    eng = create_engine(PG_URL, future=True)
    wdb.metadata.drop_all(eng)
    wdb.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(
            wdb.jobs.insert().values(
                id=99,
                status="queued",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=_epoch(2026, 8, 1),
                end_epoch=_epoch(2026, 9, 1),
                chunk_hours=1,
                id_batch_size=100,
                filter_spec={"phrases": [], "ids": []},
                rows_written=0,
                total_chunks=0,
                completed_chunks=0,
                lease_token=0,
            )
        )

    barrier = threading.Barrier(2)
    claimed: dict[str, int | None] = {}

    def claimer(owner: str) -> None:
        with eng.begin() as conn:
            barrier.wait(timeout=15)
            claimed[owner] = wdb.claim_job(conn, 99, owner_id=owner, ttl_seconds=120)

    threads = [threading.Thread(target=claimer, args=(f"rollup-{i}",)) for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert len(claimed) == 2
    winners = [owner for owner, token in claimed.items() if token is not None]
    assert len(winners) == 1, claimed
    winner = winners[0]

    with eng.begin() as conn:
        row = dict(conn.execute(wdb.jobs.select().where(wdb.jobs.c.id == 99)).mappings().one())
    assert row["owner_id"] == winner
    assert row["lease_token"] == 1
    assert row["status"] == "running"

    # A later delivery also loses: the lease is live, not stale.
    with eng.begin() as conn:
        assert wdb.claim_job(conn, 99, owner_id="rollup-late", ttl_seconds=120) is None

    # The winner, and only the winner, can still write.
    with eng.begin() as conn:
        assert fenced.fenced_update(conn, 99, 1, completed_chunks=1) is True
        assert fenced.fenced_update(conn, 99, 2, completed_chunks=2) is False
    eng.dispose()


def _run_rollup_case(
    worker_db, monkeypatch, *, supersede: bool = True, fail_merge: bool = False
) -> None:
    """Run a rollup, optionally losing the lease between the claim and its writes."""
    _seed_day(worker_db, 1, 7, 1, ["1001", "1002"])
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))

    if supersede:
        original = rollup.find_source_jobs

        def supersede_then_read(conn, schedule_id, start_epoch, end_epoch):
            # The other worker wins the lease while this one is between the claim
            # and its next write. Same connection, so the UPDATE joins the read
            # transaction exactly as an interleaved claim would.
            _write(
                conn,
                99,
                status="running",
                owner_id="rescue-worker",
                lease_token=2,
                lease_expires_at=_now() + timedelta(seconds=120),
            )
            return original(conn, schedule_id, start_epoch, end_epoch)

        monkeypatch.setattr(rollup, "find_source_jobs", supersede_then_read)
    if fail_merge:

        def disk_full(*_args, **_kwargs):
            raise OSError("no space left on device")

        monkeypatch.setattr(rollup, "_concat_raw", disk_full)
    rollup.run_rollup(99)


def _seed_schedule_alerts(wdb, schedule_id: int = 7, recipients: str = "ops@example.com") -> None:
    """Give schedule 7 an alert recipient so a failure path would email someone.

    The worker mirror now includes ``alert_recipients``. Older/stale test tables
    may not, so add it only when the column is actually missing.
    """
    with wdb.engine().begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(schedules)")}
        if "alert_recipients" not in columns:
            conn.exec_driver_sql("ALTER TABLE schedules ADD COLUMN alert_recipients VARCHAR(500)")
        conn.exec_driver_sql(
            "INSERT INTO schedules (id, name, alert_recipients) VALUES (?, ?, ?)",
            (schedule_id, "nightly", recipients),
        )


# 4 -------------------------------------------------------------------------
def test_superseded_rollup_cannot_write_its_result(worker_db, monkeypatch):
    """Superseded mid-merge: every subsequent write must match zero rows."""
    _run_rollup_case(worker_db, monkeypatch)

    job = _job(worker_db, 99)
    assert job["status"] == "running", "the stale rollup published its own result"
    assert job["owner_id"] == "rescue-worker"
    assert job["lease_token"] == 2
    assert job["finished_at"] is None
    assert job["rows_written"] == 0
    assert job["aggregation_result"] is None
    assert job["output_file_path"] is None


# 5 -------------------------------------------------------------------------
def test_worker_crash_after_claim_is_recovered_not_lost(worker_db):
    """Crash leaves the row ``running`` with a live lease: neither a duplicate
    delivery nor the reconciler may lose it, and a retry must finish the job."""
    _seed_day(worker_db, 1, 7, 1, ["1001", "1002"])
    _seed_day(worker_db, 2, 7, 2, ["1001", "1003"])
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))
    with worker_db.engine().begin() as conn:
        assert worker_db.claim_job(conn, 99, owner_id="rollup", ttl_seconds=120) == 1
        worker_db.add_event(conn, 99, "Rollup started")
    # ... the process dies here. No terminal write, no release.

    # A duplicate delivery arrives while the lease still looks live.
    rollup.run_rollup(99)
    job = _job(worker_db, 99)
    assert job["status"] == "running"
    assert job["owner_id"] == "rollup"
    assert job["lease_token"] == 1
    assert job["completed_chunks"] == 0

    # Time passes without a heartbeat: the lease expires and the reconciler
    # fences the dead owner rather than failing the job.
    with worker_db.engine().begin() as conn:
        _write(conn, 99, lease_expires_at=_now() - timedelta(seconds=120))
    stats = reconciler.reconcile_once(worker_db.engine())
    assert stats["redispatched"] == 1, stats
    job = _job(worker_db, 99)
    assert job["status"] == "running"
    assert job["owner_id"] is None
    assert job["lease_expires_at"] is None
    assert job["lease_token"] == 2, "the dead owner's token must be invalidated"

    # The redelivery now claims the fenced row and finishes it.
    rollup.run_rollup(99)
    job = _job(worker_db, 99)
    assert job["status"] == "completed"
    assert job["owner_id"] == "rollup"
    assert job["lease_token"] == 3
    assert job["aggregation_result"]["groups"][0]["unique_counts"] == {"spid": 3}


# 6 -------------------------------------------------------------------------
def test_retry_after_lease_expiry_reclaims_and_completes(worker_db):
    _seed_day(worker_db, 1, 7, 1, ["1001", "1002"])
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))
    with worker_db.engine().begin() as conn:
        assert worker_db.claim_job(conn, 99, owner_id="dead-worker", ttl_seconds=60) == 1
        _write(conn, 99, lease_expires_at=_now() - timedelta(seconds=1))

    # Expiry alone does not transfer ownership; the reconciler fences the dead
    # owner first (token bumped, owner and lease cleared), then the retry claims.
    stats = reconciler.reconcile_once(worker_db.engine())
    assert stats["redispatched"] == 1, stats

    # The dead owner's token is now stale and its late write must not land.
    with worker_db.engine().begin() as conn:
        assert fenced.fenced_update(conn, 99, 1, status="failed", error_message="dead") is False
    assert _job(worker_db, 99)["status"] == "running"
    assert _job(worker_db, 99)["error_message"] is None

    rollup.run_rollup(99)

    job = _job(worker_db, 99)
    assert job["status"] == "completed"
    assert job["owner_id"] == "rollup"
    assert job["lease_token"] == 3
    assert job["aggregation_result"]["groups"][0]["unique_counts"] == {"spid": 2}


# 7 -------------------------------------------------------------------------
def test_failure_in_a_superseded_rollup_cannot_fail_the_new_owners_job(worker_db, monkeypatch):
    """The except-path writes are fenced too, not just the success path."""
    _run_rollup_case(worker_db, monkeypatch, fail_merge=True)

    job = _job(worker_db, 99)
    assert job["status"] == "running", "a superseded rollup failed the new owner's job"
    assert job["owner_id"] == "rescue-worker"
    assert job["lease_token"] == 2
    assert job["error_message"] is None
    assert job["finished_at"] is None


# F-02a-1 -------------------------------------------------------------------
def test_superseded_rollup_cannot_announce_success(worker_db, monkeypatch):
    """A refused completion must not write a completion event.

    ``runner.py`` already branches on its publish result; ``run_rollup`` used to
    discard the boolean from its fenced ``save()`` and narrate a completion the
    row itself refused to record.
    """
    _run_rollup_case(worker_db, monkeypatch)

    events = _events(worker_db, 99)
    assert not any(e.startswith("Rollup completed") for e in events), events
    assert _job(worker_db, 99)["status"] == "running"


def test_superseded_rollup_cannot_announce_failure(worker_db, monkeypatch):
    _run_rollup_case(worker_db, monkeypatch, fail_merge=True)

    events = _events(worker_db, 99)
    assert not any(e.startswith("Failed") for e in events), events
    assert _job(worker_db, 99)["status"] == "running"


def test_superseded_rollup_cannot_send_a_failure_alert(worker_db, monkeypatch):
    sent = []
    monkeypatch.setattr(rollup, "send_failure_alert", lambda *a, **k: sent.append(a))
    _seed_schedule_alerts(worker_db)

    _run_rollup_case(worker_db, monkeypatch, fail_merge=True)

    assert sent == [], "a superseded rollup emailed the schedule owner a false failure"
    assert not any(e.startswith("Failed") for e in _events(worker_db, 99))


def test_superseded_incomplete_spec_cannot_fail_the_new_owners_job(worker_db, monkeypatch):
    """The third fenced save: the incomplete-spec failure path."""
    sent = []
    monkeypatch.setattr(rollup, "send_failure_alert", lambda *a, **k: sent.append(a))
    _seed_schedule_alerts(worker_db)
    with worker_db.engine().begin() as conn:
        conn.execute(
            worker_db.jobs.insert().values(
                id=99,
                status="queued",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=_epoch(2026, 8, 1),
                end_epoch=_epoch(2026, 9, 1),
                chunk_hours=1,
                id_batch_size=100,
                filter_spec={"phrases": [], "ids": []},  # no aggregation
                rows_written=0,
                total_chunks=0,
                completed_chunks=0,
                rollup_of={"schedule_id": 7},
            )
        )

    real_claim = rollup.db.claim_job

    def claim_then_lose(conn, job_id, **kwargs):
        token = real_claim(conn, job_id, **kwargs)
        # The other worker takes the lease in the same transaction that grants
        # it, so this one proceeds holding a token that is already stale.
        _write(
            conn,
            job_id,
            status="running",
            owner_id="rescue-worker",
            lease_token=2,
            lease_expires_at=_now() + timedelta(seconds=120),
        )
        return token

    monkeypatch.setattr(rollup.db, "claim_job", claim_then_lose)

    rollup.run_rollup(99)

    job = _job(worker_db, 99)
    assert job["status"] == "running"
    assert job["owner_id"] == "rescue-worker"
    assert job["error_message"] is None
    assert _events(worker_db, 99) == ["Rollup started"]
    assert sent == []


def test_current_owner_can_announce_success(worker_db, monkeypatch):
    _run_rollup_case(worker_db, monkeypatch, supersede=False)

    job = _job(worker_db, 99)
    assert job["status"] == "completed"
    assert any(e.startswith("Rollup completed") for e in _events(worker_db, 99))


def test_current_owner_can_announce_failure_and_alert(worker_db, monkeypatch):
    sent = []
    monkeypatch.setattr(rollup, "send_failure_alert", lambda *a, **k: sent.append(a))
    _seed_schedule_alerts(worker_db)

    _run_rollup_case(worker_db, monkeypatch, supersede=False, fail_merge=True)

    job = _job(worker_db, 99)
    assert job["status"] == "failed"
    assert "no space left on device" in (job["error_message"] or "")
    events = _events(worker_db, 99)
    assert any(e.startswith("Failed: no space left on device") for e in events), events
    assert len(sent) == 1, sent
