"""Month-end rollup: merge a schedule's daily runs into one exact total.

The headline property is that a customer seen on several days counts once, not
once per day — a rollup that got this wrong would report a believable number,
so it is asserted directly.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import app.rollup as rollup
from app.config import get_settings
from app.last9.distinct_store import DistinctStore, store_path

PATTERN = r"SPAccountId\s+(?<spid>\d+)\s+in\s+BU\s+(?<BU>.*?)\s+API User"
AGG = {
    "enabled": True,
    "regex": PATTERN,
    "group_by": ["BU"],
    "unique_fields": ["spid"],
    "skip_raw_output": True,
}


def _epoch(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp())


def _seed_day(
    wdb, job_id: int, schedule_id: int, day: int, spids: list[str], *, status="completed"
):
    """A completed daily run: a jobs row plus the distinct-value store it left."""
    with wdb.engine().begin() as conn:
        conn.execute(
            wdb.jobs.insert().values(
                id=job_id,
                status=status,
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=_epoch(2026, 8, day),
                end_epoch=_epoch(2026, 8, day + 1),
                chunk_hours=1,
                id_batch_size=100,
                filter_spec={"phrases": [], "ids": [], "aggregation": AGG},
                rows_written=len(spids),
                total_chunks=1,
                completed_chunks=1,
                created_by=f"schedule:{schedule_id}",
            )
        )
    with DistinctStore(store_path(get_settings().storage_dir, job_id), fresh=True) as s:
        for spid in spids:
            s.add(("AHA INDIA",), "spid", spid)
        s.bump("rows_matched", len(spids))


def _seed_rollup_job(wdb, job_id: int, schedule_id: int, start: int, end: int):
    with wdb.engine().begin() as conn:
        conn.execute(
            wdb.jobs.insert().values(
                id=job_id,
                status="queued",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=start,
                end_epoch=end,
                chunk_hours=1,
                id_batch_size=100,
                filter_spec={"phrases": [], "ids": [], "aggregation": AGG},
                rows_written=0,
                total_chunks=0,
                completed_chunks=0,
                rollup_of={"schedule_id": schedule_id, "label": "2026-08"},
            )
        )


def _job(wdb, job_id: int) -> dict:
    with wdb.engine().begin() as conn:
        return dict(wdb.load(conn, wdb.jobs, job_id))


def _events(wdb, job_id: int) -> list[str]:
    with wdb.engine().begin() as conn:
        return [
            r["message"]
            for r in conn.execute(
                wdb.job_events.select().where(wdb.job_events.c.job_id == job_id)
            ).mappings()
        ]


def test_monthly_unique_count_is_a_union_not_a_sum(worker_db):
    # 1001 appears on all three days. Daily counts are 2 + 2 + 2 = 6; the true
    # number of distinct customers across the month is 4.
    _seed_day(worker_db, 1, 7, 1, ["1001", "1002"])
    _seed_day(worker_db, 2, 7, 2, ["1001", "1003"])
    _seed_day(worker_db, 3, 7, 3, ["1001", "1004"])
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))

    rollup.run_rollup(99)

    job = _job(worker_db, 99)
    assert job["status"] == "completed"
    groups = {
        tuple(g["key"].values()): g["unique_counts"] for g in job["aggregation_result"]["groups"]
    }
    assert groups[("AHA INDIA",)] == {"spid": 4}


def test_rollup_writes_a_summary_csv(worker_db):
    _seed_day(worker_db, 1, 7, 1, ["1001", "1002"])
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))

    rollup.run_rollup(99)

    path = _job(worker_db, 99)["summary_file_path"]
    assert os.path.exists(path)
    lines = _read_export(path)
    assert lines[0] == "BU,unique_spid"
    assert lines[1] == "AHA INDIA,2"


def test_days_outside_the_period_are_not_merged(worker_db):
    _seed_day(worker_db, 1, 7, 1, ["1001"])
    _seed_day(worker_db, 2, 7, 2, ["1002"])
    # A window covering only Aug 1.
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 8, 2))

    rollup.run_rollup(99)

    job = _job(worker_db, 99)
    assert job["aggregation_result"]["groups"][0]["unique_counts"] == {"spid": 1}


def test_runs_from_other_schedules_are_not_merged(worker_db):
    _seed_day(worker_db, 1, 7, 1, ["1001"])
    _seed_day(worker_db, 2, 8, 1, ["2001"])  # a different schedule
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))

    rollup.run_rollup(99)

    assert _job(worker_db, 99)["aggregation_result"]["groups"][0]["unique_counts"] == {"spid": 1}


def test_a_missing_day_is_reported_rather_than_silently_dropped(worker_db):
    """An under-count that looks clean is worse than one that says what it missed."""
    _seed_day(worker_db, 1, 7, 1, ["1001"])
    _seed_day(worker_db, 2, 7, 2, ["1002"], status="failed")
    _seed_day(worker_db, 3, 7, 3, ["1003"])
    os.remove(store_path(get_settings().storage_dir, 3))  # e.g. deleted by retention
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))

    rollup.run_rollup(99)

    job = _job(worker_db, 99)
    assert job["status"] == "completed"
    events = _events(worker_db, 99)
    assert any("Skipped job 2" in e and "status=failed" in e for e in events)
    assert any("Skipped job 3" in e and "missing" in e for e in events)
    assert any("counts are incomplete" in e for e in events)


def test_rollup_without_an_aggregation_spec_fails_cleanly(worker_db):
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

    rollup.run_rollup(99)

    job = _job(worker_db, 99)
    assert job["status"] == "failed"
    assert "aggregation" in job["error_message"]


def _write_raw(path: str, rows: list[str]) -> None:
    import pathlib

    pathlib.Path(path).write_text(
        "timestamp_utc,message\n" + "".join(f"{r}\n" for r in rows), encoding="utf-8"
    )


def _read_export(path: str) -> list[str]:
    """An export's lines, whether or not it was compressed on completion."""
    import zipfile

    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            return zf.read(zf.namelist()[0]).decode("utf-8").splitlines()
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def _seed_day_with_raw(wdb, job_id, schedule_id, day, spids, rows, zipped=False):
    _seed_day(wdb, job_id, schedule_id, day, spids)
    raw = os.path.join(get_settings().storage_dir, f"job_{job_id}.csv")
    _write_raw(raw, rows)
    if zipped:
        # What a real completed day looks like: runner.py compresses the export
        # and stores the archive path, so the rollup's sources are never plain CSV.
        import zipfile

        archive = f"{raw}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(raw, arcname=os.path.basename(raw))
        os.remove(raw)
        raw = archive
    with wdb.engine().begin() as conn:
        wdb.update_job(conn, job_id, output_file_path=raw)


