"""Index targets CRUD + regions + region-dependent listing."""

from __future__ import annotations


def _create(client, name="UMServices", region="ap-southeast-1", **over):
    body = {"name": name, "region_code": region}
    body.update(over)
    return client.post("/indexes", json=body)


def test_regions_lists_four(client):
    regions = client.get("/regions").json()
    assert {r["code"] for r in regions} == {
        "ap-south-1",
        "us-east-1",
        "ap-southeast-1",
        "eu-central-1",
    }


def test_create_derives_full_index_string(client):
    resp = _create(client)
    assert resp.status_code == 201
    assert resp.json()["full_index_string"] == "physical_index:UMServices"


def test_unknown_region_rejected(client):
    assert _create(client, region="mars-1").status_code == 422


def test_duplicate_in_region_conflicts(client):
    assert _create(client).status_code == 201
    assert _create(client).status_code == 409
    # Same name, different region is allowed.
    assert _create(client, region="us-east-1").status_code == 201


def test_list_filtered_by_region(client):
    _create(client, name="A", region="ap-southeast-1")
    _create(client, name="B", region="us-east-1")
    sg = client.get("/indexes", params={"region": "ap-southeast-1"}).json()
    assert [i["name"] for i in sg] == ["A"]
    assert len(client.get("/indexes").json()) == 2


def test_renaming_the_label_does_not_repoint_the_index(client):
    """The label is free text a person picks from; the physical index is what
    Last9 is actually queried with. Re-deriving one from the other would make
    renaming "UMServices" to "UMS_india" query an index that doesn't exist."""
    iid = _create(client).json()["id"]
    resp = client.put(f"/indexes/{iid}", json={"name": "UMS_india"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "UMS_india"
    assert resp.json()["full_index_string"] == "physical_index:UMServices"


def test_changing_the_physical_index_does_repoint_it(client):
    iid = _create(client).json()["id"]
    resp = client.put(f"/indexes/{iid}", json={"physical_index": "OtherService"})
    assert resp.json()["full_index_string"] == "physical_index:OtherService"


def test_a_source_carries_its_credential(client, monkeypatch):
    """The point of a profile: one pick supplies region, index and credential."""
    from app.models import Last9Credential

    session = client.session_factory()
    session.add(
        Last9Credential(
            id=7,
            label="india",
            org_slug="evergent",
            encrypted_refresh_token="x",
            refresh_token_last4="wxyz",
        )
    )
    session.commit()
    session.close()

    iid = _create(client).json()["id"]
    assert client.put(f"/indexes/{iid}", json={"credential_id": 7}).json()["credential_id"] == 7
    listed = client.get("/indexes").json()[0]
    assert listed["credential_label"] == "india"


def test_an_unknown_credential_is_rejected(client):
    iid = _create(client).json()["id"]
    assert client.put(f"/indexes/{iid}", json={"credential_id": 999}).status_code == 422


def test_a_source_without_a_credential_is_still_valid(client):
    """Targets predating profiles keep working — the job form asks for one."""
    body = client.get("/indexes").json()
    _create(client)
    listed = client.get("/indexes").json()[len(body)]
    assert listed["credential_id"] is None
    assert listed["credential_label"] is None


def test_delete(client):
    iid = _create(client).json()["id"]
    assert client.delete(f"/indexes/{iid}").status_code == 204
    assert client.delete(f"/indexes/{iid}").status_code == 404
