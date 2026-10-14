"""The jobs list is polled every few seconds by every open tab, so it is the one
endpoint whose payload and row count have to stay bounded.
"""

from __future__ import annotations

import pytest

import app.routers.jobs as jobs_router

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
        "ids": [f"ID-{n}" for n in range(500)],
        "label": "AHA_CGetEntitlements",
        "customer": "AHA",
    }
    body.update(over)
    return client.post("/jobs", json=body)


def test_list_omits_the_bulky_filter_spec_but_keeps_what_lists_render(client, monkeypatch):
    _create(client, monkeypatch)

    row = client.get("/jobs").json()[0]
    # The label and customer are what the jobs and customers pages group by.
    assert row["filter_spec"] == {"label": "AHA_CGetEntitlements", "customer": "AHA"}
    # 500 account IDs have no business being re-sent on every poll.
    assert "ids" not in row["filter_spec"]
    assert "phrases" not in row["filter_spec"]
    # Detail-only payloads stay out of the list entirely.
    assert row["preview"] is None
    assert row["aggregation_result"] is None
    assert row["rollup_of"] is None

    # ...and the single-job fetch still carries everything, so cloning a job works.
    full = client.get(f"/jobs/{row['id']}").json()
    assert len(full["filter_spec"]["ids"]) == 500
    assert full["filter_spec"]["phrases"] == ["GetEntitlements"]


def test_list_is_bounded_and_pages(client, monkeypatch):
    for _ in range(5):
        _create(client, monkeypatch)

    assert len(client.get("/jobs").json()) == 5

    page = client.get("/jobs?limit=2").json()
    assert len(page) == 2
    rest = client.get("/jobs?limit=2&offset=2").json()
    assert [j["id"] for j in rest] != [j["id"] for j in page]

    assert client.get("/jobs?limit=0").status_code == 422
    assert client.get("/jobs?limit=5000").status_code == 422


def test_list_still_reports_status_filter_and_credential_label(client, monkeypatch):
    jid = _create(client, monkeypatch).json()["id"]
    client.post(f"/jobs/{jid}/cancel")

    assert client.get("/jobs?status=canceled").json()[0]["id"] == jid
    assert client.get("/jobs?status=running").json() == []