def test_rollup_reads_days_that_were_compressed_on_completion(worker_db):
    """Exports are zipped when a day finishes, so the rollup's sources are archives.

    Reading those bytes straight through produced a file named `.csv` holding
    concatenated ZIP containers — with each archive's first line-worth of bytes
    stripped as if it were a header — and the job still reported "Rollup
    completed" with a download link.
    """
    _seed_day_with_raw(worker_db, 1, 7, 1, ["1001"], ["d1r1,a", "d1r2,b"], zipped=True)
    _seed_day_with_raw(worker_db, 2, 7, 2, ["1002"], ["d2r1,c"], zipped=True)
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))

    rollup.run_rollup(99)

    lines = _read_export(_job(worker_db, 99)["output_file_path"])
    assert lines[0] == "timestamp_utc,message"
    assert lines.count("timestamp_utc,message") == 1
    assert lines[1:] == ["d1r1,a", "d1r2,b", "d2r1,c"]


def test_rollup_concatenates_each_days_rows_with_one_header(worker_db):
    _seed_day_with_raw(worker_db, 1, 7, 1, ["1001"], ["d1r1,a", "d1r2,b"])
    _seed_day_with_raw(worker_db, 2, 7, 2, ["1002"], ["d2r1,c"])
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))

    rollup.run_rollup(99)

    job = _job(worker_db, 99)
    lines = _read_export(job["output_file_path"])
    assert lines[0] == "timestamp_utc,message"
    assert lines.count("timestamp_utc,message") == 1  # not once per day
    assert lines[1:] == ["d1r1,a", "d1r2,b", "d2r1,c"]


def test_rollup_still_produces_the_aggregates(worker_db):
    _seed_day_with_raw(worker_db, 1, 7, 1, ["1001", "1002"], ["r,a"])
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))

    rollup.run_rollup(99)

    job = _job(worker_db, 99)
    assert os.path.exists(job["summary_file_path"])
    assert os.path.exists(job["counts_file_path"])


def test_a_day_whose_raw_file_aged_out_is_skipped_not_fatal(worker_db):
    """Retention removes raw extracts before the value stores, so the combined
    file can be short a day while the counts still cover it."""
    _seed_day_with_raw(worker_db, 1, 7, 1, ["1001"], ["d1,a"])
    _seed_day(worker_db, 2, 7, 2, ["1002"])  # completed, but no raw file
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))

    rollup.run_rollup(99)

    job = _job(worker_db, 99)
    assert job["status"] == "completed"
    assert _read_export(job["output_file_path"])[1:] == ["d1,a"]
    # Both days still counted, because that comes from the stores.
    assert job["aggregation_result"]["groups"][0]["unique_counts"] == {"spid": 2}


def test_a_rollup_with_no_raw_files_at_all_has_no_combined_output(worker_db):
    _seed_day(worker_db, 1, 7, 1, ["1001"])
    _seed_rollup_job(worker_db, 99, 7, _epoch(2026, 8, 1), _epoch(2026, 9, 1))

    rollup.run_rollup(99)

    job = _job(worker_db, 99)
    assert job["status"] == "completed"
    assert job["output_file_path"] is None
