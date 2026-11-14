"""Group extraction: one shared window, one job per saved search."""

from __future__ import annotations

import pytest

import app.routers.jobs as jobs_router
import app.tasks_client as tasks_client
from app.models import Job

pytestmark = pytest.mark.usefixtures("job_refs")


def _template(client, name, **over):
    body = {
        "name": name,
        "phrases": ["ClassName"],
        "ids": ["Ekkl"],
        "message_types": [],
        "customer": "TEST_CUSTOMER",
        "credential_id": 1,
        "index_target_id": 1,
        "region_code": "ap-southeast-1",
    }
    body.update(over)
    response = client.post("/templates", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _group(client, monkeypatch, items, **over):
    monkeypatch.setattr(tasks_client, "dispatch_job", lambda _id: None)
    body = {
        "name": "Month end",
        "items": [{"template_id": template_id} for template_id in items],
        "start_epoch": 0,
        "end_epoch": 86400,
    }
    body.update(over)
    return client.post("/groups", json=body)


def test_group_creates_one_job_per_search_and_is_listed(client, monkeypatch):
    a = _template(client, "INVOICE_EKKL")
    b = _template(client, "INVOICE_ABSCBN")

    response = _group(client, monkeypatch, [a["id"], b["id"]])
    assert response.status_code == 201, response.text
    group = response.json()

    assert group["name"] == "Month end"
    assert group["status"] == "queued"
    assert group["total_jobs"] == 2
    assert group["completed"] == group["failed"] == 0
    assert group["rows_written"] == 0
    assert {job["group_id"] for job in group["jobs"]} == {group["id"]}
    assert {job["filter_spec"]["label"] for job in group["jobs"]} == {
        "INVOICE_EKKL",
        "INVOICE_ABSCBN",
    }

    listed = client.get("/groups").json()
    assert len(listed) == 1
    assert listed[0]["id"] == group["id"]
    assert listed[0]["total_jobs"] == 2

    detail = client.get(f"/groups/{group['id']}").json()
    assert len(detail["jobs"]) == 2
    assert detail["status"] == "queued"

    # The list endpoint carries the group link on each job too.
    jobs = client.get("/jobs?limit=200").json()
    assert {job["group_id"] for job in jobs} == {group["id"]}


def test_group_uses_each_search_saved_source(client, monkeypatch):
    # A second source, so the group has to resolve per item instead of one
    # shared source for the whole request.
    from app.models import IndexTarget, Last9Credential

    with client.session_factory() as db:
        db.add(
            Last9Credential(
                id=2,
                label="other",
                org_slug="otherorg",
                encrypted_refresh_token="x",
                refresh_token_last4="efgh",
            )
        )
        db.add(
            IndexTarget(
                id=2,
                name="other-index",
                region_code="ap-south-1",
                full_index_string="otherorg:UMServices",
                credential_id=2,
            )
        )
        db.commit()

    a = _template(client, "SINGAPORE")
    b = _template(
        client,
        "INDIA",
        credential_id=2,
        index_target_id=2,
        region_code="ap-south-1",
    )
    group = _group(client, monkeypatch, [a["id"], b["id"]]).json()
    by_label = {job["filter_spec"]["label"]: job for job in group["jobs"]}
    assert by_label["SINGAPORE"]["index_target_id"] == 1
    assert by_label["INDIA"]["index_target_id"] == 2
    assert by_label["INDIA"]["region_code"] == "ap-south-1"


def test_group_rejects_sourceless_search_and_creates_nothing(client, monkeypatch):
    t = _template(client, "SOURCELESS", credential_id=None, index_target_id=None, region_code=None)
    response = _group(client, monkeypatch, [t["id"]])
    assert response.status_code == 422
    assert "SOURCELESS" in response.json()["detail"]
    assert client.get("/groups").json() == []
    assert client.get("/jobs?limit=200").json() == []


def test_group_cancel_stops_active_jobs(client, monkeypatch):
    a = _template(client, "A")
    b = _template(client, "B")
    group = _group(client, monkeypatch, [a["id"], b["id"]]).json()

    response = client.post(f"/groups/{group['id']}/cancel")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "canceled"
    assert body["canceled"] == 2
    assert all(job["status"] == "canceled" for job in body["jobs"])


def test_group_status_and_rows_are_derived_from_jobs(client, monkeypatch):
    a = _template(client, "A")
    b = _template(client, "B")
    group = _group(client, monkeypatch, [a["id"], b["id"]]).json()

    with client.session_factory() as db:
        first, second = group["jobs"][0]["id"], group["jobs"][1]["id"]
        db.get(Job, first).status = "completed"
        db.get(Job, first).rows_written = 120
        db.get(Job, second).status = "failed"
        db.get(Job, second).error_message = "Last9 502"
        db.commit()

    detail = client.get(f"/groups/{group['id']}").json()
    assert detail["status"] == "partial"
    assert detail["completed"] == 1
    assert detail["failed"] == 1
    assert detail["rows_written"] == 120


def test_group_retry_creates_a_child_group_with_only_failures(client, monkeypatch):
    a = _template(client, "RETRY_A")
    b = _template(client, "RETRY_B")
    group = _group(client, monkeypatch, [a["id"], b["id"]]).json()

    with client.session_factory() as db:
        first, second = group["jobs"][0]["id"], group["jobs"][1]["id"]
        db.get(Job, first).status = "failed"
        db.get(Job, first).error_message = "boom"
        db.get(Job, second).status = "completed"
        db.get(Job, second).rows_written = 5
        db.commit()

    monkeypatch.setattr(tasks_client, "dispatch_job", lambda _id: None)
    response = client.post(f"/groups/{group['id']}/retry")
    assert response.status_code == 201, response.text
    retry = response.json()

    assert retry["parent_group_id"] == group["id"]
    assert retry["name"].endswith("(retry)")
    assert retry["total_jobs"] == 1
    assert retry["jobs"][0]["filter_spec"]["label"] == "RETRY_A"
    assert retry["jobs"][0]["status"] == "queued"
    assert retry["jobs"][0]["group_id"] == retry["id"]
    assert retry["jobs"][0]["group_id"] != group["id"]

    # The original group keeps its history.
    original = client.get(f"/groups/{group['id']}").json()
    assert original["status"] == "partial"
    assert original["failed"] == 1


def test_group_retry_without_failures_is_rejected(client, monkeypatch):
    a = _template(client, "A")
    group = _group(client, monkeypatch, [a["id"]]).json()
    with client.session_factory() as db:
        db.get(Job, group["jobs"][0]["id"]).status = "completed"
        db.commit()
    assert client.post(f"/groups/{group['id']}/retry").status_code == 422


def test_batch_endpoint_now_creates_a_group(client, monkeypatch):
    a = _template(client, "BATCH_A")
    b = _template(client, "BATCH_B")
    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    response = client.post(
        "/jobs/batch",
        json={
            "items": [{"template_id": a["id"]}, {"template_id": b["id"]}],
            "start_epoch": 0,
            "end_epoch": 86400,
        },
    )
    assert response.status_code == 201, response.text
    jobs = response.json()
    group_ids = {job["group_id"] for job in jobs}
    assert len(group_ids) == 1
    assert None not in group_ids
    groups = client.get("/groups").json()
    assert [group["id"] for group in groups] == list(group_ids)


def test_one_search_batch_does_not_create_a_group(client, monkeypatch):
    a = _template(client, "QUICK_A")
    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    response = client.post(
        "/jobs/batch",
        json={"items": [{"template_id": a["id"]}], "start_epoch": 0, "end_epoch": 86400},
    )
    assert response.status_code == 201, response.text
    assert response.json()[0]["group_id"] is None
    assert client.get("/groups").json() == []
