"""Deleting a customer removes exactly the jobs it groups, plus their files."""

from __future__ import annotations

import os

import pytest

from app.config import get_settings
from app.models import Job, JobEvent

pytestmark = pytest.mark.usefixtures("job_refs")


def _job(db, jid, *, customer=None, label=None, status="completed", files=()):
    db.add(
        Job(
            id=jid,
            status=status,
            region_code="ap-south-1",
            index_target_id=1,
            credential_id=1,
            start_epoch=0,
            end_epoch=3600,
            filter_spec={"phrases": [], "ids": [], "customer": customer, "label": label},
            output_format="csv",
            is_preview=False,
        )
    )
    return files


def _touch(path):
    with open(path, "wb") as fh:
        fh.write(b"x")
    return str(path)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Point the export dir at a temp dir so file removal is observable."""
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    return tmp_path


def _ids(client):
    return {j["id"] for j in client.get("/jobs?limit=1000").json()}


def test_delete_customer_removes_its_jobs_files_and_stores(client, storage):
    out1 = _touch(storage / "job_1.csv.zip")
    out2 = _touch(storage / "job_2.csv.zip")
    summary2 = _touch(storage / "job_2.summary.csv.zip")
    store2 = _touch(storage / "job_2.distinct.sqlite")
    other = _touch(storage / "job_3.csv.zip")

    with client.session_factory() as db:
        _job(db, 1, customer="ABSCBN")
        _job(db, 2, customer="ABSCBN")
        _job(db, 3, customer="EKKL")
        db.commit()
        db.get(Job, 1).output_file_path = out1
        db.get(Job, 2).output_file_path = out2
        db.get(Job, 2).summary_file_path = summary2
        db.add(JobEvent(job_id=1, level="info", message="Job started", rows_delta=0))
        db.commit()

    resp = client.delete("/customers", params={"name": "ABSCBN"})
    assert resp.status_code == 200
    body = resp.json()
    # job_1.csv.zip + job_2.csv.zip + job_2.summary.csv.zip + job_2 distinct store
    assert body == {"customer": "ABSCBN", "deleted_jobs": 2, "deleted_files": 4}

    assert _ids(client) == {3}
    for path in (out1, out2, summary2, store2):
        assert not os.path.exists(path), f"{path} should be deleted"
    assert os.path.exists(other), "another customer's file must survive"
    with client.session_factory() as db:
        assert db.query(JobEvent).filter(JobEvent.job_id == 1).count() == 0


def test_a_job_falls_back_to_its_label_when_no_customer_is_set(client, storage):
    """The Customers page groups that way, so delete must match the same rule."""
    with client.session_factory() as db:
        _job(db, 1, label="AHA_CgetEntitlements")
        _job(db, 2, customer="AHA")
        db.commit()

    resp = client.delete("/customers", params={"name": "AHA_CgetEntitlements"})
    assert resp.status_code == 200
    assert resp.json()["deleted_jobs"] == 1
    assert _ids(client) == {2}


def test_preview_files_are_removed_even_though_the_path_is_not_stored(client, storage):
    """A preview run writes job_<id>.csv but never records output_file_path, so
    looking at the column alone would leak the file."""
    preview_file = _touch(storage / "job_5.csv")
    with client.session_factory() as db:
        _job(db, 5, customer="PREVIEWONLY")
        db.commit()

    resp = client.delete("/customers", params={"name": "PREVIEWONLY"})
    assert resp.status_code == 200
    assert resp.json()["deleted_files"] == 1
    assert not os.path.exists(preview_file)


def test_an_unknown_customer_is_404(client):
    assert client.delete("/customers", params={"name": "NOPE"}).status_code == 404


def test_active_jobs_must_be_cancelled_first(client, storage):
    with client.session_factory() as db:
        _job(db, 1, customer="ABSCBN", status="running")
        db.commit()

    resp = client.delete("/customers", params={"name": "ABSCBN"})
    assert resp.status_code == 409
    assert "cancel them first" in resp.json()["detail"]
    assert _ids(client) == {1}


def test_the_unassigned_bucket_is_not_a_customer(client):
    resp = client.delete("/customers", params={"name": "(unassigned)"})
    assert resp.status_code == 400
