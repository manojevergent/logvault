"""POST /jobs/batch: several saved searches, one shared window, one job each."""

from __future__ import annotations

import pytest

import app.routers.jobs as jobs_router

pytestmark = pytest.mark.usefixtures("job_refs")


def _template(client, name, **over):
    body = {"name": name, "phrases": ["ClassName"], "ids": ["Ekkl"], "message_types": []}
    body.update(over)
    resp = client.post("/templates", json=body)
    assert resp.status_code == 201
    return resp.json()


def _batch(client, monkeypatch, items, **over):
    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    body = {"items": items, "start_epoch": 0, "end_epoch": 86400}
    body.update(over)
    return client.post("/jobs/batch", json=body)


def _item(tid):
    return {
        "template_id": tid,
        "credential_id": 1,
        "index_target_id": 1,
        "region_code": "ap-southeast-1",
    }


def test_batch_creates_one_job_per_search_over_the_shared_window(client, monkeypatch):
    a = _template(client, "INVOICE_EKKL")
    b = _template(client, "INVOICE_ABSCBN", phrases=["ABSCBNController"], ids=["ABSCBN"])
    resp = _batch(client, monkeypatch, [_item(a["id"]), _item(b["id"])])
    assert resp.status_code == 201
    jobs = resp.json()
    assert len(jobs) == 2
    assert [j["status"] for j in jobs] == ["queued", "queued"]
    assert [j["filter_spec"]["label"] for j in jobs] == ["INVOICE_EKKL", "INVOICE_ABSCBN"]
    assert jobs[0]["filter_spec"]["phrases"] == ["ClassName"]
    assert jobs[0]["filter_spec"]["ids"] == ["Ekkl"]
    assert jobs[1]["filter_spec"]["phrases"] == ["ABSCBNController"]
    for j in jobs:
        assert (j["start_epoch"], j["end_epoch"]) == (0, 86400)
        assert j["credential_label"] == "test"


def test_batch_carries_each_search_parse_config(client, monkeypatch):
    agg = {
        "enabled": True,
        "regex": r"SPAccountId\s+(?<spid>\S+)",
        "group_by": [],
        "unique_fields": ["spid"],
    }
    t = _template(client, "PARSED", aggregation=agg)
    jobs = _batch(client, monkeypatch, [_item(t["id"])]).json()
    assert jobs[0]["filter_spec"]["aggregation"]["unique_fields"] == ["spid"]


def test_batch_falls_back_to_the_search_remembered_source(client, monkeypatch):
    """No per-entry source needed when the search remembers its own — the
    batch dialog pre-fills from exactly these fields."""
    t = _template(client, "REMEMBERED")
    db = client.session_factory()
    from app.models import FilterTemplate

    tpl = db.get(FilterTemplate, t["id"])
    tpl.credential_id = 1
    tpl.region_code = "ap-southeast-1"
    tpl.index_target_id = 1
    db.commit()
    db.close()

    resp = _batch(client, monkeypatch, [{"template_id": t["id"]}])
    assert resp.status_code == 201
    job = resp.json()[0]
    assert (job["credential_id"], job["index_target_id"], job["region_code"]) == (
        1,
        1,
        "ap-southeast-1",
    )


def test_batch_names_searches_without_any_source(client, monkeypatch):
    t = _template(client, "SOURCELESS")
    resp = _batch(client, monkeypatch, [{"template_id": t["id"]}])
    assert resp.status_code == 422
    assert "SOURCELESS" in resp.json()["detail"]
    assert client.get("/jobs?limit=200").json() == []


def test_batch_is_all_or_nothing(client, monkeypatch):
    t = _template(client, "GOOD")
    resp = _batch(
        client,
        monkeypatch,
        [_item(t["id"]), {**_item(9999), "template_id": 9999}],
    )
    assert resp.status_code == 422
    assert client.get("/jobs?limit=200").json() == []


def test_batch_rejects_unknown_credential(client, monkeypatch):
    t = _template(client, "GOOD")
    item = {**_item(t["id"]), "credential_id": 999}
    assert _batch(client, monkeypatch, [item]).status_code == 422
    assert client.get("/jobs?limit=200").json() == []


def test_batch_rejects_empty_oversize_and_inverted_window(client, monkeypatch):
    t = _template(client, "GOOD")
    assert _batch(client, monkeypatch, []).status_code == 422
    big = [_item(t["id"]) for _ in range(51)]
    assert _batch(client, monkeypatch, big).status_code == 422
    assert (
        _batch(client, monkeypatch, [_item(t["id"])], start_epoch=9, end_epoch=9).status_code == 422
    )
