"""The task-level safety net.

A job whose task dies before the runner starts used to stay `queued` with an
empty error and no events — indistinguishable in the UI from a job that is
merely slow, and it would sit there forever. (This is not hypothetical: a stale
import in a long-running worker put a real job in exactly that state.)
"""

from __future__ import annotations

import pytest

import app.runner as runner
import app.tasks as tasks


def _seed(wdb, job_id: int = 1, status: str = "queued", rollup_of=None) -> None:
    with wdb.engine().begin() as conn:
        conn.execute(
            wdb.jobs.insert().values(
                id=job_id,
                status=status,
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=0,
                end_epoch=3600,
                chunk_hours=1,
                id_batch_size=100,
                output_format="csv",
                is_preview=False,
                filter_spec={"phrases": [], "ids": []},
                rows_written=0,
                total_chunks=0,
                completed_chunks=0,
                rollup_of=rollup_of,
            )
        )


def _job(wdb, job_id: int = 1) -> dict:
    with wdb.engine().begin() as conn:
        return dict(wdb.load(conn, wdb.jobs, job_id))


def _events(wdb, job_id: int = 1) -> list[str]:
    with wdb.engine().begin() as conn:
        return [
            r["message"]
            for r in conn.execute(
                wdb.job_events.select().where(wdb.job_events.c.job_id == job_id)
            ).mappings()
        ]


def test_a_crash_before_the_runner_starts_marks_the_job_failed(worker_db, monkeypatch):
    _seed(worker_db)

    def boom(_job_id, **_kw):
        raise ImportError("cannot import name 'format_log_timestamp' from 'app.last9'")

    monkeypatch.setattr(runner, "run_extraction", boom)

    with pytest.raises(ImportError):  # still raised, so Celery logs it too
        tasks.run_job(1)

    job = _job(worker_db)
    assert job["status"] == "failed"
    assert "format_log_timestamp" in job["error_message"]
    assert any("Failed before starting" in e for e in _events(worker_db))


def test_the_net_does_not_overwrite_a_status_the_runner_already_set(worker_db, monkeypatch):
    """A job the runner deliberately paused or canceled has a better story than
    'something threw' — the net must not clobber it."""
    _seed(worker_db)

    def pause_then_fail(_job_id, **_kw):
        with worker_db.engine().begin() as conn:
            worker_db.update_job(conn, 1, status="paused")
        raise RuntimeError("connection reset while shutting down")

    monkeypatch.setattr(runner, "run_extraction", pause_then_fail)

    with pytest.raises(RuntimeError):
        tasks.run_job(1)

    assert _job(worker_db)["status"] == "paused"


def test_a_completed_job_is_left_alone(worker_db, monkeypatch):
    _seed(worker_db)

    def complete_then_fail(_job_id, **_kw):
        with worker_db.engine().begin() as conn:
            worker_db.update_job(conn, 1, status="completed")
        raise RuntimeError("error during cleanup, after the work was done")

    monkeypatch.setattr(runner, "run_extraction", complete_then_fail)

    with pytest.raises(RuntimeError):
        tasks.run_job(1)

    assert _job(worker_db)["status"] == "completed"


def test_rollup_jobs_route_to_the_rollup_runner(worker_db, monkeypatch):
    import app.rollup as rollup

    _seed(worker_db, rollup_of={"schedule_id": 7})
    called = []
    monkeypatch.setattr(rollup, "run_rollup", lambda jid: called.append(jid))
    monkeypatch.setattr(runner, "run_extraction", lambda jid, **_kw: pytest.fail("wrong runner"))

    tasks.run_job(1)
    assert called == [1]


def test_plain_jobs_route_to_the_extraction_runner(worker_db, monkeypatch):
    import app.rollup as rollup

    _seed(worker_db)
    called = []
    monkeypatch.setattr(runner, "run_extraction", lambda jid, **_kw: called.append(jid))
    monkeypatch.setattr(rollup, "run_rollup", lambda jid: pytest.fail("wrong runner"))

    tasks.run_job(1)
    assert called == [1]


def test_a_redelivered_message_lets_the_runner_reclaim(worker_db, monkeypatch):
    """Only a broker redelivery may take over a `running` row — that is the
    signal the previous worker is gone."""
    from types import SimpleNamespace

    import celery

    _seed(worker_db)
    seen = []
    monkeypatch.setattr(
        celery,
        "current_task",
        SimpleNamespace(request=SimpleNamespace(redelivered=True)),
    )
    monkeypatch.setattr(runner, "run_extraction", lambda jid, reclaim=False: seen.append(reclaim))

    tasks.run_job(1)
    assert seen == [True]


def test_a_first_delivery_does_not_ask_to_reclaim(worker_db, monkeypatch):
    _seed(worker_db)
    seen = []
    monkeypatch.setattr(runner, "run_extraction", lambda jid, reclaim=False: seen.append(reclaim))

    tasks.run_job(1)
    assert seen == [False]


def _free_disk(gb: float):
    """Stand in for shutil.disk_usage with a chosen amount of free space."""
    import shutil

    total = 100 * 1024**3
    free = int(gb * 1024**3)
    return lambda _path: shutil._ntuple_diskusage(total, total - free, free)


def test_a_nearly_full_disk_fails_the_job_before_it_starts(worker_db, monkeypatch):
    """Exports and pgdata share a filesystem: a job that fills it takes Postgres
    down with it, so one job must fail early rather than every job failing late."""
    _seed(worker_db)
    monkeypatch.setattr(tasks.shutil, "disk_usage", _free_disk(2))
    monkeypatch.setattr(
        runner, "run_extraction", lambda _jid, **_kw: pytest.fail("should not start")
    )

    with pytest.raises(RuntimeError, match="refusing to start"):
        tasks.run_job(1)

    job = _job(worker_db)
    assert job["status"] == "failed"
    assert "2.0 GB free" in job["error_message"]


def test_a_healthy_disk_lets_the_job_run(worker_db, monkeypatch):
    _seed(worker_db)
    monkeypatch.setattr(tasks.shutil, "disk_usage", _free_disk(500))
    ran = []
    monkeypatch.setattr(runner, "run_extraction", lambda jid, **_kw: ran.append(jid))

    tasks.run_job(1)
    assert ran == [1]
