"""Rollup creation: which schedules can be rolled up, and which runs get picked."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import Job, Schedule


@pytest.fixture
def db_session(client):
    s = client.session_factory()
    yield s
    s.close()


PATTERN = r"SPAccountId\s+(?<spid>\d+)\s+in\s+BU\s+(?<BU>.*?)\s+API"
AGG = {"enabled": True, "regex": PATTERN, "group_by": ["BU"], "unique_fields": ["spid"]}


def _epoch(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp())


AUG = {"start_epoch": _epoch(2026, 8, 1), "end_epoch": _epoch(2026, 9, 1)}


def _schedule(session, sid: int = 1, *, aggregation=AGG) -> Schedule:
    spec = {"phrases": [], "ids": []}
    if aggregation:
        spec["aggregation"] = aggregation
    s = Schedule(
        id=sid,
        name="Daily UMServices",
        enabled=True,
        interval_seconds=86400,
        lookback_seconds=86400,
        calendar_day=True,
        region_code="ap-south-1",
        index_target_id=1,
        credential_id=1,
        chunk_hours=1,
        id_batch_size=100,
        output_format="csv",
        filter_spec=spec,
    )
    session.add(s)
    session.commit()
    return s


def _run(session, jid: int, sid: int, day: int, status: str = "completed") -> None:
    session.add(
        Job(
            id=jid,
            status=status,
            region_code="ap-south-1",
            index_target_id=1,
            credential_id=1,
            start_epoch=_epoch(2026, 8, day),
            end_epoch=_epoch(2026, 8, day + 1),
            chunk_hours=1,
            id_batch_size=100,
            filter_spec={"phrases": [], "ids": [], "aggregation": AGG},
            created_by=f"schedule:{sid}",
        )
    )
    session.commit()


def _no_dispatch(monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)


def test_rollup_job_records_the_runs_it_will_merge(client, db_session, monkeypatch):
    _no_dispatch(monkeypatch)
    _schedule(db_session)
    _run(db_session, 10, 1, 1)
    _run(db_session, 11, 1, 2)

    resp = client.post("/jobs/rollup", json={"schedule_id": 1, "label": "2026-08", **AUG})
    assert resp.status_code == 201
    body = resp.json()
    assert body["rollup_of"]["source_job_ids"] == [10, 11]
    assert body["rollup_of"]["label"] == "2026-08"
    # It inherits the schedule's aggregation spec — the counts must be defined
    # the same way they were on each day, or merging them is meaningless.
    assert body["filter_spec"]["aggregation"]["unique_fields"] == ["spid"]


def test_incomplete_runs_are_not_offered_for_merging(client, db_session, monkeypatch):
    _no_dispatch(monkeypatch)
    _schedule(db_session)
    _run(db_session, 10, 1, 1)
    _run(db_session, 11, 1, 2, status="failed")

    resp = client.post("/jobs/rollup", json={"schedule_id": 1, **AUG})
    assert resp.json()["rollup_of"]["source_job_ids"] == [10]


def test_schedule_without_aggregation_cannot_be_rolled_up(client, db_session, monkeypatch):
    _no_dispatch(monkeypatch)
    _schedule(db_session, aggregation=None)
    _run(db_session, 10, 1, 1)

    resp = client.post("/jobs/rollup", json={"schedule_id": 1, **AUG})
    assert resp.status_code == 422
    assert "parse & aggregate" in resp.json()["detail"]


def test_period_with_no_runs_is_rejected(client, db_session, monkeypatch):
    _no_dispatch(monkeypatch)
    _schedule(db_session)
    _run(db_session, 10, 1, 1)

    resp = client.post(
        "/jobs/rollup",
        json={
            "schedule_id": 1,
            "start_epoch": _epoch(2026, 9, 1),
            "end_epoch": _epoch(2026, 10, 1),
        },
    )
    assert resp.status_code == 422
    assert "no completed runs" in resp.json()["detail"]


def test_unknown_schedule_404s(client, monkeypatch):
    _no_dispatch(monkeypatch)
    resp = client.post("/jobs/rollup", json={"schedule_id": 999, **AUG})
    assert resp.status_code == 404


def test_backwards_period_is_rejected(client, db_session, monkeypatch):
    _no_dispatch(monkeypatch)
    _schedule(db_session)
    resp = client.post(
        "/jobs/rollup",
        json={"schedule_id": 1, "start_epoch": AUG["end_epoch"], "end_epoch": AUG["start_epoch"]},
    )
    assert resp.status_code == 422
