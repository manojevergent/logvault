"""Last9Client: request wiring, pagination/streaming, message extraction, and
the full §2.10 retry policy including inline token refresh (§2.2)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.last9.client import Last9Client, _extract_message
from app.last9.errors import (
    AuthExpiredError,
    FatalClientError,
    RetryableError,
    TransientBadRequestError,
)
from app.last9.pipeline import build_filter_pipeline

from .conftest import API_BASE, ORG, mock_client, query_response


class FakeTokens:
    """Stand-in TokenManager: returns a token, counts refreshes."""

    def __init__(self) -> None:
        self.token = "AT0"
        self.refreshes = 0

    def get_access_token(self) -> str:
        return self.token

    def refresh(self) -> str:
        self.refreshes += 1
        self.token = f"AT{self.refreshes}"
        return self.token


def sequence_handler(responses, captured: list[httpx.Request] | None = None):
    """Return queued responses in order; optionally record each request."""
    it = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        item = next(it)
        return item(request) if callable(item) else item

    return handler


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    tokens: FakeTokens | None = None,
    sleeps: list[float] | None = None,
    **kwargs,
) -> Last9Client:
    return Last9Client(
        token_manager=tokens or FakeTokens(),  # type: ignore[arg-type]
        org_slug=ORG,
        api_base=API_BASE,
        http=mock_client(handler),
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
        **kwargs,
    )


PIPE = build_filter_pipeline(phrases=["x"])


def _drain(client: Last9Client, **kw):
    return list(
        client.iter_rows(
            index="physical_index:UMServices",
            region="ap-southeast-1",
            start=0,
            end=3600,
            pipeline=PIPE,
            **kw,
        )
    )


# ── request wiring ─────────────────────────────────────────────────────────


def test_request_uses_custom_header_url_params_and_body():
    captured: list[httpx.Request] = []
    handler = sequence_handler([query_response([("1", "hello")])], captured)
    client = make_client(handler)

    rows = _drain(client, limit=10000)
    assert len(rows) == 1

    req = captured[0]
    assert req.url.path == f"/api/v4/organizations/{ORG}/logs/api/v2/query_range/json"
    # §2.2 — custom header, not Authorization.
    assert req.headers["X-LAST9-API-TOKEN"] == "Bearer AT0"
    assert "authorization" not in {k.lower() for k in req.headers}
    params = dict(req.url.params)
    assert params["index"] == "physical_index:UMServices"
    assert params["region"] == "ap-southeast-1"
    # Forward so the CSV is oldest-first; backward made each hour land
    # newest-first and the day appeared to start at 00:59:59.
    assert params["direction"] == "forward"
    assert params["step"] == "200ms"
    assert params["offset"] == "0"
    body = json.loads(req.content)
    assert body == {"pipeline": PIPE}


def test_empty_index_omits_the_index_param_for_the_org_default():
    """The org's Default index is addressed by sending no `index` at all —
    any value (even the UI's "Default" label) 400s with a misleading
    "parse error: invalid JSON pipeline". Verified live against Singapore."""
    captured: list[httpx.Request] = []
    handler = sequence_handler([query_response([("1", "hello")])], captured)
    client = make_client(handler)

    rows = list(
        client.iter_rows(
            index="",
            region="ap-southeast-1",
            start=0,
            end=3600,
            pipeline=PIPE,
        )
    )
    assert len(rows) == 1
    params = dict(captured[0].url.params)
    assert "index" not in params
    assert params["region"] == "ap-southeast-1"


# ── pagination & streaming (§2.8) ────────────────────────────────────────────


def test_pagination_advances_offset_until_short_page():
    captured: list[httpx.Request] = []
    handler = sequence_handler(
        [
            query_response([("1", "a"), ("2", "b")]),  # full page (== limit)
            query_response([("3", "c")]),  # short page -> stop
        ],
        captured,
    )
    client = make_client(handler)
    rows = _drain(client, limit=2)

    assert [r.message for r in rows] == ["a", "b", "c"]
    assert [dict(c.url.params)["offset"] for c in captured] == ["0", "2"]


def test_empty_result_yields_nothing_and_stops():
    handler = sequence_handler([query_response([])])
    client = make_client(handler)
    assert _drain(client, limit=2) == []


def test_non_string_raw_line_is_json_encoded():
    # Some values carry a structured object rather than a string line.
    body = {"data": {"data": {"result": [{"values": [["1", {"message": "structured"}]]}]}}}
    handler = sequence_handler([httpx.Response(200, json=body)])
    client = make_client(handler)
    rows = _drain(client, limit=10)
    assert rows[0].message == "structured"
    assert rows[0].raw == json.dumps({"message": "structured"})


def test_handles_shallow_result_nesting():
    handler = sequence_handler([query_response([("1", "shallow")], nested=False)])
    client = make_client(handler)
    rows = _drain(client, limit=10)
    assert [r.message for r in rows] == ["shallow"]


# ── message extraction (§2.8) ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        (json.dumps({"message": "m"}), "m"),
        (json.dumps({"Message": "M"}), "M"),
        (json.dumps({"Body": "B"}), "B"),
        (json.dumps({"body": "b"}), "b"),
        (json.dumps({"msg": "s"}), "s"),
        ("plain text line", "plain text line"),
        (json.dumps({"other": 1}), json.dumps({"other": 1})),
    ],
)
def test_extract_message_tries_known_keys(raw, expected):
    assert _extract_message(raw) == expected


# ── retry policy (§2.10) ─────────────────────────────────────────────────────


def test_5xx_retries_with_exponential_backoff_then_succeeds():
    sleeps: list[float] = []
    handler = sequence_handler(
        [
            httpx.Response(500),
            httpx.Response(503),
            query_response([("1", "ok")]),
        ]
    )
    client = make_client(handler, sleeps=sleeps)
    rows = _drain(client, limit=10)
    assert [r.message for r in rows] == ["ok"]
    assert sleeps == [1.0, 2.0]  # exponential: base*2^(n-1)


def test_5xx_exhausts_attempts_and_raises_retryable():
    handler = sequence_handler([httpx.Response(500)] * 10)
    client = make_client(handler, max_attempts=3)
    with pytest.raises(RetryableError) as ei:
        _drain(client, limit=10)
    assert ei.value.attempts == 3


def test_backoff_is_capped():
    sleeps: list[float] = []
    handler = sequence_handler([httpx.Response(500)] * 4 + [query_response([("1", "ok")])])
    client = make_client(handler, sleeps=sleeps, backoff_cap=3.0, max_attempts=10)
    _drain(client, limit=10)
    assert sleeps == [1.0, 2.0, 3.0, 3.0]  # capped at 3.0


def test_timeout_and_connect_errors_are_retried():
    def raiser(exc):
        def _r(_request):
            raise exc

        return _r

    handler = sequence_handler(
        [
            raiser(httpx.ConnectTimeout("boom")),
            raiser(httpx.ConnectError("nope")),
            query_response([("1", "ok")]),
        ]
    )
    client = make_client(handler, sleeps=[])
    assert [r.message for r in _drain(client, limit=10)] == ["ok"]


def test_connection_errors_exhaust_and_raise_retryable():
    def raiser(_request):
        raise httpx.ConnectError("down")

    handler = sequence_handler([raiser] * 10)
    client = make_client(handler, max_attempts=3)
    with pytest.raises(RetryableError) as ei:
        _drain(client, limit=10)
    assert ei.value.attempts == 3


def test_400_retries_flat_then_raises_transient():
    sleeps: list[float] = []
    handler = sequence_handler([httpx.Response(400, text="bad")] * 3)
    client = make_client(handler, sleeps=sleeps)
    with pytest.raises(TransientBadRequestError):
        _drain(client, limit=10)
    assert sleeps == [5.0, 5.0]  # two flat 5s waits, third attempt raises


def test_other_4xx_fast_fails():
    for status in (403, 404, 429):
        handler = sequence_handler([httpx.Response(status, text="x")])
        client = make_client(handler)
        with pytest.raises(FatalClientError) as ei:
            _drain(client, limit=10)
        assert ei.value.status == status


# ── inline auth refresh (§2.2) ───────────────────────────────────────────────


def test_401_triggers_refresh_then_retry():
    tokens = FakeTokens()
    captured: list[httpx.Request] = []
    handler = sequence_handler([httpx.Response(401), query_response([("1", "ok")])], captured)
    client = make_client(handler, tokens=tokens)
    assert [r.message for r in _drain(client, limit=10)] == ["ok"]
    assert tokens.refreshes == 1
    # retried request carries the refreshed token
    assert captured[1].headers["X-LAST9-API-TOKEN"] == "Bearer AT1"


def test_200_with_expired_marker_triggers_refresh():
    tokens = FakeTokens()
    handler = sequence_handler(
        [
            httpx.Response(200, text="Authorization token is expired"),
            query_response([("1", "ok")]),
        ]
    )
    client = make_client(handler, tokens=tokens)
    assert [r.message for r in _drain(client, limit=10)] == ["ok"]
    assert tokens.refreshes == 1


def test_repeated_401_after_refresh_raises_auth_expired():
    tokens = FakeTokens()
    handler = sequence_handler([httpx.Response(401)] * 5)
    client = make_client(handler, tokens=tokens, max_auth_refreshes=2)
    with pytest.raises(AuthExpiredError):
        _drain(client, limit=10)


# ── error messages carry the server's explanation ────────────────────────────


def _erroring_client(status: int, body: str):
    import httpx

    from app.last9 import Last9Client, TokenManager, TokenSet

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    tokens = TokenManager(
        TokenSet(refresh_token="rt", access_token="at", expires_at=2**31),
        api_base=API_BASE,
        http=http,
        on_rotate=lambda _t: None,
    )
    return Last9Client(token_manager=tokens, org_slug=ORG, api_base=API_BASE, http=http)


def test_403_reports_what_the_server_actually_said():
    """ "HTTP 403" alone doesn't say whether the credential, org, region or index
    is at fault — the body does."""
    from app.last9 import FatalClientError

    client = _erroring_client(
        403, '{ "type": "error", "message": "You don\'t have access to this resource."}'
    )
    with pytest.raises(FatalClientError) as exc:
        list(
            client.iter_rows(
                index="physical_index:X", region="us-east-1", start=0, end=1, pipeline=[]
            )
        )
    assert "403" in str(exc.value)
    assert "don't have access to this resource" in str(exc.value)


def test_5xx_reports_the_server_error_code_not_just_the_status():
    from app.last9 import RetryableError

    client = _erroring_client(500, '{"error":"ERR_S3_CONFIG_MISSING"}')
    client._sleep = lambda _s: None  # don't actually back off in a test
    with pytest.raises(RetryableError) as exc:
        list(
            client.iter_rows(
                index="physical_index:X", region="us-east-1", start=0, end=1, pipeline=[]
            )
        )
    assert "ERR_S3_CONFIG_MISSING" in str(exc.value)


def test_an_unparseable_error_body_still_produces_a_usable_message():
    from app.last9 import FatalClientError

    client = _erroring_client(403, "<html>Forbidden</html>")
    with pytest.raises(FatalClientError) as exc:
        list(
            client.iter_rows(
                index="physical_index:X", region="us-east-1", start=0, end=1, pipeline=[]
            )
        )
    assert "403" in str(exc.value)
    assert "Forbidden" in str(exc.value)


def test_an_empty_error_body_falls_back_to_the_status_alone():
    from app.last9 import FatalClientError

    client = _erroring_client(404, "")
    with pytest.raises(FatalClientError) as exc:
        list(
            client.iter_rows(
                index="physical_index:X", region="us-east-1", start=0, end=1, pipeline=[]
            )
        )
    assert str(exc.value) == "HTTP 404"


# ── message extraction from envelopes that aren't valid JSON ─────────────────

# Shape seen in production: a redaction step drops bare quotes into the string
# value, so the envelope no longer parses.
_BROKEN = (
    '{"level":"TRACK","timestamp":"2026-08-31 15:51:41:224 UTC","thread":"WorkerThread46",'
    '"message":"ABSCBN-1-6a95a30d - ABSCBNController getContactPostAction -- '
    'request:<channelPartnerID>ABSCBN</channelPartnerID>apiPassword="***REDACTED***"'
    '<apiUser>abscbnapiuser</apiUser>"}'
)


def test_a_valid_envelope_still_yields_just_the_message():
    assert _extract_message('{"level":"INFO","message":"hello"}') == "hello"


def test_an_unparseable_envelope_still_yields_the_log_line():
    """Returning the whole envelope forces every parse pattern to match JSON
    wrapper text instead of the log line — which reads as "0 rows matched"."""
    out = _extract_message(_BROKEN)
    assert out.startswith("ABSCBN-1-")
    assert not out.startswith("{")
    assert '"level"' not in out
    # The unescaped quotes inside the message survive intact.
    assert 'apiPassword="***REDACTED***"' in out


def test_a_plain_non_json_line_is_returned_unchanged():
    assert _extract_message("just a log line") == "just a log line"


# A real multi-line record: timestamp/blank line, a (broken) JSON envelope with
# unescaped redaction quotes, then a trace line. The whole block used to reach
# the parse pattern, so an anchored regex could never match the inner request.
_MULTILINE_STANDARD = (
    "2026-11-05 18:08:00:630 UTC\n\n"
    '{"level":"TRACK","timestamp":"2026-11-05 18:07:55:102 UTC",'
    '"thread":"WorkerThread1","class":"Logger","message":"'
    "1-6aecc5fb-374d56d06974b82b543bc94c - getActiveSubscriptionsPostAction -- "
    "data comes from request:<GetActiveSubscriptionRequestMessage><returnTVOD>F</returnTVOD>"
    "<channelPartnerID>LIGHTBOX</channelPartnerID>"
    "<sessionToken>MyNp-pvSM-xAaQ-HDpC-o7xw-YVB3-Yr</sessionToken>"
    'apiPassword="***REDACTED***"<apiUser>lightboxapiuser</apiUser>'
    '</GetActiveSubscriptionRequestMessage>"}\n'
    "User BU Query time: 0 ms"
)

# Entry-time trace: the JSON message is only a marker; the actual request is the
# line after the envelope, using "data request cp :" instead of "data comes from
# request:".
_MULTILINE_ENTRY = (
    "2026-11-05 19:22:10:625 UTC\n\n"
    '{"level":"TRACK","timestamp":"2026-11-05 19:22:07:189 UTC",'
    '"thread":"WorkerThread20","message":'
    '"[getAcctPairedCoupensCodesPostAction entry time] 1793906527189"}\n'
    "data request cp : <GetAccountPairedCouponCodesRequest>"
    "<channelPartnerID>LIGHTBOX</channelPartnerID>"
    "<sessionToken>v8oG-Cocl-EIXN-veD3-T2T0-vucX-T3</sessionToken>"
    'apiPassword="***REDACTED***"<apiUser>neoniframeuser</apiUser>'
    "</GetAccountPairedCouponCodesRequest>\n"
    "unmarshell request : null"
)


def test_a_multiline_standard_request_is_unwrapped():
    out = _extract_message(_MULTILINE_STANDARD)
    assert out.startswith("1-6aecc5fb-")
    assert "<channelPartnerID>LIGHTBOX" in out
    assert '"level"' not in out


def test_a_multiline_entry_time_trace_joins_the_request_line():
    out = _extract_message(_MULTILINE_ENTRY)
    assert out.startswith("getAcctPairedCoupensCodesPostAction -- data request cp :")
    assert "<sessionToken>v8oG-Cocl" in out
    assert '"level"' not in out


def test_a_broken_line_that_is_not_an_envelope_is_returned_unchanged():
    assert _extract_message("not json {but has a brace") == "not json {but has a brace"


def test_a_broken_envelope_with_no_message_key_is_returned_unchanged():
    raw = '{"level":"TRACK","detail":"a="b" c"}'
    assert _extract_message(raw) == raw
