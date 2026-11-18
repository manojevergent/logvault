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


def test_schedule_alert_thresholds_round_trip(client, job_refs):
    response = client.post(
        "/schedules",
        json={
            "name": "anomaly-thresholds",
            "interval_seconds": 86400,
            "lookback_seconds": 86400,
            "calendar_day": True,
            "credential_id": 1,
            "index_target_id": 1,
            "region_code": "ap-southeast-1",
            "phrases": ["error"],
            "customer": "ACME",
            "alert_recipients": ["ops@example.com"],
            "alert_on_row_drop": True,
            "row_drop_threshold_pct": 25,
            "alert_on_unmatched": True,
            "unmatched_threshold": 50,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["alert_on_row_drop"] is True
    assert body["row_drop_threshold_pct"] == 25
    assert body["alert_on_unmatched"] is True
    assert body["unmatched_threshold"] == 50

    patched = client.patch(
        f"/schedules/{body['id']}",
        json={"row_drop_threshold_pct": 30, "unmatched_threshold": 75},
    )
    assert patched.status_code == 200, patched.text
    updated = patched.json()
    assert updated["row_drop_threshold_pct"] == 30
    assert updated["unmatched_threshold"] == 75


def test_schedule_alert_thresholds_are_bounded(client, job_refs):
    base = {
        "name": "bad-thresholds",
        "interval_seconds": 86400,
        "lookback_seconds": 86400,
        "credential_id": 1,
        "index_target_id": 1,
        "region_code": "ap-southeast-1",
        "phrases": ["error"],
    }
    assert (
        client.post("/schedules", json={**base, "row_drop_threshold_pct": 101}).status_code == 422
    )
    assert client.post("/schedules", json={**base, "unmatched_threshold": 0}).status_code == 422
