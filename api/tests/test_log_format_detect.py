"""Auto-detect: match pasted lines against saved patterns and propose fields."""

from __future__ import annotations

import pytest

from app.models import Job

pytestmark = pytest.mark.usefixtures("job_refs")

LINE = (
    "AHA-1-6a907c43-522740b7206c8b03224bd10d - ClassName  CGetEntitlementsCommand "
    "SPAccountId  220815144118207 in BU  AHA INDIA API User ahaapiuser"
)
REGEX = (
    r"^(?P<trackerid>AHA-\d-[a-f0-9-]+)\s+-\s+ClassName\s+(?P<api>\w+)\s+SPAccountId\s+"
    r"(?P<spid>\S+)\s+in\s+BU\s+(?P<bu>.*?)\s+API User"
)


def _format(client, name: str, regex: str = REGEX, hint: str = "", sample_line: str = LINE) -> int:
    response = client.post(
        "/log-formats",
        json={"name": name, "regex": regex, "hint": hint, "sample_line": sample_line},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_detect_matches_a_saved_library_format(client):
    _format(client, "Entitlements")
    response = client.post("/log-formats/detect", json={"lines": [LINE, LINE]})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["lines_analyzed"] == 2
    assert body["matched"] == 2
    assert body["unmatched"] == 0
    candidate = body["candidates"][0]
    assert candidate["source"] == "library"
    assert candidate["name"] == "Entitlements"
    assert candidate["matched"] == 2

    names = [f["name"] for f in candidate["fields"]]
    assert set(names) == {"trackerid", "api", "spid", "bu"}
    spid = next(f for f in candidate["fields"] if f["name"] == "spid")
    assert spid["coverage"] == 2
    assert spid["distinct"] == 1
    assert spid["sample"] == "220815144118207"


def test_detect_suggests_group_versus_unique_by_cardinality(client):
    _format(client, "Entitlements")
    lines = [
        LINE.replace("CGetEntitlementsCommand", "CGetA").replace("220815144118207", "111"),
        LINE.replace("CGetEntitlementsCommand", "CGetB").replace("220815144118207", "222"),
        LINE.replace("CGetEntitlementsCommand", "CGetA").replace("220815144118207", "333"),
    ]
    body = client.post("/log-formats/detect", json={"lines": lines}).json()
    candidate = body["candidates"][0]

    # api repeats (A, B, A) -> grouping key; spid is unique per line -> counted.
    assert "api" in candidate["suggested_group_by"]
    assert "spid" in candidate["suggested_unique"]


def test_detect_uses_field_names_when_only_one_line_is_pasted(client):
    """One line has no cardinality, so an *id field is counted and a word grouped."""
    _format(client, "Entitlements")
    body = client.post("/log-formats/detect", json={"lines": [LINE]}).json()
    candidate = body["candidates"][0]

    assert "api" in candidate["suggested_group_by"]
    assert "bu" in candidate["suggested_group_by"]
    assert "spid" in candidate["suggested_unique"]
    assert "trackerid" in candidate["suggested_unique"]


def test_detect_never_puts_a_field_in_both_boxes(client):
    """All-word single line: one field is promoted to a count so the pair is valid."""
    regex = r"^paid=(?P<paid>\w+) valid=(?P<valid>\w+) api=(?P<api>\w+)$"
    line = "paid=true valid=yes api=CGetAccount"
    _format(client, "Flags", regex=regex, sample_line=line)
    candidate = client.post("/log-formats/detect", json={"lines": [line]}).json()["candidates"][0]

    assert set(candidate["suggested_group_by"]) & set(candidate["suggested_unique"]) == set()
    assert candidate["suggested_unique"]
    assert set(candidate["suggested_group_by"]) | set(candidate["suggested_unique"]) == {
        "paid",
        "valid",
        "api",
    }


def test_detect_falls_back_to_a_saved_search_pattern(client):
    """A pattern saved inside a search is reusable even if it is not in the library."""
    response = client.post(
        "/templates",
        json={
            "name": "Entitlements search",
            "phrases": ["ClassName"],
            "customer": "AHA",
            "aggregation": {
                "enabled": True,
                "regex": REGEX,
                "group_by": ["api"],
                "unique_fields": ["spid"],
            },
            "credential_id": 1,
            "index_target_id": 1,
            "region_code": "ap-southeast-1",
        },
    )
    assert response.status_code == 201, response.text

    body = client.post("/log-formats/detect", json={"lines": [LINE]}).json()
    assert body["matched"] == 1
    candidate = body["candidates"][0]
    assert candidate["source"] == "saved_search"
    assert candidate["name"] == "Entitlements search"


def test_identifier_heuristic_ignores_plain_words():
    from app.routers.log_formats import _looks_like_identifier

    assert not _looks_like_identifier("paid", "true")
    assert not _looks_like_identifier("valid", "yes")
    assert not _looks_like_identifier("api", "CGetAccountContactsCommand")
    assert _looks_like_identifier("spid", "220815144118207")
    assert _looks_like_identifier("trackerid", "Pinnacle-1-6af334a3")
    assert _looks_like_identifier("SPAccountId", "abc")
    assert _looks_like_identifier("request", "r-1")


def test_detect_reports_json_keys_when_no_pattern_matches(client):
    line = '{"level":"INFO","service":"checkout","latency_ms":42}'
    body = client.post("/log-formats/detect", json={"lines": [line]}).json()
    assert body["matched"] == 0
    assert body["unmatched"] == 1
    assert body["candidates"] == []
    assert body["inferred"] is None
    names = [f["name"] for f in body["json_fields"]]
    assert names == ["latency_ms", "level", "service"] or set(names) == {
        "level",
        "service",
        "latency_ms",
    }
    assert "JSON" in body["message"]


def test_detect_explains_when_nothing_can_be_inferred(client):
    body = client.post(
        "/log-formats/detect", json={"lines": ["completely unstructured text"]}
    ).json()
    assert body["matched"] == 0
    assert body["candidates"] == []
    assert body["inferred"] is None
    assert "Paste 2-3 lines" in body["message"]


LOGFMT = "ts=2024-05-01T10:00:00Z level=info service=checkout order_id=8812"


def test_detect_infers_a_pattern_for_unsaved_key_value_lines(client):
    """One logfmt line is enough: its labels anchor the pattern."""
    body = client.post("/log-formats/detect", json={"lines": [LOGFMT]}).json()
    inferred = body["inferred"]

    assert inferred is not None
    assert inferred["regex"].startswith("ts=(?<ts>")
    assert [f["name"] for f in inferred["fields"]] == ["ts", "level", "service", "order_id"]
    assert "level" in inferred["suggested_group_by"]
    assert "order_id" in inferred["suggested_unique"]


def test_detect_infers_from_position_for_unsaved_text_shapes(client):
    lines = [
        "2024-05-01T10:00:00Z INFO checkout status=200",
        "2024-05-01T10:00:01Z INFO payments status=500",
        "2024-05-01T10:00:02Z INFO checkout status=200",
    ]
    body = client.post("/log-formats/detect", json={"lines": lines}).json()
    inferred = body["inferred"]

    assert inferred is not None
    assert "INFO" in inferred["regex"]
    assert "(?<status>" in inferred["regex"]
    assert inferred["lines_used"] == 3
    # Positional order, not alphabetical: field1 reads better than field10.
    assert [f["name"] for f in inferred["fields"]][0] == "field1"
    assert "status" in inferred["suggested_group_by"]


def test_detect_infers_nothing_when_lines_share_no_structure(client):
    lines = ["level=info msg=ok", "service=checkout latency=42"]
    body = client.post("/log-formats/detect", json={"lines": lines}).json()
    assert body["inferred"] is None
    assert "share no stable text" in body["message"]


def test_detect_infers_nothing_from_mismatched_token_counts(client):
    lines = ["2024-05-01 INFO checkout", "2024-05-01 INFO checkout status=200"]
    body = client.post("/log-formats/detect", json={"lines": lines}).json()
    assert body["inferred"] is None
    assert "same number of fields" in body["message"]


def test_inferred_pattern_can_be_saved_and_is_then_reused(client):
    body = client.post("/log-formats/detect", json={"lines": [LOGFMT]}).json()
    inferred = body["inferred"]

    created = client.post(
        "/log-formats",
        json={"name": "Checkout logfmt", "regex": inferred["regex"], "sample_line": LOGFMT},
    )
    assert created.status_code == 201, created.text

    again = client.post("/log-formats/detect", json={"lines": [LOGFMT]}).json()
    assert again["inferred"] is None
    assert again["candidates"][0]["source"] == "library"
    assert again["candidates"][0]["name"] == "Checkout logfmt"


def test_detect_deduplicates_the_same_pattern_saved_twice(client):
    _format(client, "First copy")
    _format(client, "Second copy")
    body = client.post("/log-formats/detect", json={"lines": [LINE]}).json()
    assert len(body["candidates"]) == 1


def test_detect_requires_at_least_one_line(client):
    body = client.post("/log-formats/detect", json={"lines": ["  ", ""]}).json()
    assert body["lines_analyzed"] == 0
    assert "Paste at least one log line" in body["message"]


# --- learning from a real job ------------------------------------------------

KV_LINES = [
    "ts=2026-01-01T00:00:00Z level=INFO user=alice action=login",
    "ts=2026-01-01T00:01:00Z level=INFO user=bob action=logout",
]


def _job_with_unmatched(client, lines, label="Checkout", customer="ACME"):
    with client.session_factory() as db:
        job = Job(
            status="completed",
            region_code="ap-southeast-1",
            index_target_id=1,
            credential_id=1,
            start_epoch=0,
            end_epoch=3600,
            filter_spec={"label": label, "customer": customer},
            rows_written=0,
            aggregation_result={
                "rows_unmatched": len(lines),
                "unmatched_samples": [
                    {"timestamp": "2026-01-01T00:00:00Z", "message": line} for line in lines
                ],
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job.id


def test_detect_job_uses_stored_unmatched_samples(client):
    job_id = _job_with_unmatched(client, KV_LINES)
    response = client.post(f"/log-formats/jobs/{job_id}/detect")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["job_id"] == job_id
    assert body["job_label"] == "Checkout"
    assert body["customer"] == "ACME"
    assert body["lines_analyzed"] == 2
    assert body["unmatched_total"] == 2
    assert body["source"] == "stored unmatched samples"
    assert body["inferred"] is not None
    assert "user=" in body["inferred"]["regex"]
    assert {f["name"] for f in body["inferred"]["fields"]} == {
        "ts",
        "level",
        "user",
        "action",
    }


def test_learn_saves_an_enabled_format_and_dedupes(client):
    job_id = _job_with_unmatched(client, KV_LINES)

    response = client.post(
        f"/log-formats/jobs/{job_id}/learn",
        json={"name": "Checkout KV"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True
    fmt = body["format"]
    assert fmt["name"] == "Checkout KV"
    assert fmt["priority"] == 500
    assert fmt["enabled"] is True
    assert "job #" in (fmt["description"] or "")
    assert "Checkout" in (fmt["description"] or "")

    formats = client.get("/log-formats").json()
    assert [f["id"] for f in formats if f["name"] == "Checkout KV"] == [fmt["id"]]

    # Same regex, different requested name: not a second format.
    again = client.post(
        f"/log-formats/jobs/{job_id}/learn",
        json={"name": "Checkout KV copy", "regex": fmt["regex"]},
    )
    assert again.status_code == 201, again.text
    assert again.json()["created"] is False
    assert again.json()["format"]["id"] == fmt["id"]
    assert len(client.get("/log-formats").json()) == 1


def test_job_without_unmatched_lines_cannot_learn(client):
    with client.session_factory() as db:
        job = Job(
            status="completed",
            region_code="ap-southeast-1",
            index_target_id=1,
            credential_id=1,
            start_epoch=0,
            end_epoch=3600,
            filter_spec={"label": "Clean", "customer": "ACME"},
            rows_written=5,
            aggregation_result={"rows_unmatched": 0, "unmatched_samples": []},
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    detected = client.post(f"/log-formats/jobs/{job_id}/detect")
    assert detected.status_code == 200
    assert detected.json()["lines_analyzed"] == 0
    assert "no unmatched lines" in (detected.json()["message"] or "")

    learned = client.post(f"/log-formats/jobs/{job_id}/learn", json={})
    assert learned.status_code == 422
