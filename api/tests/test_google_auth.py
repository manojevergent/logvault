"""Google sign-in: providers flag, OAuth round-trip, provisioning, guards."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from jose import jwt

from app.config import get_settings
from app.models import User

CLIENT_ID = "test-google-client-id"


@pytest.fixture
def google_on(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-google-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class FakeGoogle:
    """Stands in for httpx.Client inside the auth router only in these tests.

    The TestClient's own httpx.Client instance is created by the fixture before
    any test patches the class, so in-flight test requests are unaffected.
    """

    token_payload: dict = {"id_token": "test-id-token"}
    token_status: int = 200
    tokeninfo_payload: dict = {}
    tokeninfo_status: int = 200

    def __init__(self, *args, **kwargs):
        pass

    def post(self, url, data=None, **kwargs):
        assert "oauth2.googleapis.com/token" in url
        return _FakeResp(self.token_status, self.token_payload)

    def get(self, url, params=None, **kwargs):
        assert "tokeninfo" in url
        return _FakeResp(self.tokeninfo_status, self.tokeninfo_payload)


class _FakeResp:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=self)  # type: ignore[arg-type]

    def json(self):
        return self._payload


@pytest.fixture
def google_http(monkeypatch):
    FakeGoogle.token_payload = {"id_token": "test-id-token"}
    FakeGoogle.token_status = 200
    FakeGoogle.tokeninfo_payload = {
        "aud": CLIENT_ID,
        "iss": "accounts.google.com",
        "sub": "google-sub-1",
        "email": "ana@evergent.com",
        "email_verified": "true",
        "name": "Ana",
        "hd": "evergent.com",
        "exp": str(int(time.time()) + 3600),
    }
    FakeGoogle.tokeninfo_status = 200
    monkeypatch.setattr(httpx, "Client", FakeGoogle)
    return FakeGoogle


def _start(client):
    """Run the login step; return (state, ) — the cookie jar keeps the cookie."""
    r = client.get("/auth/google/login?next=/jobs", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    q = parse_qs(urlparse(loc).query)
    assert q["client_id"] == [CLIENT_ID]
    assert q["redirect_uri"] == ["http://localhost:8000/auth/google/callback"]
    assert r.cookies.get("lv_oauth_state")
    return q["state"][0]


def _users(client):
    db = client.session_factory()
    try:
        return db.query(User).order_by(User.id).all()
    finally:
        db.close()


def _fragment_params(location: str) -> dict:
    assert location.startswith("http://localhost:3001/auth/callback#")
    return {k: v[0] for k, v in parse_qs(urlparse(location).fragment).items()}


def test_providers_off_by_default(client):
    assert client.get("/auth/providers").json() == {"password": True, "google": False}


def test_providers_on_when_configured(client, google_on):
    assert client.get("/auth/providers").json() == {"password": True, "google": True}


def test_login_redirects_to_google_when_disabled(client):
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code == 302
    assert "error=disabled" in r.headers["location"]


def test_happy_path_creates_user_and_redirects_with_session(client, google_on, google_http):
    # Non-empty table, so the new Google account lands as a member (the
    # empty-table first-user-becomes-admin path has its own test).
    db = client.session_factory()
    db.add(User(email="owner@evergent.com", name="Owner", hashed_password="x", role="admin"))
    db.commit()
    db.close()

    state = _start(client)
    r = client.get(f"/auth/google/callback?code=authcode&state={state}", follow_redirects=False)
    assert r.status_code == 302
    frag = _fragment_params(r.headers["location"])
    assert frag["next"] == "/jobs"
    payload = jwt.decode(frag["access_token"], get_settings().jwt_secret, algorithms=["HS256"])
    assert payload["sub"] == "ana@evergent.com"

    users = _users(client)
    assert len(users) == 2  # seeded owner + the new Google account
    ana = [u for u in users if u.email == "ana@evergent.com"][0]
    assert ana.name == "Ana"
    assert ana.role == "member"
    assert ana.hashed_password is None
    assert ana.auth_provider == "google"
    assert ana.oauth_subject == "google-sub-1"


def test_first_google_user_becomes_admin_when_table_empty(client, google_on, google_http):
    # (table is empty — no users seeded by this fixture)
    r = client.get(
        "/auth/google/callback?code=x&state=" + _fresh_state(client), follow_redirects=False
    )
    frag = _fragment_params(r.headers["location"])
    assert frag["role"] == "admin"
    assert _users(client)[0].role == "admin"


def _fresh_state(client):
    # The login cookie jar persists; starting again mints a fresh state whose
    # cookie overwrites the previous one, matching real browser behavior.
    return _start(client)


def test_repeat_login_reuses_account_and_keeps_role(client, google_on, google_http):
    cb = "/auth/google/callback?code=x&state="
    client.get(cb + _fresh_state(client), follow_redirects=False)
    client.get(cb + _fresh_state(client), follow_redirects=False)
    users = _users(client)
    assert len(users) == 1  # no duplicate on second sign-in


def test_existing_password_account_links_by_email(client, google_on, google_http):
    from app.routers.auth import _hash

    db = client.session_factory()
    db.add(User(email="ana@evergent.com", name="Ana", hashed_password=_hash("pw"), role="member"))
    db.commit()
    db.close()

    client.get("/auth/google/callback?code=x&state=" + _fresh_state(client), follow_redirects=False)
    users = _users(client)
    assert len(users) == 1
    assert users[0].oauth_subject == "google-sub-1"
    assert users[0].role == "member"  # linking never escalates


def test_tampered_state_rejected(client, google_on, google_http):
    state = _start(client) + "forged"
    r = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
    assert r.status_code == 302
    assert "error=invalid_state" in r.headers["location"]
    assert _users(client) == []


def test_missing_cookie_rejected(client, google_on, google_http):
    state = _start(client)
    client.cookies.clear()
    r = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
    assert "error=invalid_state" in r.headers["location"]
    assert _users(client) == []


def test_user_denied_at_google(client, google_on):
    r = client.get("/auth/google/callback?error=access_denied", follow_redirects=False)
    assert r.status_code == 302
    assert "error=denied" in r.headers["location"]
    assert _users(client) == []


def test_exchange_failure_redirects(client, google_on, google_http):
    google_http.token_status = 400
    r = client.get(
        "/auth/google/callback?code=bad&state=" + _fresh_state(client), follow_redirects=False
    )
    assert "error=oauth_failed" in r.headers["location"]
    assert _users(client) == []


def test_wrong_audience_rejected(client, google_on, google_http):
    google_http.tokeninfo_payload["aud"] = "someone-elses-client"
    r = client.get(
        "/auth/google/callback?code=x&state=" + _fresh_state(client), follow_redirects=False
    )
    assert "error=oauth_failed" in r.headers["location"]
    assert _users(client) == []


def test_unverified_email_rejected(client, google_on, google_http):
    google_http.tokeninfo_payload["email_verified"] = "false"
    r = client.get(
        "/auth/google/callback?code=x&state=" + _fresh_state(client), follow_redirects=False
    )
    assert "error=oauth_failed" in r.headers["location"]
    assert _users(client) == []


def test_disallowed_domain_rejected(client, google_on, google_http, monkeypatch):
    monkeypatch.setenv("GOOGLE_ALLOWED_DOMAINS", "evergent.com")
    get_settings.cache_clear()
    try:
        google_http.tokeninfo_payload["hd"] = "gmail.com"
        google_http.tokeninfo_payload["email"] = "ana@gmail.com"
        r = client.get(
            "/auth/google/callback?code=x&state=" + _fresh_state(client), follow_redirects=False
        )
        assert "error=domain" in r.headers["location"]
        assert _users(client) == []
    finally:
        get_settings.cache_clear()


def test_allowed_domain_passes(client, google_on, google_http, monkeypatch):
    monkeypatch.setenv("GOOGLE_ALLOWED_DOMAINS", "Evergent.com")  # case-insensitive
    get_settings.cache_clear()
    try:
        r = client.get(
            "/auth/google/callback?code=x&state=" + _fresh_state(client), follow_redirects=False
        )
        assert "/auth/callback#" in r.headers["location"]
    finally:
        get_settings.cache_clear()


def test_open_redirect_next_is_neutered(client, google_on):
    for evil in ["//evil.com", "https://evil.com", "javascript:alert(1)"]:
        r = client.get(f"/auth/google/login?next={evil}", follow_redirects=False)
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        claims = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
        assert claims["next"] == "/"


def test_password_login_rejects_google_only_account(client):
    db = client.session_factory()
    db.add(
        User(
            email="g@evergent.com",
            name="G",
            hashed_password=None,
            role="member",
            auth_provider="google",
            oauth_subject="sub-9",
        )
    )
    db.commit()
    db.close()
    r = client.post("/auth/login", json={"email": "g@evergent.com", "password": "anything"})
    assert r.status_code == 401
