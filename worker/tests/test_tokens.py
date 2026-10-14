"""TokenManager: refresh, rotation, expiry, and the on_rotate callback (§2.2)."""

import httpx
import pytest

from app.last9.errors import AuthExpiredError
from app.last9.tokens import TokenManager, TokenSet

from .conftest import API_BASE, mock_client

OAUTH_PATH = "/api/v4/oauth/access_token"


def test_refresh_posts_refresh_token_and_stores_access():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == OAUTH_PATH
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"access_token": "AT1", "expires_at": 5000})

    tm = TokenManager(
        TokenSet(refresh_token="RT0"),
        api_base=API_BASE,
        http=mock_client(handler),
        now=lambda: 1000.0,
    )
    assert tm.get_access_token() == "AT1"
    assert seen["body"] == {"refresh_token": "RT0"}
    assert tm.tokens.expires_at == 5000


def test_rotated_refresh_token_is_adopted_and_callback_fired():
    rotations = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": "AT2", "refresh_token": "RT1", "expires_in": 86400}
        )

    tm = TokenManager(
        TokenSet(refresh_token="RT0"),
        api_base=API_BASE,
        http=mock_client(handler),
        on_rotate=lambda ts: rotations.append((ts.access_token, ts.refresh_token)),
        now=lambda: 0.0,
    )
    tm.refresh()
    assert tm.tokens.refresh_token == "RT1"
    assert tm.tokens.expires_at == 86400
    assert rotations == [("AT2", "RT1")]


def test_valid_token_not_refreshed():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"access_token": "NEW", "expires_at": 10_000})

    tm = TokenManager(
        TokenSet(refresh_token="RT0", access_token="CACHED", expires_at=10_000),
        api_base=API_BASE,
        http=mock_client(handler),
        now=lambda: 1000.0,
    )
    assert tm.get_access_token() == "CACHED"
    assert calls["n"] == 0


def test_expired_token_triggers_refresh():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "FRESH", "expires_at": 99_999})

    tm = TokenManager(
        TokenSet(refresh_token="RT0", access_token="OLD", expires_at=1000),
        api_base=API_BASE,
        http=mock_client(handler),
        now=lambda: 2000.0,  # past expiry
    )
    assert tm.get_access_token() == "FRESH"


def test_expiry_parsed_from_iso_string():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": "AT", "expires_at": "2024-01-01T00:00:00Z"}
        )

    tm = TokenManager(TokenSet(refresh_token="RT0"), api_base=API_BASE, http=mock_client(handler))
    tm.refresh()
    assert tm.tokens.expires_at == 1704067200


def test_expiry_falls_back_to_assumed_lifetime():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "AT"})  # no expiry field

    tm = TokenManager(
        TokenSet(refresh_token="RT0"),
        api_base=API_BASE,
        http=mock_client(handler),
        now=lambda: 1000.0,
    )
    tm.refresh()
    assert tm.tokens.expires_at == 1000 + 24 * 3600


def test_refresh_failure_raises_auth_expired():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "nope"})

    tm = TokenManager(
        TokenSet(refresh_token="BAD"),
        api_base=API_BASE,
        http=mock_client(handler),
    )
    with pytest.raises(AuthExpiredError):
        tm.refresh()


def test_missing_access_token_in_response_raises():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"expires_at": 1})

    tm = TokenManager(
        TokenSet(refresh_token="RT0"),
        api_base=API_BASE,
        http=mock_client(handler),
    )
    with pytest.raises(AuthExpiredError):
        tm.refresh()


def test_transient_refresh_failure_is_retried():
    """A 5xx from the OAuth endpoint must not discard a long-running job.

    The 10-attempt backoff policy covered only the query call, so a single 503
    on refresh at chunk 690 of 720 failed the whole job — and a failed job can
    only be re-run from scratch, not resumed.
    """
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="upstream unavailable")
        return httpx.Response(200, json={"access_token": "AT-after-retry", "expires_at": 5000})

    slept: list[float] = []
    tm = TokenManager(
        TokenSet(refresh_token="RT0"),
        api_base=API_BASE,
        http=mock_client(handler),
        now=lambda: 1000.0,
        sleep=slept.append,
    )

    assert tm.refresh() == "AT-after-retry"
    assert calls["n"] == 3
    assert slept, "retries must back off rather than hammer the endpoint"


def test_connection_error_on_refresh_is_retried():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("connection reset")
        return httpx.Response(200, json={"access_token": "AT-ok", "expires_at": 5000})

    tm = TokenManager(
        TokenSet(refresh_token="RT0"),
        api_base=API_BASE,
        http=mock_client(handler),
        now=lambda: 1000.0,
        sleep=lambda _s: None,
    )
    assert tm.refresh() == "AT-ok"


def test_a_rejected_refresh_token_fails_fast():
    """4xx means the token is genuinely bad — retrying just delays the failure."""
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "invalid refresh token"})

    tm = TokenManager(
        TokenSet(refresh_token="BAD"),
        api_base=API_BASE,
        http=mock_client(handler),
        sleep=lambda _s: None,
    )
    with pytest.raises(AuthExpiredError):
        tm.refresh()
    assert calls["n"] == 1, "a 4xx must not be retried"
