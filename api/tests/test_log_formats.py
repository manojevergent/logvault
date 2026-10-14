"""The log formats library: what may be registered, and why each guard exists."""

from __future__ import annotations

RX = r"SPAccountId\s+(?<cpid>\S+)\s+in\s+BU\s+(?<partner>\S+)"
SAMPLE = "AHA-1-x - ClassName C SPAccountId  1001 in BU  AHA-INDIA API User u"


def _fmt(**over):
    body = {"name": "aha", "regex": RX, "sample_line": SAMPLE, "hint": "SPAccountId"}
    body.update(over)
    return body


def test_a_format_round_trips(client):
    assert client.post("/log-formats", json=_fmt()).status_code == 201
    got = client.get("/log-formats").json()[0]
    assert got["name"] == "aha"
    assert got["hint"] == "SPAccountId"
    assert got["enabled"] is True


def test_formats_are_listed_in_the_order_they_will_be_tried(client):
    client.post("/log-formats", json=_fmt(name="broad", priority=50))
    client.post("/log-formats", json=_fmt(name="narrow", priority=1))
    # First match wins, so the listing has to show the order actually used.
    assert [f["name"] for f in client.get("/log-formats").json()] == ["narrow", "broad"]


def test_a_pattern_with_no_named_groups_is_rejected(client):
    resp = client.post("/log-formats", json=_fmt(regex="SPAccountId"))
    assert resp.status_code == 422
    assert "no named groups" in resp.json()["detail"]


def test_an_invalid_regex_is_rejected(client):
    resp = client.post("/log-formats", json=_fmt(regex="(unclosed"))
    assert resp.status_code == 422
    assert "invalid regex" in resp.json()["detail"]


def test_a_pattern_that_misses_its_own_sample_is_rejected(client):
    # Contains the hint, so the hint guard passes and the pattern is what fails.
    resp = client.post("/log-formats", json=_fmt(sample_line="SPAccountId but nothing else"))
    assert resp.status_code == 422
    assert "does not match the sample line" in resp.json()["detail"]


def test_a_hint_absent_from_the_sample_is_rejected(client):
    """A hint is a pre-filter: if it isn't present the regex never runs, so a
    wrong one makes the format silently unreachable."""
    resp = client.post("/log-formats", json=_fmt(hint="NOT-IN-LINE"))
    assert resp.status_code == 422
    assert "would never be tried" in resp.json()["detail"]


def test_duplicate_names_are_rejected(client):
    client.post("/log-formats", json=_fmt())
    assert client.post("/log-formats", json=_fmt()).status_code == 409


def test_the_test_endpoint_shows_the_fields_a_pattern_extracts(client):
    resp = client.post(
        "/log-formats/test", json={"regex": RX, "sample_line": SAMPLE, "hint": "SPAccountId"}
    )
    body = resp.json()
    assert body["matched"] is True
    assert body["fields"] == {"cpid": "1001", "partner": "AHA-INDIA"}


def test_the_test_endpoint_explains_a_hint_that_would_skip_the_format(client):
    body = client.post(
        "/log-formats/test", json={"regex": RX, "sample_line": SAMPLE, "hint": "NOPE"}
    ).json()
    assert body["matched"] is False
    assert "would be skipped" in body["error"]


def test_the_test_endpoint_reports_a_bad_regex_rather_than_raising(client):
    body = client.post("/log-formats/test", json={"regex": "(bad", "sample_line": "x"}).json()
    assert body["matched"] is False
    assert "invalid regex" in body["error"]


def test_a_format_can_be_disabled_and_deleted(client):
    fid = client.post("/log-formats", json=_fmt()).json()["id"]
    assert client.put(f"/log-formats/{fid}", json=_fmt(enabled=False)).json()["enabled"] is False
    assert client.delete(f"/log-formats/{fid}").status_code == 204
    assert client.get("/log-formats").json() == []
