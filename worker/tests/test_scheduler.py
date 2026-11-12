"""Beat tasks: due-schedule scan creates+dispatches a job; cleanup removes
expired exports."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import app.scheduler as scheduler
import app.tasks as tasks
from app.last9 import previous_calendar_day_window


def test_scan_creates_job_for_due_schedule(worker_db, monkeypatch):
    dispatched: list[int] = []
    monkeypatch.setattr(tasks.run_job, "delay", lambda jid: dispatched.append(jid))

    with worker_db.engine().begin() as conn:
        conn.execute(
            worker_db.schedules.insert().values(
                id=1,
                name="daily",
                enabled=True,
                interval_seconds=3600,
                lookback_seconds=3600,
                region_code="ap-southeast-1",
                index_target_id=1,
                credential_id=1,
                chunk_hours=1,
                id_batch_size=100,
                output_format="csv",
                filter_spec={"phrases": ["x"], "ids": []},
                last_run_at=None,
            )
        )

    created = scheduler.scan_schedules()
    assert len(created) == 1
    assert dispatched == created

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, created[0]))
        sched = (
            conn.execute(worker_db.schedules.select().where(worker_db.schedules.c.id == 1))
            .mappings()
            .first()
        )
    assert job["status"] == "queued"
    assert job["created_by"] == "schedule:1"
    assert sched["last_run_at"] is not None

    # Not due again immediately.
    assert scheduler.scan_schedules() == []


def test_scan_uses_previous_calendar_day_window_when_flagged(worker_db, monkeypatch):
    monkeypatch.setattr(tasks.run_job, "delay", lambda jid: None)

    with worker_db.engine().begin() as conn:
        conn.execute(
            worker_db.schedules.insert().values(
                id=1,
                name="daily-full-day",
                enabled=True,
                interval_seconds=86400,
                lookback_seconds=3600,  # ignored when calendar_day is set
                calendar_day=True,
                region_code="ap-southeast-1",
                index_target_id=1,
                credential_id=1,
                chunk_hours=1,
                id_batch_size=100,
                output_format="csv",
                filter_spec={"phrases": ["x"], "ids": []},
                last_run_at=None,
            )
        )

    now = datetime.now(UTC)
    created = scheduler.scan_schedules()
    expected_start, expected_end = previous_calendar_day_window(int(now.timestamp()), "UTC")

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, created[0]))
    assert job["start_epoch"] == expected_start
    assert job["end_epoch"] == expected_end

    # Spelled out rather than only compared to the helper: the window must land
    # on UTC midnight, and cover exactly one day.
    start_dt = datetime.fromtimestamp(job["start_epoch"], UTC)
    end_dt = datetime.fromtimestamp(job["end_epoch"], UTC)
    assert (start_dt.hour, start_dt.minute, start_dt.second) == (0, 0, 0)
    assert (end_dt.hour, end_dt.minute, end_dt.second) == (0, 0, 0)
    assert job["end_epoch"] - job["start_epoch"] == 86400
    assert end_dt.date() == now.date()  # yesterday 00:00 -> today 00:00


def _insert_calendar_schedule(worker_db, last_run_at, sid=1):
    with worker_db.engine().begin() as conn:
        conn.execute(
            worker_db.schedules.insert().values(
                id=sid,
                name="daily-full-day",
                enabled=True,
                interval_seconds=86400,
                lookback_seconds=3600,
                calendar_day=True,
                region_code="ap-southeast-1",
                index_target_id=1,
                credential_id=1,
                chunk_hours=1,
                id_batch_size=100,
                output_format="csv",
                filter_spec={"phrases": ["x"], "ids": []},
                last_run_at=last_run_at,
            )
        )


def test_scan_backfills_every_missed_calendar_day(worker_db, monkeypatch):
    """Missed ticks each get their own day extracted, not just the newest.

    The failure this guards: the worker being down Fri->Mon used to advance
    last_run_at to Monday and extract only Sunday, losing Friday and Saturday
    permanently with no event and no alert.
    """
    monkeypatch.setattr(tasks.run_job, "delay", lambda jid: None)

    now = datetime.now(UTC)
    _insert_calendar_schedule(worker_db, now - timedelta(days=3))

    created = scheduler.scan_schedules()
    assert len(created) == 3, "three completed days went un-extracted; all three are owed"

    with worker_db.engine().begin() as conn:
        jobs = [dict(worker_db.load(conn, worker_db.jobs, jid)) for jid in created]

    windows = sorted((j["start_epoch"], j["end_epoch"]) for j in jobs)
    for start, end in windows:
        assert end - start == 86400, "each backfilled window is exactly one calendar day"
    for (_, earlier_end), (later_start, _) in zip(windows, windows[1:], strict=False):
        assert earlier_end == later_start, "windows are contiguous: no gap, no overlap"
    assert windows[-1] == previous_calendar_day_window(int(now.timestamp()), "UTC")


def test_scan_does_not_re_extract_a_covered_day(worker_db, monkeypatch):
    """A second scan in the same day is a no-op — backfill must be idempotent."""
    monkeypatch.setattr(tasks.run_job, "delay", lambda jid: None)

    now = datetime.now(UTC)
    _insert_calendar_schedule(worker_db, now - timedelta(days=2))

    first = scheduler.scan_schedules()
    assert len(first) == 2
    assert scheduler.scan_schedules() == []


def test_scan_caps_runaway_backfill(worker_db, monkeypatch):
    """A schedule re-enabled after months backfills a bounded window, newest first.

    Without a cap, one tick would queue hundreds of multi-hour jobs at once and
    saturate both the worker pool and the Last9 API.
    """
    monkeypatch.setattr(tasks.run_job, "delay", lambda jid: None)

    now = datetime.now(UTC)
    _insert_calendar_schedule(worker_db, now - timedelta(days=365))

    created = scheduler.scan_schedules()
    assert 0 < len(created) <= scheduler.MAX_BACKFILL_DAYS

    with worker_db.engine().begin() as conn:
        jobs = [dict(worker_db.load(conn, worker_db.jobs, jid)) for jid in created]
    windows = sorted((j["start_epoch"], j["end_epoch"]) for j in jobs)
    # The cap keeps the most recent days, not the oldest.
    assert windows[-1] == previous_calendar_day_window(int(now.timestamp()), "UTC")


def test_cleanup_removes_expired_exports(worker_db, tmp_path):
    f = tmp_path / "old.csv"
    f.write_text("timestamp,message\n", encoding="utf-8")
    old = datetime.now(UTC) - timedelta(days=40)

    with worker_db.engine().begin() as conn:
        conn.execute(
            worker_db.jobs.insert().values(
                id=1,
                status="completed",
                region_code="r",
                index_target_id=1,
                credential_id=1,
                start_epoch=0,
                end_epoch=1,
                chunk_hours=1,
                id_batch_size=100,
                filter_spec={},
                rows_written=0,
                total_chunks=0,
                completed_chunks=0,
                output_file_path=str(f),
                finished_at=old,
            )
        )

    removed = scheduler.cleanup_exports()
    assert removed == 1
    assert not os.path.exists(f)
    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    assert job["output_file_path"] is None


def test_cleanup_prunes_comparison_run_history(worker_db, monkeypatch):
    """Each run stores a full series plus raw rows. Only the newest N per
    comparison are kept, so the table cannot grow without bound."""
    from app.config import get_settings

    keep = get_settings().comparison_run_retention_count
    with worker_db.engine().begin() as conn:
        for comparison_id in (1, 2):
            for n in range(keep + 5):
                conn.execute(
                    worker_db.comparison_runs.insert().values(
                        id=comparison_id * 1000 + n,
                        comparison_id=comparison_id,
                        created_at=datetime.now(UTC),
                    )
                )

    scheduler.cleanup_exports()

    with worker_db.engine().begin() as conn:
        rows = (
            conn.execute(
                worker_db.comparison_runs.select().order_by(
                    worker_db.comparison_runs.c.comparison_id,
                    worker_db.comparison_runs.c.id,
                )
            )
            .mappings()
            .all()
        )

    per_comparison: dict[int, list[int]] = {}
    for row in rows:
        per_comparison.setdefault(row["comparison_id"], []).append(row["id"])
    assert sorted(per_comparison) == [1, 2]
    for ids in per_comparison.values():
        assert len(ids) == keep
        # The survivors are the newest, not the oldest.
        assert ids[-1] % 1000 == keep + 4


def _running_job(wdb, job_id: int, *, started_at, last_event_at=None, created_by=None) -> None:
    with wdb.engine().begin() as conn:
        conn.execute(
            wdb.jobs.insert().values(
                id=job_id,
                status="running",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=0,
                end_epoch=3600,
                chunk_hours=1,
                id_batch_size=100,
                filter_spec={"phrases": [], "ids": []},
                output_format="csv",
                is_preview=False,
                rows_written=0,
                total_chunks=1,
                completed_chunks=0,
                created_by=created_by,
                started_at=started_at,
            )
        )
        if last_event_at is not None:
            conn.execute(
                wdb.job_events.insert().values(
                    job_id=job_id, ts=last_event_at, level="info", message="Chunk done"
                )
            )


def test_reap_fails_a_job_that_stopped_reporting(worker_db):
    """An OOM-killed worker raises nothing anywhere: without this the row stays
    `running` forever and reads in the UI as a job that is merely slow."""
    long_ago = datetime.now(UTC) - timedelta(hours=3)
    _running_job(worker_db, 1, started_at=long_ago, last_event_at=long_ago)

    assert scheduler.reap_stale_jobs() == [1]

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
        events = [
            r["message"]
            for r in conn.execute(
                worker_db.job_events.select().where(worker_db.job_events.c.job_id == 1)
            ).mappings()
        ]
    assert job["status"] == "failed"
    assert "worker presumed dead" in job["error_message"]
    assert job["finished_at"] is not None
    assert any("worker presumed dead" in e for e in events)


def test_reap_leaves_a_job_that_is_still_reporting(worker_db):
    """A slow chunk is not a dead worker: one request can legitimately retry for
    ~14 minutes without emitting anything."""
    _running_job(
        worker_db,
        1,
        started_at=datetime.now(UTC) - timedelta(hours=5),
        last_event_at=datetime.now(UTC) - timedelta(minutes=20),
    )

    assert scheduler.reap_stale_jobs() == []
    with worker_db.engine().begin() as conn:
        assert worker_db.current_status(conn, 1) == "running"


def test_reap_falls_back_to_started_at_when_no_events_exist(worker_db):
    _running_job(worker_db, 1, started_at=datetime.now(UTC) - timedelta(hours=3))
    assert scheduler.reap_stale_jobs() == [1]


def test_reap_leaves_a_job_with_no_timestamps_at_all(worker_db):
    """No timestamp is no evidence of death — do not kill a job on a guess."""
    _running_job(worker_db, 1, started_at=None)
    assert scheduler.reap_stale_jobs() == []


def test_reap_alerts_when_the_dead_job_came_from_a_schedule(worker_db, monkeypatch):
    """A schedule's owner learns its job died the same way they learn it failed."""
    alerted: list[tuple] = []
    monkeypatch.setattr(
        tasks,
        "_send_alert_if_scheduled",
        lambda conn, job, msg: alerted.append((job["id"], msg)),
    )
    _running_job(
        worker_db,
        1,
        started_at=datetime.now(UTC) - timedelta(hours=3),
        created_by="schedule:7",
    )

    assert scheduler.reap_stale_jobs() == [1]
    assert alerted == [(1, alerted[0][1])]
    assert "worker presumed dead" in alerted[0][1]


def test_beat_heartbeat_is_written_after_a_scan(worker_db, monkeypatch):
    """/health/ops reads this key; without it a dead worker is invisible."""
    written: dict[str, object] = {}

    class _FakeRedis:
        def set(self, key, value, ex=None):
            written["key"], written["value"], written["ex"] = key, value, ex

    monkeypatch.setattr(scheduler, "_redis", lambda: _FakeRedis())
    scheduler.scan_schedules()

    assert written["key"] == scheduler.BEAT_KEY
    assert written["ex"] > 60  # outlives a single missed tick
    datetime.fromisoformat(written["value"])  # parseable by the API side


def test_a_broken_heartbeat_does_not_break_the_scan(worker_db, monkeypatch):
    def explode():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(scheduler, "_redis", explode)
    assert scheduler.scan_schedules() == []
