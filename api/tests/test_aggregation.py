"""Parse & aggregate validation at job/schedule creation time."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("job_refs")

PATTERN = r"ClassName\s+(?<api>\w+)\s+SPAccountId\s+(?<spid>\d+)\s+in\s+BU\s+(?<BU>.*?)\s+API"


def _job(**agg_over):
    body = {
        "credential_id": 1,
        "index_target_id": 1,
        "region_code": "ap-southeast-1",
        "start_epoch": 0,
        "end_epoch": 7200,
        "phrases": ["ClassName"],
        "label": "TEST_SEARCH",
    }
    agg = {
        "enabled": True,
        "regex": PATTERN,
        "group_by": ["api", "BU"],
        "unique_fields": ["spid"],
    }
    agg.update(agg_over)
    body["aggregation"] = agg
    return body


def test_valid_aggregation_accepted_and_stored(client, monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post("/jobs", json=_job())
    assert resp.status_code == 201
    assert resp.json()["filter_spec"]["aggregation"]["unique_fields"] == ["spid"]


def test_python_style_named_groups_also_accepted(client, monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    # PATTERN above is .NET/Last9-style (?<name>...); Python's own (?P<name>...)
    # form must keep working too.
    python_pattern = PATTERN.replace("(?<", "(?P<")
    resp = client.post("/jobs", json=_job(regex=python_pattern))
    assert resp.status_code == 201


def test_parse_only_without_unique_fields_accepted(client, monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post("/jobs", json=_job(aggregate=False, group_by=[], unique_fields=[]))
    assert resp.status_code == 201, resp.text
    stored = resp.json()["filter_spec"]["aggregation"]
    assert stored["aggregate"] is False
    assert stored["unique_fields"] == []


def test_aggregate_still_requires_a_unique_field(client, monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post("/jobs", json=_job(aggregate=True, unique_fields=[]))
    assert resp.status_code == 422
    assert "at least one field" in resp.json()["detail"]


def test_invalid_regex_rejected(client, monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post("/jobs", json=_job(regex="(unclosed"))
    assert resp.status_code == 422


def test_unknown_field_rejected(client, monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post("/jobs", json=_job(unique_fields=["not_a_group"]))
    assert resp.status_code == 422


def test_multiple_unique_fields_accepted(client, monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    # Counted fields must sit outside group_by: "unique BUs and unique SPIDs per
    # api" is meaningful, whereas counting BU while also grouping by it is not.
    resp = client.post("/jobs", json=_job(group_by=["api"], unique_fields=["spid", "BU"]))
    assert resp.status_code == 201
    assert resp.json()["filter_spec"]["aggregation"]["unique_fields"] == ["spid", "BU"]


def test_disabled_aggregation_skips_validation(client, monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post("/jobs", json=_job(enabled=False, regex="(unclosed"))
    assert resp.status_code == 201


def test_field_in_both_group_by_and_unique_fields_is_rejected(client, monkeypatch):
    """Grouping by the counted field makes every count exactly 1. Job 9 shipped
    with group_by=[api,BU,spid] + unique_fields=[spid] and produced one row per
    SPID with unique_spid=1 throughout — plausible-looking and useless."""
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post("/jobs", json=_job(group_by=["api", "BU", "spid"], unique_fields=["spid"]))
    assert resp.status_code == 422
    assert "every count would be 1" in resp.json()["detail"]


def test_the_corrected_shape_is_accepted(client, monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post("/jobs", json=_job(group_by=["api", "BU"], unique_fields=["spid"]))
    assert resp.status_code == 201


def test_a_catastrophically_backtracking_pattern_is_rejected(client, monkeypatch):
    """A nested quantifier can hang one worker slot for good.

    The pattern runs against every row, `re` has no timeout, and nothing sets a
    Celery time limit — so `(\d+)+$` against a long non-matching line spins that
    slot until the container is restarted. Cancel does not help: the check only
    happens between chunks, and the row never finishes.
    """
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post("/jobs", json=_job(regex=r"SPAccountId\s+(?<spid>(\d+)+)\s+end"))
    assert resp.status_code == 422
    assert "backtrack" in resp.json()["detail"].lower()


def test_an_absurdly_long_pattern_is_rejected(client, monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post("/jobs", json=_job(regex="(?<spid>a)" + "b" * 5000))
    assert resp.status_code == 422


def test_the_real_production_patterns_still_pass(client, monkeypatch):
    """The guard must not reject the lazy quantifiers these patterns rely on."""
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    resp = client.post("/jobs", json=_job(regex=PATTERN))
    assert resp.status_code == 201, "rejected the AHA pattern"

    for pattern in (
        r"(?<api_name>getActiveSubscriptionsPostAction) sessionToken taken from jwt:"
        r"\s*\S+\s+and\s+cpCustomerID:\s*(?<spid>\S+)",
        r"(?<api_name>refreshTokenPostAction).*?<channelPartnerID>(?<spid>[^<]*)"
        r"</channelPartnerID>",
    ):
        # These AstroSooka patterns define no BU/api group — they aggregate flat.
        resp = client.post("/jobs", json=_job(regex=pattern, group_by=[]))
        assert resp.status_code == 201, f"rejected a real pattern: {pattern}"
