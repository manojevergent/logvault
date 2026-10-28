"""Runner: streams rows to CSV, checkpoints, completes — and finalizes on cancel.
The Last9 client is never hit; iter_extraction is faked."""

from __future__ import annotations

import csv

import app.runner as runner
from app import crypto
from app.last9 import Checkpoint, LogRow
from tests.conftest import read_export


def _seed(wdb, *, start=0, end=7200, chunk_hours=1):
    with wdb.engine().begin() as conn:
        conn.execute(
            wdb.last9_credentials.insert().values(
                id=1,
                org_slug="evergentapse1",
                encrypted_refresh_token=crypto.encrypt("rt-WXYZ"),
                refresh_token_last4="WXYZ",
                encrypted_access_token=None,
                access_token_expires_at=None,
            )
        )
        conn.execute(
            wdb.index_targets.insert().values(
                id=1, region_code="ap-southeast-1", full_index_string="physical_index:UMServices"
            )
        )
        conn.execute(
            wdb.jobs.insert().values(
                id=1,
                status="queued",
                region_code="ap-southeast-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=start,
                end_epoch=end,
                chunk_hours=chunk_hours,
                id_batch_size=100,
                filter_spec={"phrases": ["GetEntitlements"], "ids": []},
                rows_written=0,
                total_chunks=0,
                completed_chunks=0,
            )
        )


def test_export_entry_name_uses_descriptive_filename_inside_zip():
    from app.runner import export_entry_name

    # Full day window
    name = export_entry_name(
        795, "GetEntitlementsRequestMessage_20th_oct", 1788000000, 1788086400, "raw", "csv"
    )
    assert name.startswith("GetEntitlementsRequestMessage_20th_oct_795_")
    assert name.endswith(".csv")

    # Summary and counts
    summary = export_entry_name(
        795, "GetEntitlementsRequestMessage_20th_oct", 1788000000, 1788086400, "summary", "csv"
    )
    assert summary.endswith("_summary.csv")

    counts = export_entry_name(
        795, "GetEntitlementsRequestMessage_20th_oct", 1788000000, 1788086400, "counts", "csv"
    )
    assert counts.endswith("_counts.csv")


def test_zip_file_uses_arcname(tmp_path):
    import zipfile

    from app.runner import _zip_file

    p = tmp_path / "job_795.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    zipped = _zip_file(str(p), arcname="GetEntitlements_795_2026-10-27.csv")
    assert zipped.endswith(".zip")
    with zipfile.ZipFile(zipped) as zf:
        assert zf.namelist() == ["GetEntitlements_795_2026-10-27.csv"]


def _fake_iter_two_chunks(client, spec, *, checkpoint=None, on_chunk_complete=None, **kw):
    cp: Checkpoint = checkpoint
    yield LogRow("1", "a", "")
    yield LogRow("2", "b", "")
    cp.advance(
        chunk_index=0,
        chunk_start=spec.start_epoch,
        chunk_end=spec.start_epoch + 3600,
        rows_delta=2,
    )
    on_chunk_complete(cp, 2)
    yield LogRow("3", "c", "")
    cp.advance(
        chunk_index=1,
        chunk_start=spec.start_epoch + 3600,
        chunk_end=spec.start_epoch + 7200,
        rows_delta=1,
    )
    on_chunk_complete(cp, 1)


def test_run_completes_and_writes_csv(worker_db, monkeypatch):
    _seed(worker_db)
    monkeypatch.setattr(runner, "iter_extraction", _fake_iter_two_chunks)

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    assert job["status"] == "completed"
    assert job["rows_written"] == 3
    assert job["completed_chunks"] == 2
    assert job["total_chunks"] == 2

    rows = list(csv.reader(read_export(job["output_file_path"])))
    assert rows[0] == ["timestamp_utc", "message"]
    assert [r[1] for r in rows[1:]] == ["a", "b", "c"]
    # Plain by default: `="..."` is literal data to a warehouse loader.
    assert not any('="' in r[0] for r in rows[1:])
    assert all(r[0] and r[0][0] != "=" for r in rows[1:])


