"""S3 destination profiles and their attachment to searches/jobs/schedules."""

from __future__ import annotations

import app.routers.jobs as jobs_router
from app import crypto


def _profile(client) -> int:
    response = client.post(
        "/s3-profiles",
        json={
            "name": "archive",
            "bucket": "acme-log-archive",
            "region": "us-east-1",
            "prefix": "logvault/prod",
            "access_key_id": "AKIA-test-1234",
            "secret_access_key": "secret-test",
            "force_path_style": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _template(client, s3_id: int) -> dict:
    response = client.post(
        "/templates",
        json={
            "name": "S3 search",
            "phrases": ["error"],
            "customer": "ACME",
            "s3_profile_id": s3_id,
            "credential_id": 1,
            "index_target_id": 1,
            "region_code": "ap-southeast-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_s3_profile_encrypts_keys_and_masks_output(client, job_refs):
    profile_id = _profile(client)
    listed = client.get("/s3-profiles").json()
    assert listed[0]["key_preview"] == "••••1234"
    assert "secret" not in listed[0]

    db = client.session_factory()
    from app.models import S3Profile

    profile = db.get(S3Profile, profile_id)
    assert profile is not None
    assert crypto.decrypt(profile.encrypted_access_key_id) == "AKIA-test-1234"
    assert crypto.decrypt(profile.encrypted_secret_access_key) == "secret-test"
    db.close()


def test_s3_profile_update_can_clear_stored_keys(client, job_refs):
    profile_id = _profile(client)
    response = client.put(
        f"/s3-profiles/{profile_id}",
        json={"name": "archive-2", "bucket": "acme-log-archive-2", "clear_credentials": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "archive-2"
    assert response.json()["key_preview"] == "instance role"


def test_s3_profile_test_endpoint_reports_result(client, job_refs, monkeypatch):
    profile_id = _profile(client)
    monkeypatch.setattr(
        "app.routers.s3_profiles.s3.test_profile", lambda _profile: "write succeeded"
    )
    response = client.post(f"/s3-profiles/{profile_id}/test")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "write succeeded"}


def test_saved_search_job_and_schedule_keep_s3_destination(client, job_refs, monkeypatch):
    profile_id = _profile(client)
    tpl = _template(client, profile_id)
    assert tpl["s3_profile_id"] == profile_id
    assert tpl["s3_profile_label"] == "archive"

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    job_response = client.post(
        "/jobs",
        json={
            "credential_id": 1,
            "index_target_id": 1,
            "region_code": "ap-southeast-1",
            "start_epoch": 0,
            "end_epoch": 7200,
            "phrases": ["error"],
            "label": "S3 search",
            "s3_profile_id": profile_id,
        },
    )
    assert job_response.status_code == 201, job_response.text
    job = job_response.json()
    assert job["s3_profile_id"] == profile_id
    assert job["s3_destination"] == {
        "profile_id": profile_id,
        "name": "archive",
        "bucket": "acme-log-archive",
        "region": "us-east-1",
        "prefix": "logvault/prod",
    }

    exported = client.get(f"/jobs/{job['id']}/export").json()
    assert exported["s3_profile"] == {"name": "archive"}

    schedule = client.post(
        "/schedules",
        json={
            "name": "daily S3",
            "interval_seconds": 86400,
            "lookback_seconds": 86400,
            "credential_id": 1,
            "index_target_id": 1,
            "region_code": "ap-southeast-1",
            "phrases": ["error"],
            "customer": "ACME",
            "s3_profile_id": profile_id,
        },
    )
    assert schedule.status_code == 201, schedule.text
    assert schedule.json()["s3_profile_id"] == profile_id
    assert schedule.json()["s3_profile_label"] == "archive"


def test_s3_profile_delete_is_blocked_while_used(client, job_refs):
    profile_id = _profile(client)
    _template(client, profile_id)
    response = client.delete(f"/s3-profiles/{profile_id}")
    assert response.status_code == 409
    assert "S3 search" in response.json()["detail"] or "archive" in response.json()["detail"]


def test_batch_jobs_inherit_the_saved_search_s3_destination(client, job_refs, monkeypatch):
    profile_id = _profile(client)
    tpl = _template(client, profile_id)
    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    response = client.post(
        "/jobs/batch",
        json={
            "items": [{"template_id": tpl["id"]}],
            "start_epoch": 0,
            "end_epoch": 7200,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()[0]["s3_profile_id"] == profile_id
