"""Jobs API: create (dispatch mocked), control transitions, signed download."""

from __future__ import annotations

import pytest

import app.routers.jobs as jobs_router
from app import signing
from app.models import Job

pytestmark = pytest.mark.usefixtures("job_refs")


def _create(client, monkeypatch, **over):
    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    body = {
        "credential_id": 1,
        "index_target_id": 1,
        "region_code": "ap-southeast-1",
        "start_epoch": 0,
        "end_epoch": 7200,
        "phrases": ["GetEntitlements"],
        "ids": ["ID-A", "ID-B"],
    }
    body.update(over)
    return client.post("/jobs", json=body)


def test_create_queues_job_and_stores_filter(client, monkeypatch):
    resp = _create(client, monkeypatch)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "queued"
    assert data["filter_spec"] == {
        "phrases": ["GetEntitlements"],
        "ids": ["ID-A", "ID-B"],
        "message_types": [],
    }
    assert data["download_url"] is None


def test_control_transitions(client, monkeypatch):
    jid = _create(client, monkeypatch).json()["id"]
    assert client.post(f"/jobs/{jid}/pause").json()["status"] == "paused"
    assert client.post(f"/jobs/{jid}/resume").json()["status"] == "queued"
    assert client.post(f"/jobs/{jid}/cancel").json()["status"] == "canceled"
    assert client.post(f"/jobs/{jid}/cancel").status_code == 409


def test_bulk_cancel_cancels_active_jobs_and_reports_skips(client, monkeypatch):
    active1 = _create(client, monkeypatch).json()["id"]
    active2 = _create(client, monkeypatch).json()["id"]
    already_done = _create(client, monkeypatch).json()["id"]
    client.post(f"/jobs/{already_done}/cancel")

    resp = client.post(
        "/jobs/bulk-cancel",
        json={"job_ids": [active1, active2, already_done, 9999]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(body["canceled"]) == sorted([active1, active2])
    assert body["skipped"] == {str(already_done): "canceled", "9999": "not_found"}

    assert client.get(f"/jobs/{active1}").json()["status"] == "canceled"
    assert client.get(f"/jobs/{active2}").json()["status"] == "canceled"


def test_bulk_cancel_deduplicates_repeated_ids(client, monkeypatch):
    jid = _create(client, monkeypatch).json()["id"]
    resp = client.post("/jobs/bulk-cancel", json={"job_ids": [jid, jid, jid]})
    assert resp.json()["canceled"] == [jid]


def test_bulk_cancel_empty_list_is_a_no_op(client, monkeypatch):
    resp = client.post("/jobs/bulk-cancel", json={"job_ids": []})
    assert resp.status_code == 200
    assert resp.json() == {"canceled": [], "skipped": {}}


def test_list_and_get(client, monkeypatch):
    jid = _create(client, monkeypatch).json()["id"]
    assert len(client.get("/jobs").json()) == 1
    assert client.get(f"/jobs/{jid}").json()["id"] == jid
    assert client.get("/jobs/9999").status_code == 404


def test_download_rejects_bad_signature(client, monkeypatch):
    jid = _create(client, monkeypatch).json()["id"]
    assert client.get(f"/jobs/{jid}/download?exp=9999999999&sig=bad").status_code == 403


def test_signed_download_serves_completed_file(client, monkeypatch, tmp_path):
    jid = _create(client, monkeypatch).json()["id"]
    csv = tmp_path / "out.csv"
    csv.write_text("timestamp,message\n1,hello\n", encoding="utf-8")

    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "completed"
        job.output_file_path = str(csv)
        db.commit()

    # Completed jobs expose a signed download_url.
    url = client.get(f"/jobs/{jid}").json()["download_url"]
    assert url is not None
    resp = client.get(url)
    assert resp.status_code == 200
    assert "hello" in resp.text
    # The file on disk is plain CSV, not a zip — the download must say so too.
    assert ".zip" not in resp.headers["content-disposition"]
    assert resp.headers["content-type"].startswith("text/csv")

    # Tampered signature is rejected.
    assert client.get(signing.make_download_url(jid).replace("sig=", "sig=x")).status_code == 403


def test_signed_download_of_an_actually_zipped_file_keeps_the_zip_name(
    client, monkeypatch, tmp_path
):
    jid = _create(client, monkeypatch).json()["id"]
    zip_path = tmp_path / "out.csv.zip"
    zip_path.write_bytes(b"PK\x05\x06" + b"\x00" * 18)  # minimal empty-zip EOCD

    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "completed"
        job.output_file_path = str(zip_path)
        db.commit()

    resp = client.get(client.get(f"/jobs/{jid}").json()["download_url"])
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].count(".zip") == 1
    assert resp.headers["content-type"] == "application/zip"


def test_preview_job_download_is_not_misnamed_as_a_zip(client, monkeypatch, tmp_path):
    """Reproduces job 588: a "Test filter" preview never gets its raw output
    compressed (worker/app/runner.py), but the DB still points at that file —
    so the download must not claim it's a zip just because most jobs are."""
    jid = _create(client, monkeypatch).json()["id"]
    csv = tmp_path / "preview.csv"
    csv.write_text("timestamp,message\n1,hello\n", encoding="utf-8")

    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "completed"
        job.is_preview = True
        job.output_file_path = str(csv)
        db.commit()

    resp = client.get(client.get(f"/jobs/{jid}").json()["download_url"])
    assert resp.status_code == 200
    assert ".zip" not in resp.headers["content-disposition"]
    assert resp.headers["content-type"].startswith("text/csv")


def test_retry_carries_schedule_ownership_and_rollup_marker(client, monkeypatch):
    """A retried job must stay attached to its schedule, and stay a rollup.

    Losing `created_by` detached a retried scheduled day from `schedule:N`, so
    the month-end rollup skipped it and under-reported. Losing `rollup_of`
    turned a retried rollup into a plain extraction that re-queries Last9 for
    the whole month instead of merging the day stores.
    """
    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    created = _create(client, monkeypatch).json()

    session = client.session_factory()
    orig = session.get(Job, created["id"])
    orig.status = "failed"
    orig.created_by = "schedule:42"
    orig.rollup_of = {"schedule_id": 42, "label": "2026-08"}
    session.commit()
    session.close()

    resp = client.post(f"/jobs/{created['id']}/retry")
    assert resp.status_code == 201

    session = client.session_factory()
    retried = session.get(Job, resp.json()["id"])
    assert retried.created_by == "schedule:42"
    assert retried.rollup_of == {"schedule_id": 42, "label": "2026-08"}
    session.close()


def test_retry_repoints_a_deleted_credential_at_the_sources_current_one(
    client, monkeypatch, job_refs
):
    from app.models import IndexTarget, Last9Credential

    jid = _create(client, monkeypatch).json()["id"]
    db = client.session_factory()
    db.query(Last9Credential).filter_by(id=1).delete()
    db.add(
        Last9Credential(
            id=2,
            label="new",
            org_slug="testorg",
            encrypted_refresh_token="x",
            refresh_token_last4="abcd",
        )
    )
    db.query(IndexTarget).filter_by(id=1).update({"credential_id": 2})
    db.query(Job).filter_by(id=jid).update({"status": "failed"})
    db.commit()
    db.close()

    resp = client.post(f"/jobs/{jid}/retry")
    assert resp.status_code == 201
    assert resp.json()["credential_id"] == 2