def test_excel_escape_is_opt_in_for_spreadsheet_workflows(worker_db, monkeypatch):
    """With EXCEL_ESCAPE on, the timestamp is wrapped so Excel keeps it literal."""
    _seed(worker_db)
    monkeypatch.setattr(runner, "iter_extraction", _fake_iter_two_chunks)
    monkeypatch.setattr(runner.get_settings(), "excel_escape", True)

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    rows = list(csv.reader(read_export(job["output_file_path"])))
    assert all(r[0].startswith('="') and r[0].endswith('"') for r in rows[1:])


def test_a_second_worker_cannot_claim_a_running_job(worker_db, monkeypatch):
    """Two workers on one job interleave rows into the same CSV and store.

    Resume dispatches unconditionally and nothing deduped the task, so pausing a
    job and resuming it before it reached its next chunk boundary put two workers
    on the same output — duplicated rows, wrong counts, and a job that still
    reported "completed".
    """
    _seed(worker_db)
    with worker_db.engine().begin() as conn:
        worker_db.update_job(conn, 1, status="running")  # worker A already has it

    ran = []
    monkeypatch.setattr(runner, "iter_extraction", lambda *a, **kw: ran.append(1) or iter(()))
    runner.run_extraction(1)

    assert ran == [], "worker B must not start extracting a job already claimed"


def test_a_job_canceled_while_queued_never_starts(worker_db, monkeypatch):
    """Cancelling a queued job has to actually stop it.

    `run_extraction` used to overwrite status with "running" without reading it,
    so a wrong 30-day job cancelled while the worker was busy still ran to
    completion and flipped itself to "completed".
    """
    _seed(worker_db)
    with worker_db.engine().begin() as conn:
        worker_db.update_job(conn, 1, status="canceled")

    ran = []
    monkeypatch.setattr(runner, "iter_extraction", lambda *a, **kw: ran.append(1) or iter(()))
    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    assert ran == []
    assert job["status"] == "canceled", "a cancelled job must stay cancelled"


def test_cancel_between_chunks_finalizes_partial(worker_db, monkeypatch):
    _seed(worker_db)
    monkeypatch.setattr(runner, "iter_extraction", _fake_iter_two_chunks)
    # Simulate a cancel request landing while the job runs.
    monkeypatch.setattr(runner.db, "current_status", lambda conn, jid: "canceled")

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    assert job["status"] == "canceled"
    assert job["finished_at"] is not None
    # Chunk 0 rows were flushed before the cancel took effect.
    rows = list(csv.reader(read_export(job["output_file_path"])))
    assert [r[1] for r in rows[1:]] == ["a", "b"]


def test_adaptive_chunk_size_reports_every_change(worker_db, monkeypatch):
    """The returned size must be relative to what the iterator is using now.

    It was compared against the size the job STARTED with, so growing 1h -> 2h
    on a sparse chunk and shrinking back to 1h on the next dense one returned
    None the second time: the iterator carried on at 2h while the checkpoint
    recorded 1h, and the two stayed out of step for the rest of the run.
    """
    returned = []

    def fake(client, spec, *, checkpoint=None, on_chunk_complete=None, **kw):
        cp: Checkpoint = checkpoint
        cp.advance(chunk_index=0, chunk_start=0, chunk_end=3600, rows_delta=0)
        returned.append(on_chunk_complete(cp, 0))  # sparse -> grow
        cp.advance(chunk_index=1, chunk_start=3600, chunk_end=7200, rows_delta=10_000)
        returned.append(on_chunk_complete(cp, 10_000))  # dense -> shrink back
        yield from ()

    _seed(worker_db)
    monkeypatch.setattr(runner, "iter_extraction", fake)
    runner.run_extraction(1)

    assert returned[0] == 2.0, "a sparse chunk doubles the window"
    assert returned[1] == 1.0, "shrinking back to the starting size is still a change"


