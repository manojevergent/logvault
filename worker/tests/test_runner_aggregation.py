"""Runner wiring for parse & aggregate: the Aggregator itself is unit-tested in
test_aggregate.py — this covers how run_extraction wires it in (skip_raw_output,
checkpoint persistence, multi-field unique counts, resume)."""

from __future__ import annotations

import csv

import app.runner as runner
from app import crypto
from app.last9 import Checkpoint, LogRow
from tests.conftest import read_export

PATTERN = (
    r"^\s*(?<trackerid>AHA-\d-[a-f0-9]+)\s+-\s+ClassName\s+(?<api>\w+)\s+"
    r"SPAccountId\s+(?<spid>\d+)\s+in\s+BU\s+(?<BU>.*?)\s+API User.*$"
)


def _line(tracker: str, api: str, spid: str, bu: str) -> str:
    # Double spaces on purpose — matches the real one-use-case log format.
    return f"{tracker} - ClassName  {api} SPAccountId  {spid} in BU  {bu} API User ahaapiuser"


def _seed(wdb, *, aggregation=None, checkpoint=None, start=0, end=7200, chunk_hours=1):
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
                id=1, region_code="ap-south-1", full_index_string="physical_index:UMServices"
            )
        )
        filter_spec = {"phrases": ["ClassName"], "ids": []}
        if aggregation is not None:
            filter_spec["aggregation"] = aggregation
        conn.execute(
            wdb.jobs.insert().values(
                id=1,
                status="queued",
                region_code="ap-south-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=start,
                end_epoch=end,
                chunk_hours=chunk_hours,
                id_batch_size=100,
                filter_spec=filter_spec,
                rows_written=0,
                total_chunks=0,
                completed_chunks=0,
                checkpoint=checkpoint,
            )
        )


def _fake_iter_rows(rows, chunk_end=3600):
    def _iter(client, spec, *, checkpoint=None, on_chunk_complete=None, **kw):
        cp: Checkpoint = checkpoint
        yield from rows
        cp.advance(
            chunk_index=0, chunk_start=spec.start_epoch, chunk_end=chunk_end, rows_delta=len(rows)
        )
        if on_chunk_complete:
            on_chunk_complete(cp, len(rows))

    return _iter


AGG = {
    "enabled": True,
    "regex": PATTERN,
    "group_by": ["api", "BU"],
    "unique_fields": ["spid", "trackerid"],
    "skip_raw_output": False,
}

ROWS = [
    LogRow("1", _line("AHA-1-aaa", "CGetEntitlementsCommand", "1001", "AHA INDIA"), ""),
    LogRow("2", _line("AHA-1-bbb", "CGetEntitlementsCommand", "1002", "AHA INDIA"), ""),
    LogRow("3", _line("AHA-1-ccc", "CGetEntitlementsCommand", "1001", "AHA INDIA"), ""),  # dup spid
    LogRow("4", _line("AHA-1-ddd", "CGetEntitlementsCommand", "2001", "AHA MIDDLE EAST"), ""),
    LogRow("5", "this line matches nothing", ""),
]


def test_aggregation_result_has_multiple_unique_fields_per_group(worker_db, monkeypatch):
    _seed(worker_db, aggregation=AGG)
    monkeypatch.setattr(runner, "iter_extraction", _fake_iter_rows(ROWS))

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    assert job["status"] == "completed"
    snap = job["aggregation_result"]
    assert snap["rows_matched"] == 4
    assert snap["rows_unmatched"] == 1
    assert [s["message"] for s in snap["unmatched_samples"]] == ["this line matches nothing"]
    assert snap["unmatched_sample_cap"] == 20

    # The complete artifact carries every unmatched line, not just the sample.
    assert job["unmatched_file_path"]
    artifact = list(csv.reader(read_export(job["unmatched_file_path"])))
    assert artifact[0] == ["timestamp", "message"]
    assert [row[1] for row in artifact[1:]] == ["this line matches nothing"]
    groups = {tuple(g["key"].values()): g["unique_counts"] for g in snap["groups"]}
    assert groups[("CGetEntitlementsCommand", "AHA INDIA")] == {"spid": 2, "trackerid": 3}
    assert groups[("CGetEntitlementsCommand", "AHA MIDDLE EAST")] == {"spid": 1, "trackerid": 1}
    # Raw output still written alongside the aggregate summary.
    assert len(read_export(job["output_file_path"])) == 1 + len(ROWS)


def test_parse_only_job_writes_fields_without_summary_or_counts(worker_db, monkeypatch):
    agg = {"enabled": True, "regex": PATTERN, "aggregate": False}
    _seed(worker_db, aggregation=agg)
    monkeypatch.setattr(runner, "iter_extraction", _fake_iter_rows(ROWS))

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    snap = job["aggregation_result"]
    assert snap["aggregate"] is False
    assert snap["rows_matched"] == 4
    assert snap["rows_unmatched"] == 1
    assert snap["groups"] == []
    assert job["summary_file_path"] is None
    assert job["counts_file_path"] is None

    rows = read_export(job["output_file_path"])
    parsed = list(csv.reader(rows))
    # timestamp + every named group + the raw message (include_message defaults
    # on; the wizard can drop it). No aggregate-only columns.
    assert parsed[0] == ["timestamp_utc", "trackerid", "api", "spid", "BU", "message"]
    assert len(parsed) == 1 + len(ROWS)
    # The unmatched line still gets its row, with blank parsed fields.
    assert parsed[-1][1:5] == ["", "", "", ""]
    assert parsed[-1][5] == "this line matches nothing"


