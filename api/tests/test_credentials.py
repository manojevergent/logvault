"""Credentials CRUD + test-connection (Last9 call monkeypatched)."""

from __future__ import annotations

import app.routers.credentials as creds_router


def _create(client, **over):
    body = {
        "label": "Prod",
        "org_slug": "evergentapse1",
        "refresh_token": "rt-secret-WXYZ",
    }
    body.update(over)
    return client.post("/credentials", json=body)


def test_create_masks_token_and_never_leaks_it(client):
    resp = _create(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["refresh_token_preview"] == "••••WXYZ"
    assert data["token_status"] == "unknown"
    # No plaintext / encrypted token fields in the response.
    assert "refresh_token" not in data
    assert "encrypted_refresh_token" not in data


def test_list_and_delete(client):
    cid = _create(client).json()["id"]
    assert len(client.get("/credentials").json()) == 1

    assert client.delete(f"/credentials/{cid}").status_code == 204
    assert client.get("/credentials").json() == []
    assert client.delete(f"/credentials/{cid}").status_code == 404


def test_test_connection_success_caches_status(client, monkeypatch):
    cid = _create(client).json()["id"]
    monkeypatch.setattr(
        creds_router,
        "refresh_access_token",
        lambda _rt, **_kw: {
            "access_token": "AT",
            "refresh_token": None,
            "expires_at": 9_999_999_999,
        },
    )
    resp = client.post(f"/credentials/{cid}/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # Status now reflects the cached expiry.
    assert client.get("/credentials").json()[0]["token_status"] == "valid"


def test_test_connection_failure_returns_ok_false(client, monkeypatch):
    cid = _create(client).json()["id"]

    def boom(_rt, **_kw):
        raise ValueError("Last9 returned HTTP 401")

    monkeypatch.setattr(creds_router, "refresh_access_token", boom)
    resp = client.post(f"/credentials/{cid}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "401" in body["message"]


def test_members_cannot_create_or_delete_credentials(member_client):
    """Last9 credentials are shared infrastructure, not per-user objects.

    Any authenticated member could delete any credential — which silently breaks
    every schedule and job bound to it.
    """
    created = member_client.post(
        "/credentials", json={"label": "X", "org_slug": "o", "refresh_token": "rt-1234"}
    )
    assert created.status_code == 403
    assert member_client.delete("/credentials/1").status_code == 403