def test_total_chunks_tracks_adaptive_growth_so_a_finished_job_reads_100pct(worker_db, monkeypatch):
    """A 6h window at 1h chunks is queued as 6 chunks, but sparse data doubles
    the window each boundary, so it really finishes in 3.

    The denominator used to be computed once at job start and never updated, so
    a job that grew its chunks completed showing "3 / 6" (50%) with a green bar
    frozen halfway. The total has to be re-estimated at every chunk boundary.
    """
    _seed(worker_db, start=0, end=6 * 3600, chunk_hours=1)

    def fake(client, spec, *, checkpoint=None, on_chunk_complete=None, **kw):
        cp = checkpoint
        h = spec.chunk_hours
        cursor = spec.start_epoch
        idx = 0
        while cursor < spec.end_epoch:
            end = min(cursor + int(h * 3600), spec.end_epoch)
            cp.advance(chunk_index=idx, chunk_start=cursor, chunk_end=end, rows_delta=1)
            # 1 row per chunk is "sparse" -> the runner doubles the window.
            new_h = on_chunk_complete(cp, 1)
            if new_h is not None:
                h = new_h
            cursor = end
            idx += 1
            yield LogRow(str(idx), "x", "")

    monkeypatch.setattr(runner, "iter_extraction", fake)
    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
        events = [
            r._mapping["message"]
            for r in conn.execute(
                worker_db.job_events.select().order_by(worker_db.job_events.c.id)
            ).all()
        ]

    assert job["status"] == "completed"
    assert job["completed_chunks"] == 3, "1h -> 2h -> 4h covers 6h in three chunks"
    assert job["total_chunks"] == job["completed_chunks"], "a finished job must read N / N"
    # The per-chunk feed has to agree with the bar, not report the stale plan.
    assert "Chunk 3/3 done" in events
    assert not any(e.startswith("Chunk 3/6") for e in events)


def test_long_chunk_emits_heartbeats_so_the_reaper_does_not_kill_it(worker_db, monkeypatch):
    """A chunk can take hours (millions of rows, upstream 502 retries).

    Progress used to be recorded only when a chunk finished, so reap_stale_jobs
    — which reads the newest job event — failed a perfectly healthy job after
    60 quiet minutes ("worker presumed dead"). The runner now writes a
    heartbeat while rows stream.
    """
    _seed(worker_db, start=0, end=3600)

    def fake(client, spec, *, checkpoint=None, on_chunk_complete=None, **kw):
        cp = checkpoint
        for i in range(10):
            yield LogRow(str(i), f"line {i}", "")
        cp.advance(chunk_index=0, chunk_start=0, chunk_end=3600, rows_delta=10)
        on_chunk_complete(cp, 10)

    class Clock:
        t = 0.0

        def __call__(self):
            self.t += 60.0  # 5 rows => 5 minutes of wall clock
            return self.t

    monkeypatch.setattr(runner, "iter_extraction", fake)
    monkeypatch.setattr(runner.time, "monotonic", Clock())

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
        events = [
            r._mapping["message"]
            for r in conn.execute(
                worker_db.job_events.select().order_by(worker_db.job_events.c.id)
            ).all()
        ]

    assert job["status"] == "completed"
    beats = [e for e in events if e.startswith("Still scanning")]
    assert beats, "a multi-hour chunk must keep its job event fresh"
    assert any("rows written so far" in e for e in beats)


def test_total_chunks_on_resume_counts_only_what_is_left(worker_db, monkeypatch):
    """Resuming must not re-measure the whole range at the adapted chunk size.

    A 30-day job 400 chunks in at 1h, paused once adaptive sizing had dropped to
    0.25h, recomputed total over the FULL range at 0.25h — so the UI showed 400
    of 2880 (14%) for a job that was better than half done.
    """
    _seed(worker_db, start=0, end=7200, chunk_hours=1)
    with worker_db.engine().begin() as conn:
        worker_db.update_job(
            conn,
            1,
            status="queued",
            checkpoint={
                "completed_chunks": 1,
                "rows_written": 10,
                "current_chunk_start": 0,
                "next_chunk_start": 3600,
                "chunk_hours": 0.25,
                "file_offset": 0,
            },
        )

    monkeypatch.setattr(runner, "iter_extraction", lambda *a, **kw: iter(()))
    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    # 1 done + the remaining hour at 0.25h = 4 more. Not 8 (the whole range).
    assert job["total_chunks"] == 5
