"""New Relic connections, saved comparisons, and the run engine.

Network calls are monkeypatched here; the provider parsers have their own
unit-level coverage in test_comparison_parsing.py.
"""

from __future__ import annotations

import pytest

from app import crypto, newrelic
from app.last9_query import Last9QueryResult


def _nr_credential(client) -> int:
    response = client.post(
        "/newrelic/credentials",
        json={
            "label": "NR prod",
            "account_id": 1234567,
            "region": "us",
            "api_key": "NRAK-test-key-1234",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _comparison(client, nr_id: int, *, name: str = "Checkout count") -> dict:
    response = client.post(
        "/comparisons",
        json={
            "name": name,
            "description": "NR vs Last9",
            "last9_index_target_id": 1,
            "last9_filter_spec": {
                "phrases": ["error"],
                "ids": ["123"],
                "exact_phrases": ["API : 502"],
                "message_types": [],
            },
            "nr_credential_id": nr_id,
            "nrql": "SELECT count(*) FROM Log WHERE service.name = 'checkout'",
            "nr_value_mode": "sum",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_newrelic_credential_is_encrypted_at_rest(client, job_refs):
    nr_id = _nr_credential(client)
    db = client.session_factory()
    from app.models import NewRelicCredential

    cred = db.get(NewRelicCredential, nr_id)
    assert cred is not None
    assert cred.encrypted_api_key != "NRAK-test-key-1234"
    assert crypto.decrypt(cred.encrypted_api_key) == "NRAK-test-key-1234"
    assert cred.api_key_last4 == "1234"
    db.close()

    listed = client.get("/newrelic/credentials").json()
    assert listed[0]["api_key_preview"] == "••••1234"
    assert "api_key" not in listed[0]


def test_newrelic_credential_creation_requires_admin(member_client, job_refs):
    response = member_client.post(
        "/newrelic/credentials",
        json={
            "label": "NR prod",
            "account_id": 1234567,
            "region": "us",
            "api_key": "NRAK-test-key-1234",
        },
    )
    assert response.status_code == 403


def test_newrelic_credential_can_be_updated_without_resending_key(client, job_refs):
    nr_id = _nr_credential(client)
    response = client.put(
        f"/newrelic/credentials/{nr_id}",
        json={"label": "NR renamed", "account_id": 7654321, "region": "eu"},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["label"] == "NR renamed"
    assert updated["account_id"] == 7654321
    assert updated["region"] == "eu"
    assert updated["api_key_preview"] == "••••1234"

    db = client.session_factory()
    from app.models import NewRelicCredential

    cred = db.get(NewRelicCredential, nr_id)
    assert crypto.decrypt(cred.encrypted_api_key) == "NRAK-test-key-1234"
    db.close()

    response = client.put(
        f"/newrelic/credentials/{nr_id}",
        json={"api_key": "NRAK-new-key-9999"},
    )
    assert response.status_code == 200
    assert response.json()["api_key_preview"] == "••••9999"


def test_comparison_builds_pipeline_and_returns_labels(client, job_refs):
    nr_id = _nr_credential(client)
    created = _comparison(client, nr_id)
    assert created["last9_index_name"] == "test-index"
    assert created["last9_credential_label"] == "test"
    assert created["nr_account_id"] == 1234567
    assert created["last9_pipeline"] == [
        {
            "query": {
                "$and": [
                    {"$contains": ["Body", "error"]},
                    {"$regex": ["Body", "API\\s+:\\s+502"]},
                    {"$regex": ["Body", "123"]},
                ]
            },
            "type": "filter",
        }
    ]

    listed = client.get("/comparisons").json()
    assert listed["total"] == 1
    assert listed["items"][0]["name"] == "Checkout count"
    # The list is a summary: it must not carry the potentially huge pipeline.
    assert "last9_pipeline" not in listed["items"][0]
    assert "nrql" not in listed["items"][0]


def test_comparison_list_is_paginated_and_searchable(client, job_refs):
    nr_id = _nr_credential(client)
    _comparison(client, nr_id, name="Checkout count")
    _comparison(client, nr_id, name="Payment errors")

    first = client.get("/comparisons", params={"limit": 1, "offset": 0}).json()
    assert first["total"] == 2
    assert len(first["items"]) == 1
    second = client.get("/comparisons", params={"limit": 1, "offset": 1}).json()
    assert len(second["items"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]

    searched = client.get("/comparisons", params={"q": "payment"}).json()
    assert searched["total"] == 1
    assert searched["items"][0]["name"] == "Payment errors"


def test_comparison_delete_is_blocked_while_connection_is_in_use(client, job_refs):
    nr_id = _nr_credential(client)
    _comparison(client, nr_id)
    response = client.delete(f"/newrelic/credentials/{nr_id}")
    assert response.status_code == 409
    assert "Checkout count" in response.json()["detail"]


def test_comparison_run_produces_side_by_side_result(client, job_refs, monkeypatch):
    nr_id = _nr_credential(client)
    comparison = _comparison(client, nr_id)

    start = 1_700_000_000
    end = start + 3600

    def fake_access_token(db, cred):
        return "test-token"

    def fake_nrql(**kwargs):
        return newrelic.NewRelicQueryResult(
            results=[
                {"beginTime": start * 1000, "endTime": (start + 1800) * 1000, "count": 4},
                {"beginTime": (start + 1800) * 1000, "endTime": end * 1000, "count": 6},
            ],
            metadata={"timeWindow": {"begin": start, "end": end}},
            elapsed_ms=12,
        )

    def fake_last9(**kwargs):
        pipeline = kwargs["pipeline"]
        if any(stage.get("type") == "aggregate" for stage in pipeline):
            return Last9QueryResult(rows=[{"last9_count": 12}], elapsed_ms=8)
        return Last9QueryResult(
            rows=[
                {"timestamp": start * 1_000_000_000, "last9_count": 5},
                {"timestamp": (start + 1800) * 1_000_000_000, "last9_count": 7},
            ],
            elapsed_ms=9,
        )

    monkeypatch.setattr("app.routers.comparisons.access_token", fake_access_token)
    monkeypatch.setattr("app.routers.comparisons.newrelic.execute_nrql", fake_nrql)
    monkeypatch.setattr("app.routers.comparisons.query_last9", fake_last9)

    response = client.post(
        f"/comparisons/{comparison['id']}/run",
        json={"start_epoch": start, "end_epoch": end},
    )
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "ok"
    assert run["last9_total"] == 12
    assert run["newrelic_total"] == 10
    assert run["delta"] == 2
    assert run["pct_diff"] == pytest.approx(20.0)
    assert len(run["last9"]["series"]) == 2
    assert len(run["newrelic"]["series"]) == 2
    assert run["last9"]["series"][0]["start_epoch"] == start
    assert run["newrelic"]["series"][0]["value"] == 4

    history = client.get(f"/comparisons/{comparison['id']}/runs").json()
    assert len(history) == 1
    assert history[0]["status"] == "ok"
    assert history[0]["last9_total"] == 12

    listed = client.get("/comparisons").json()
    assert listed["items"][0]["last_run_status"] == "ok"
    assert listed["items"][0]["last_run_id"] == run["id"]
    assert listed["items"][0]["last_run_last9_total"] == 12
    assert listed["items"][0]["last_run_newrelic_total"] == 10

    stored = client.get(f"/comparisons/{comparison['id']}/runs/{run['id']}").json()
    assert stored["nrql_effective"].endswith("TIMESERIES 60 seconds")
    assert "SINCE 1700000000000" in stored["nrql_effective"]


def test_comparison_run_validates_window(client, job_refs):
    nr_id = _nr_credential(client)
    comparison = _comparison(client, nr_id)
    response = client.post(
        f"/comparisons/{comparison['id']}/run",
        json={"start_epoch": 100, "end_epoch": 100},
    )
    assert response.status_code == 422
