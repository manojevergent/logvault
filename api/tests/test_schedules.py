"""Schedules list: last-run badge resolution."""

from __future__ import annotations

from app.models import Job


def _schedule(client, name: str) -> int:
    response = client.post(
        "/schedules",
        json={
            "name": name,
            "interval_seconds": 86400,
            "lookback_seconds": 86400,
            "credential_id": 1,
            "index_target_id": 1,
            "region_code": "ap-southeast-1",
            "phrases": ["error"],
            "customer": "ACME",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_schedule_keeps_exclusions(client, job_refs):
    response = client.post(
        "/schedules",
        json={
            "name": "exclude-schedule",
            "interval_seconds": 86400,
            "lookback_seconds": 86400,
            "credential_id": 1,
            "index_target_id": 1,
            "region_code": "ap-southeast-1",
            "phrases": ["error"],
            "exclude_phrases": ["healthcheck"],
            "exclude_exact_phrases": ["API : 502"],
            "customer": "ACME",
        },
    )
    assert response.status_code == 201, response.text
    spec = response.json()["filter_spec"]
    assert spec["exclude_phrases"] == ["healthcheck"]
    assert spec["exclude_exact_phrases"] == ["API : 502"]


def test_list_resolves_each_schedules_latest_job(client, job_refs):
    first = _schedule(client, "first")
    second = _schedule(client, "second")

    with client.session_factory() as db:
        db.add_all(
            [
                Job(
                    id=101,
                    status="completed",
                    region_code="ap-southeast-1",
                    index_target_id=1,
                    credential_id=1,
                    start_epoch=0,
                    end_epoch=3600,
                    filter_spec={},
                    created_by=f"schedule:{first}",
                ),
                Job(
                    id=102,
                    status="completed",
                    region_code="ap-southeast-1",
                    index_target_id=1,
                    credential_id=1,
                    start_epoch=0,
                    end_epoch=3600,
                    filter_spec={},
                    created_by=f"schedule:{first}",
                ),
                Job(
                    id=103,
                    status="failed",
                    region_code="ap-southeast-1",
                    index_target_id=1,
                    credential_id=1,
                    start_epoch=0,
                    end_epoch=3600,
                    filter_spec={},
                    created_by=f"schedule:{second}",
                ),
            ]
        )
        db.commit()

    listed = {s["name"]: s for s in client.get("/schedules").json()}
    assert listed["first"]["last_run_job_id"] == 102  # newest, not 101
    assert listed["second"]["last_run_job_id"] == 103


def test_list_has_no_last_job_before_anything_runs(client, job_refs):
    _schedule(client, "never ran")
    listed = client.get("/schedules").json()
    assert listed[0]["last_run_job_id"] is None
