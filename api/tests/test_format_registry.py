"""Auto-registration of manually entered parse patterns in the Log Formats library."""

from __future__ import annotations

import pytest

from app.config import get_settings

pytestmark = pytest.mark.usefixtures("auto_register")

PATTERN = r"ClassName\s+(?<api>\w+)\s+SPAccountId\s+(?<spid>\d+)"


@pytest.fixture
def auto_register(monkeypatch):
    # The shared test settings disable it (conftest); this file is about it.
    monkeypatch.setattr(get_settings(), "auto_register_formats", True)


def _template(name: str, **agg_over):
    agg = {
        "enabled": True,
        "regex": PATTERN,
        "group_by": ["api"],
        "unique_fields": ["spid"],
    }
    agg.update(agg_over)
    return {
        "name": name,
        "phrases": ["ClassName"],
        "customer": "TEST_CUSTOMER",
        "aggregation": agg,
    }


def _formats(client):
    return client.get("/log-formats").json()


def test_saved_search_registers_its_pattern(client):
    resp = client.post("/templates", json=_template("Entitlements search"))
    assert resp.status_code == 201, resp.text

    fmt = next(f for f in _formats(client) if f["name"] == "Entitlements search")
    assert fmt["regex"] == PATTERN
    assert fmt["priority"] == 500
    assert fmt["enabled"] is True
    assert "saved search" in fmt["description"]
    assert "Entitlements search" in fmt["description"]


def test_the_same_pattern_in_python_syntax_is_not_added_twice(client):
    assert client.post("/templates", json=_template("First name")).status_code == 201
    python_pattern = PATTERN.replace("(?<", "(?P<")
    assert (
        client.post("/templates", json=_template("Second name", regex=python_pattern)).status_code
        == 201
    )

    names = {f["name"] for f in _formats(client)}
    assert "First name" in names
    assert "Second name" not in names


def test_library_mode_does_not_register_an_empty_regex(client):
    resp = client.post(
        "/templates",
        json=_template("Library search", enabled=True, use_library=True, regex=""),
    )
    assert resp.status_code == 201, resp.text
    assert not any(f["name"] == "Library search" for f in _formats(client))


def test_job_with_a_manual_pattern_registers_it(client, monkeypatch, job_refs):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "dispatch_job", lambda _id: None)
    body = {
        "credential_id": 1,
        "index_target_id": 1,
        "region_code": "ap-southeast-1",
        "start_epoch": 0,
        "end_epoch": 7200,
        "phrases": ["ClassName"],
        "label": "Job pattern",
        "aggregation": {
            "enabled": True,
            "regex": PATTERN,
            "group_by": ["api"],
            "unique_fields": ["spid"],
        },
    }
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 201, resp.text
    fmt = next(f for f in _formats(client) if f["name"] == "Job pattern")
    assert "job" in fmt["description"]


def test_name_collision_gets_a_pattern_suffix(client):
    created = client.post(
        "/log-formats",
        json={
            "name": "Collision",
            "regex": r"^COLLIDE\s+(?<value>\S+)$",
            "sample_line": "COLLIDE abc",
        },
    )
    assert created.status_code == 201, created.text

    assert client.post("/templates", json=_template("Collision")).status_code == 201
    names = {f["name"] for f in _formats(client)}
    assert any(name.startswith("Collision (auto ") for name in names)


def test_auto_registration_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "auto_register_formats", False)
    assert client.post("/templates", json=_template("Disabled search")).status_code == 201
    assert not any(f["name"] == "Disabled search" for f in _formats(client))
