"""Filter templates ("save the search") CRUD."""

from __future__ import annotations


def _create(client, name="Entitlements SPID", **over):
    body = {"name": name, "phrases": ["ClassName", "SPAccountId"], "ids": [], "message_types": []}
    body.update(over)
    return client.post("/templates", json=body)


def test_create_and_list(client):
    resp = _create(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Entitlements SPID"
    assert data["phrases"] == ["ClassName", "SPAccountId"]

    listed = client.get("/templates").json()
    assert [t["name"] for t in listed] == ["Entitlements SPID"]


def test_requires_at_least_one_filter_value(client):
    resp = _create(client, phrases=[], ids=[], message_types=[])
    assert resp.status_code == 422


def test_duplicate_name_conflicts(client):
    assert _create(client).status_code == 201
    assert _create(client).status_code == 409


def test_delete(client):
    tid = _create(client).json()["id"]
    assert client.delete(f"/templates/{tid}").status_code == 204
    assert client.delete(f"/templates/{tid}").status_code == 404
    assert client.get("/templates").json() == []


# ── saving the parse pattern with the search ─────────────────────────────────

_RX = r"SPAccountId\s+(?<spid>\S+)\s+in\s+BU\s+(?<BU>.*?)\s+API"
_AGG = {"enabled": True, "regex": _RX, "group_by": ["BU"], "unique_fields": ["spid"]}


def test_template_round_trips_its_parse_config(client):
    """The regex is the laborious part of a search — it has to come back."""
    resp = client.post(
        "/templates",
        json={"name": "AHA_CGetEntitlements", "phrases": ["ClassName"], "aggregation": _AGG},
    )
    assert resp.status_code == 201

    saved = client.get("/templates").json()[0]["aggregation"]
    assert saved["regex"] == _RX
    assert saved["group_by"] == ["BU"]
    assert saved["unique_fields"] == ["spid"]


def test_a_parse_pattern_alone_is_enough_to_save(client):
    # Independent of any filter, and the part worth keeping.
    resp = client.post("/templates", json={"name": "parse only", "aggregation": _AGG})
    assert resp.status_code == 201


def test_a_template_with_neither_filter_nor_pattern_is_still_rejected(client):
    resp = client.post("/templates", json={"name": "empty"})
    assert resp.status_code == 422


def test_a_broken_pattern_is_rejected_on_save(client):
    """Caught here rather than resurfacing on every job loaded from it."""
    resp = client.post(
        "/templates",
        json={"name": "bad", "aggregation": {**_AGG, "regex": "(unclosed"}},
    )
    assert resp.status_code == 422
    assert "invalid regex" in resp.json()["detail"]


def test_a_pattern_grouping_by_the_counted_field_is_rejected_on_save(client):
    resp = client.post(
        "/templates",
        json={"name": "bad", "aggregation": {**_AGG, "group_by": ["BU", "spid"]}},
    )
    assert resp.status_code == 422
    assert "every count would be 1" in resp.json()["detail"]


def test_a_template_without_a_pattern_reports_none(client):
    client.post("/templates", json={"name": "filters only", "phrases": ["ClassName"]})
    assert client.get("/templates").json()[0]["aggregation"] is None


def test_a_disabled_pattern_is_not_stored(client):
    client.post(
        "/templates",
        json={"name": "off", "phrases": ["ClassName"], "aggregation": {**_AGG, "enabled": False}},
    )
    assert client.get("/templates").json()[0]["aggregation"] is None


# ── editing a saved search ────────────────────────────────────────────────────


def test_update_changes_filters_and_customer(client):
    tid = _create(client).json()["id"]
    resp = client.put(
        f"/templates/{tid}",
        json={
            "name": "Entitlements SPID",
            "phrases": ["ClassName", "NewPhrase"],
            "ids": ["ID-1"],
            "message_types": [],
            "customer": "acme",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["phrases"] == ["ClassName", "NewPhrase"]
    assert data["ids"] == ["ID-1"]
    assert data["customer"] == "acme"


def test_update_can_rename(client):
    tid = _create(client).json()["id"]
    resp = client.put(
        f"/templates/{tid}",
        json={"name": "renamed", "phrases": ["ClassName"], "ids": [], "message_types": []},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"
    assert [t["name"] for t in client.get("/templates").json()] == ["renamed"]


def test_update_404_on_missing_template(client):
    resp = client.put(
        "/templates/9999",
        json={"name": "x", "phrases": ["a"], "ids": [], "message_types": []},
    )
    assert resp.status_code == 404


def test_update_rejects_a_rename_that_collides(client):
    tid = _create(client, name="first").json()["id"]
    _create(client, name="second")
    resp = client.put(
        f"/templates/{tid}",
        json={"name": "second", "phrases": ["ClassName"], "ids": [], "message_types": []},
    )
    assert resp.status_code == 409


def test_update_can_change_the_parse_pattern(client):
    tid = client.post(
        "/templates", json={"name": "AHA_CGetEntitlements", "aggregation": _AGG}
    ).json()["id"]
    new_rx = r"SPAccountId\s+(?<spid>\S+)\s+in\s+BU\s+(?<BU>.*?)\s+API\s+v2"
    resp = client.put(
        f"/templates/{tid}",
        json={"name": "AHA_CGetEntitlements", "aggregation": {**_AGG, "regex": new_rx}},
    )
    assert resp.status_code == 200
    assert resp.json()["aggregation"]["regex"] == new_rx


def test_update_rejects_a_broken_pattern(client):
    tid = client.post(
        "/templates", json={"name": "AHA_CGetEntitlements", "aggregation": _AGG}
    ).json()["id"]
    resp = client.put(
        f"/templates/{tid}",
        json={"name": "AHA_CGetEntitlements", "aggregation": {**_AGG, "regex": "(unclosed"}},
    )
    assert resp.status_code == 422
    # Rejected, so the previously valid pattern is still what's stored.
    assert client.get("/templates").json()[0]["aggregation"]["regex"] == _RX


def test_update_can_turn_off_the_parse_pattern(client):
    tid = client.post(
        "/templates",
        json={"name": "both", "phrases": ["ClassName"], "aggregation": _AGG},
    ).json()["id"]
    resp = client.put(
        f"/templates/{tid}",
        json={"name": "both", "phrases": ["ClassName"], "aggregation": {**_AGG, "enabled": False}},
    )
    assert resp.status_code == 200
    assert resp.json()["aggregation"] is None


def test_update_preserves_hidden_aggregation_fields_the_edit_form_cannot_see(client):
    """raw_column_defaults, timestamp_column and column_labels have no editing
    control anywhere in the UI — set only via a direct API call or the
    job-export JSON. An edit submitted through the Saved Searches form always
    sends them at their schema default, and that must not erase a value the
    form never showed in the first place."""
    tid = client.post(
        "/templates",
        json={
            "name": "with hidden fields",
            "aggregation": {
                **_AGG,
                "raw_column_defaults": {"BU": "unknown"},
                "timestamp_column": "ts",
                "column_labels": {"spid": "spAccountID"},
            },
        },
    ).json()["id"]

    resp = client.put(
        f"/templates/{tid}",
        json={"name": "with hidden fields", "aggregation": _AGG},  # all at default
    )
    assert resp.status_code == 200
    saved = resp.json()["aggregation"]
    assert saved["raw_column_defaults"] == {"BU": "unknown"}
    assert saved["timestamp_column"] == "ts"
    assert saved["column_labels"] == {"spid": "spAccountID"}


def test_update_applies_uniform_column_layout(client):
    """The uniform-extract story end to end: sequence in raw_columns, uniform
    headers in column_labels, timestamp renamed — and the worker honors it."""
    rx = r"ClassName\s+(?<api>\w+)\s+SPAccountId\s+(?<spid>\S+)\s+in\s+BU\s+(?<BU>.*?)\s+API"
    agg = {
        **_AGG,
        "regex": rx,
        "group_by": ["api", "BU"],
        "raw_columns": ["spid", "api", "BU"],
        "column_labels": {"spid": "spAccountID", "BU": "bu_name"},
        "timestamp_column": "timestamp",
        "include_log_format": False,
        "include_message": False,
    }
    resp = client.post("/templates", json={"name": "uniform", "aggregation": agg})
    assert resp.status_code == 201
    saved = resp.json()["aggregation"]
    assert saved["raw_columns"] == ["spid", "api", "BU"]
    assert saved["column_labels"] == {"spid": "spAccountID", "BU": "bu_name"}
    assert saved["timestamp_column"] == "timestamp"
    assert saved["include_message"] is False


def test_update_does_not_preserve_raw_columns_or_include_message(client):
    """Unlike raw_column_defaults/timestamp_column, these two have real
    checkboxes in both editing forms now — a submission at the default
    genuinely means "use the default", and must not be overridden by
    whatever was saved before. Preserving it anyway is exactly the bug that
    would make unchecking a box do nothing the moment the result happened to
    land back on the implicit default set."""
    tid = client.post(
        "/templates",
        json={
            "name": "with real controls",
            "aggregation": {**_AGG, "raw_columns": ["BU"], "include_message": False},
        },
    ).json()["id"]

    resp = client.put(
        f"/templates/{tid}",
        json={"name": "with real controls", "aggregation": _AGG},  # both back at default
    )
    assert resp.status_code == 200
    saved = resp.json()["aggregation"]
    assert saved["raw_columns"] == []
    assert saved["include_message"] is True


def test_template_round_trips_its_remembered_source(client):
    """The source a search was built for comes back with it, so batch runs
    and the wizard pre-fill instead of asking every time."""
    from app.models import IndexTarget, Last9Credential

    db = client.session_factory()
    db.add(
        Last9Credential(
            id=11,
            label="sg",
            org_slug="evergentapse1",
            encrypted_refresh_token="x",
            refresh_token_last4="abcd",
        )
    )
    db.add(
        IndexTarget(
            id=12,
            name="UMServices",
            region_code="ap-southeast-1",
            full_index_string="physical_index:UMServices",
            credential_id=11,
        )
    )
    db.commit()
    db.close()

    resp = client.post(
        "/templates",
        json={
            "name": "SG search",
            "phrases": ["ClassName"],
            "credential_id": 11,
            "region_code": "ap-southeast-1",
            "index_target_id": 12,
        },
    )
    assert resp.status_code == 201
    saved = resp.json()
    assert (saved["credential_id"], saved["region_code"], saved["index_target_id"]) == (
        11,
        "ap-southeast-1",
        12,
    )

    # Unknown ids fail at save, not mid-batch.
    bad = client.post(
        "/templates",
        json={"name": "bad", "phrases": ["x"], "credential_id": 999},
    )
    assert bad.status_code == 422


def test_update_can_still_change_a_hidden_field_via_a_direct_api_call(client):
    """The preservation above only kicks in when the submitted value sits at
    the schema default — a deliberate non-default value still takes effect."""
    tid = client.post("/templates", json={"name": "x", "aggregation": _AGG}).json()["id"]
    resp = client.put(
        f"/templates/{tid}",
        json={"name": "x", "aggregation": {**_AGG, "raw_columns": ["spid"]}},
    )
    assert resp.json()["aggregation"]["raw_columns"] == ["spid"]
