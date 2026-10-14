"""Audit recording on mutations + settings readout."""

from __future__ import annotations


def test_mutations_are_audited(client):
    client.post(
        "/credentials",
        json={"label": "X", "org_slug": "o", "refresh_token": "rt-1234"},
    )
    audit = client.get("/audit").json()
    assert any(a["action"] == "create" and a["entity"] == "credential" for a in audit)


def test_settings_readout(client):
    s = client.get("/settings").json()
    assert s["region_count"] == 4
    assert s["default_org_slug"]
    assert "storage_dir" in s


def test_audit_and_settings_are_admin_only(member_client):
    """A member must not read the audit trail or the settings readout.

    Both endpoints shipped without `require_admin` while the two notification
    endpoints beside them had it, so every member could read the full audit
    trail — including which credentials exist and who touched them.
    """
    assert member_client.get("/audit").status_code == 403
    assert member_client.get("/settings").status_code == 403


def test_audit_rows_record_who_did_it(client):
    """An audit trail that never names an actor is not an audit trail.

    Every caller omitted the optional user_id, so `user_id` was NULL on every
    row. It is now taken from the authenticated request instead.
    """
    client.post("/credentials", json={"label": "Who", "org_slug": "o", "refresh_token": "rt-9999"})
    rows = client.get("/audit").json()
    created = [a for a in rows if a["entity"] == "credential" and a["action"] == "create"]
    assert created, "expected the credential creation to be audited"
    assert created[0]["user_id"] == "test@example.com"
