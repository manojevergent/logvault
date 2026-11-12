"""Jobs API: create (dispatch mocked), control transitions, signed download."""

from __future__ import annotations

import zipfile

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
        "label": "TEST_SEARCH",
    }
    body.update(over)
    return client.post("/jobs", json=body)


def test_create_keeps_exclusions_in_the_filter_spec(client, monkeypatch):
    resp = _create(
        client,
        monkeypatch,
        exclude_phrases=["healthcheck"],
        exclude_exact_phrases=["API : 502"],
    )
    assert resp.status_code == 201, resp.text
    spec = resp.json()["filter_spec"]
    assert spec["exclude_phrases"] == ["healthcheck"]
    assert spec["exclude_exact_phrases"] == ["API : 502"]


def test_create_queues_job_and_stores_filter(client, monkeypatch):
    resp = _create(client, monkeypatch)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "queued"
    assert data["filter_spec"] == {
        "phrases": ["GetEntitlements"],
        "ids": ["ID-A", "ID-B"],
        "exact_phrases": [],
        "exclude_phrases": [],
        "exclude_exact_phrases": [],
        "message_types": [],
        "label": "TEST_SEARCH",
    }
    assert data["download_url"] is None


def test_create_requires_non_empty_label(client, monkeypatch):
    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post(
        "/jobs",
        json={
            "credential_id": 1,
            "index_target_id": 1,
            "region_code": "ap-southeast-1",
            "start_epoch": 0,
            "end_epoch": 7200,
            "phrases": ["GetEntitlements"],
            "label": "",
        },
    )
    assert resp.status_code == 422
    assert "Search Name" in resp.json()["detail"]


def test_delete_job_files_deletes_files_and_clears_db_paths(client, monkeypatch, tmp_path):
    jid = _create(client, monkeypatch).json()["id"]
    out_file = tmp_path / "out.csv.zip"
    summary_file = tmp_path / "summary.csv.zip"
    out_file.write_bytes(b"zip1")
    summary_file.write_bytes(b"zip2")

    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "completed"
        job.output_file_path = str(out_file)
        job.summary_file_path = str(summary_file)
        db.commit()

    # Active job cannot delete files
    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "running"
        db.commit()
    assert client.delete(f"/jobs/{jid}/files").status_code == 409

    # Completed job deletes files
    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "completed"
        db.commit()

    resp = client.delete(f"/jobs/{jid}/files")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_output"] is False
    assert data["has_summary"] is False
    assert not out_file.exists()
    assert not summary_file.exists()


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


def test_list_hides_previews_unless_asked(client, monkeypatch):
    """Filter-test runs stay out of the Jobs list (they would drown it —
    every Test filter click is a job row) until ?include_previews=true."""
    real = _create(client, monkeypatch).json()["id"]
    prev = _create(client, monkeypatch, is_preview=True).json()["id"]

    listed = client.get("/jobs").json()
    assert [j["id"] for j in listed] == [real]

    listed = client.get("/jobs", params={"include_previews": "true"}).json()
    assert {j["id"] for j in listed} == {real, prev}
    assert [j for j in listed if j["id"] == prev][0]["is_preview"] is True


def test_list_previews_only_returns_only_previews(client, monkeypatch):
    _create(client, monkeypatch)
    prev = _create(client, monkeypatch, is_preview=True).json()["id"]

    listed = client.get("/jobs", params={"previews_only": "true"}).json()
    assert [j["id"] for j in listed] == [prev]


def test_stats_reports_whole_table_totals(client, monkeypatch):
    """The list is page-limited; headline numbers must not be derived from it."""
    a = _create(client, monkeypatch).json()["id"]
    b = _create(client, monkeypatch).json()["id"]
    _create(client, monkeypatch, is_preview=True)

    with client.session_factory() as db:
        db.get(Job, a).rows_written = 10
        row_b = db.get(Job, b)
        row_b.rows_written = 5
        row_b.status = "completed"
        db.commit()

    stats = client.get("/jobs/stats").json()
    assert stats["total"] == 2
    assert stats["rows_written"] == 15
    assert stats["previews"] == 1
    assert stats["by_status"]["completed"] == 1
    assert stats["by_status"]["queued"] == 1

    # Status filtering on the list still works alongside the aggregate.
    completed = client.get("/jobs", params={"status": "completed"}).json()
    assert [j["id"] for j in completed] == [b]


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


