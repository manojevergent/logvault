"""Last9 endpoint setting: the BYOC base URL, its env fallback, and validation.

The endpoint used to be env-only. Moving to BYOC means an admin has to point
extraction at a different host without rebuilding the images, so the value lives
in app_settings and is read at call time.
"""

from __future__ import annotations

import pytest

from app import last9_config


def test_normalize_strips_the_trailing_slash():
    assert (
        last9_config.normalize_api_base("https://l9.example.com/api/v4/")
        == "https://l9.example.com/api/v4"
    )


def test_normalize_adds_a_scheme_to_a_bare_host():
    assert (
        last9_config.normalize_api_base("l9.internal.example.com/api/v4")
        == "https://l9.internal.example.com/api/v4"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "ftp://l9.example.com",
        "https://l9.example.com/api?x=1",
        "https://l9.example.com/api#frag",
    ],
)
def test_rejects_invalid_urls(bad):
    with pytest.raises(ValueError):
        last9_config.normalize_api_base(bad)


def test_env_fallback_when_nothing_is_saved(client):
    out = client.get("/settings/last9").json()
    assert out["source"] == "env"
    assert out["api_base"] == out["default_api_base"]


def test_saving_persists_and_reports_database(client):
    resp = client.patch("/settings/last9", json={"api_base": "https://l9.byoc.example.com/api/v4/"})
    assert resp.status_code == 200
    assert resp.json()["api_base"] == "https://l9.byoc.example.com/api/v4"
    assert resp.json()["source"] == "database"

    out = client.get("/settings/last9").json()
    assert out["api_base"] == "https://l9.byoc.example.com/api/v4"
    assert out["source"] == "database"


def test_settings_readout_uses_the_saved_endpoint(client):
    client.patch("/settings/last9", json={"api_base": "https://l9.byoc.example.com/api/v4"})
    assert client.get("/settings").json()["last9_api_base"] == "https://l9.byoc.example.com/api/v4"


def test_invalid_save_is_rejected(client):
    resp = client.patch("/settings/last9", json={"api_base": "ftp://nope"})
    assert resp.status_code == 422


def test_only_admins_can_read_or_change_the_endpoint(member_client):
    assert member_client.get("/settings/last9").status_code == 403
    assert (
        member_client.patch(
            "/settings/last9", json={"api_base": "https://x.example.com"}
        ).status_code
        == 403
    )