def test_unmatched_samples_are_distinct_but_artifact_keeps_every_row(worker_db, monkeypatch):
    _seed(worker_db, aggregation=AGG)
    rows = [
        LogRow("1", "this line matches nothing", ""),
        LogRow("2", "this line matches nothing", ""),
    ]
    monkeypatch.setattr(runner, "iter_extraction", _fake_iter_rows(rows))

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    assert job["aggregation_result"]["rows_unmatched"] == 2
    # One sample slot, not the same line twice.
    assert [s["message"] for s in job["aggregation_result"]["unmatched_samples"]] == [
        "this line matches nothing"
    ]
    # The complete artifact is still every unmatched row.
    artifact = list(csv.reader(read_export(job["unmatched_file_path"])))
    assert len(artifact) == 3  # header + both duplicates


def test_cancel_mid_chunk_keeps_the_partial_output(worker_db, monkeypatch):
    _seed(worker_db, aggregation=AGG)
    monkeypatch.setattr(runner, "STATUS_CHECK_SECONDS", 0)
    monkeypatch.setattr(runner.db, "current_status", lambda conn, job_id: "canceled")
    monkeypatch.setattr(runner, "iter_extraction", _fake_iter_rows(ROWS))

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    assert job["status"] == "canceled"
    # The row that was being processed is kept, and it is reflected in the job.
    assert job["rows_written"] == 1
    assert job["finished_at"] is not None
    rows = read_export(job["output_file_path"])
    assert len(rows) == 2  # header + the one written row


def test_no_unmatched_rows_writes_no_unmatched_artifact(worker_db, monkeypatch):
    _seed(worker_db, aggregation=AGG)
    monkeypatch.setattr(runner, "iter_extraction", _fake_iter_rows(ROWS[:4]))

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    assert job["unmatched_file_path"] is None
    assert job["aggregation_result"]["unmatched_samples"] == []


def test_skip_raw_output_writes_no_file_but_still_aggregates(worker_db, monkeypatch):
    agg = {**AGG, "skip_raw_output": True}
    _seed(worker_db, aggregation=agg)
    monkeypatch.setattr(runner, "iter_extraction", _fake_iter_rows(ROWS))

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    assert job["output_file_path"] is None
    assert job["aggregation_result"]["rows_matched"] == 4


def test_resume_preserves_exact_unique_counts_not_just_since_resume(worker_db, monkeypatch):
    # Simulate the distinct-value store left behind by a prior partial run. The
    # checkpoint carries no aggregation state at all — the store file IS the state.
    from app.config import get_settings
    from app.last9.aggregate import AggregationSpec, Aggregator
    from app.last9.distinct_store import DistinctStore, store_path

    prior_store = DistinctStore(store_path(get_settings().storage_dir, 1), fresh=True)
    prior = Aggregator(
        AggregationSpec(
            regex=PATTERN, group_by=AGG["group_by"], unique_fields=AGG["unique_fields"]
        ),
        prior_store,
    )
    prior.feed(_line("AHA-1-aaa", "CGetEntitlementsCommand", "1001", "AHA INDIA"))
    prior.flush()
    prior_store.close()
    checkpoint = {
        "completed_chunks": 1,
        "rows_written": 1,
        "current_chunk_start": 0,
        "next_chunk_start": 3600,
        "file_offset": 0,
        "chunk_hours": 1,
    }
    _seed(worker_db, aggregation=AGG, checkpoint=checkpoint, start=3600, end=7200)
    # Post-resume: one more row, a NEW distinct spid in the same group.
    new_row = LogRow("2", _line("AHA-1-bbb", "CGetEntitlementsCommand", "1002", "AHA INDIA"), "")
    monkeypatch.setattr(runner, "iter_extraction", _fake_iter_rows([new_row], chunk_end=7200))

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    snap = job["aggregation_result"]
    # 2 distinct spids total across BOTH the pre-resume and post-resume rows.
    g = next(
        g
        for g in snap["groups"]
        if g["key"] == {"api": "CGetEntitlementsCommand", "BU": "AHA INDIA"}
    )
    assert g["unique_counts"]["spid"] == 2


def test_raw_csv_carries_parsed_fields_as_real_columns(worker_db, monkeypatch):
    """So reading a field never needs Text-to-Columns in Excel, which re-parses
    the fragments and turns a numeric id into 2.30702E+23 regardless of how the
    file was written."""
    import csv

    _seed(worker_db, aggregation=AGG)
    rows = [
        LogRow(
            "1",
            _line("AHA-1-aaa", "CGetEntitlementsCommand", "230702032635917346995349", "AHA INDIA"),
            "",
        ),
        LogRow("2", "this line matches nothing", ""),
    ]
    monkeypatch.setattr(runner, "iter_extraction", _fake_iter_rows(rows))

    runner.run_extraction(1)

    with worker_db.engine().begin() as conn:
        job = dict(worker_db.load(conn, worker_db.jobs, 1))
    parsed = list(csv.reader(read_export(job["output_file_path"])))

    # log_format first, then the fields the aggregation is about.
    assert parsed[0] == ["timestamp_utc", "log_format", "api", "BU", "spid", "trackerid", "message"]
    matched = parsed[1]
    assert matched[1] == "pattern"
    assert matched[3] == "AHA INDIA"
    assert matched[4] == "230702032635917346995349"  # plain by default; digits intact
    # An unmatched row keeps its place with blank fields rather than vanishing.
    unmatched = parsed[2]
    assert unmatched[1:6] == ["", "", "", "", ""]
    assert unmatched[6] == "this line matches nothing"