def test_unmatched_artifact_is_exposed_and_downloadable(client, monkeypatch, tmp_path):
    jid = _create(client, monkeypatch).json()["id"]
    raw = tmp_path / "out.csv"
    raw.write_text("timestamp,message\n1,matched\n", encoding="utf-8")
    unmatched = tmp_path / "unmatched.csv"
    unmatched.write_text("timestamp,message\n1,no match\n", encoding="utf-8")

    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "completed"
        job.output_file_path = str(raw)
        job.unmatched_file_path = str(unmatched)
        db.commit()

    body = client.get(f"/jobs/{jid}").json()
    assert body["has_unmatched"] is True
    assert body["unmatched_url"]

    resp = client.get(body["unmatched_url"])
    assert resp.status_code == 200
    assert "no match" in resp.text
    assert "unmatched" in resp.headers["content-disposition"]

    txt = client.get(f"{body['unmatched_url']}&format=txt")
    assert txt.status_code == 200
    assert txt.text.startswith("timestamp,message")


def test_canceled_job_exposes_its_partial_output(client, monkeypatch, tmp_path):
    jid = _create(client, monkeypatch).json()["id"]
    partial = tmp_path / "partial.csv"
    partial.write_text("timestamp,message\n1,kept before cancel\n", encoding="utf-8")

    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "canceled"
        job.output_file_path = str(partial)
        job.rows_written = 1
        db.commit()

    body = client.get(f"/jobs/{jid}").json()
    assert body["download_url"]
    resp = client.get(body["download_url"])
    assert resp.status_code == 200
    assert "kept before cancel" in resp.text


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


def test_txt_download_serves_plain_csv_as_comma_separated_text(client, monkeypatch, tmp_path):
    jid = _create(client, monkeypatch).json()["id"]
    csv = tmp_path / "out.csv"
    csv.write_bytes(b"timestamp,message\n1,hello,world\n")

    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "completed"
        job.output_file_path = str(csv)
        db.commit()

    url = client.get(f"/jobs/{jid}").json()["download_url"]
    resp = client.get(f"{url}&format=txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert (
        'filename="TEST_SEARCH_1_1970-01-01_0000-0159.txt"' in resp.headers["content-disposition"]
    )
    assert resp.text == "timestamp,message\n1,hello,world\n"


def test_txt_download_decompresses_a_zipped_csv(client, monkeypatch, tmp_path):
    jid = _create(client, monkeypatch).json()["id"]
    zip_path = tmp_path / "out.csv.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("TEST_SEARCH_1.csv", "timestamp,message\n1,zipped\n")

    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "completed"
        job.output_file_path = str(zip_path)
        db.commit()

    resp = client.get(f"{client.get(f'/jobs/{jid}').json()['download_url']}&format=txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text == "timestamp,message\n1,zipped\n"


def test_txt_download_of_summary_keeps_the_artifact_name(client, monkeypatch, tmp_path):
    jid = _create(client, monkeypatch).json()["id"]
    summary = tmp_path / "summary.csv"
    summary.write_bytes(b"api,unique_spid\nA,3\n")

    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "completed"
        job.summary_file_path = str(summary)
        db.commit()

    url = client.get(f"/jobs/{jid}").json()["summary_url"]
    resp = client.get(f"{url}&format=txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "TEST_SEARCH_1_" in resp.headers["content-disposition"]
    assert "_summary.txt" in resp.headers["content-disposition"]
    assert resp.text == "api,unique_spid\nA,3\n"


def test_txt_download_rejects_jsonl_extracts(client, monkeypatch, tmp_path):
    jid = _create(client, monkeypatch, output_format="jsonl").json()["id"]
    jsonl = tmp_path / "out.jsonl"
    jsonl.write_text('{"timestamp": "1", "message": "hello"}\n', encoding="utf-8")

    with client.session_factory() as db:
        job = db.get(Job, jid)
        job.status = "completed"
        job.output_file_path = str(jsonl)
        db.commit()

    url = client.get(f"/jobs/{jid}").json()["download_url"]
    resp = client.get(f"{url}&format=txt")
    assert resp.status_code == 400
    assert "comma-separated" in resp.json()["detail"]


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
