# Task 1: Parser module bq_formatter.py

## Context
This is LogVault — a log extraction platform. We're adding a BigQuery output format
that parses Evergent application logs into a fixed 6-column schema.

## Files
- CREATE: `worker/app/last9/bq_formatter.py`
- CREATE: `worker/tests/test_bq_formatter.py`
- MODIFY: `worker/app/last9/__init__.py`

## What to implement

### `worker/app/last9/bq_formatter.py`

```python
"""Parse Evergent application log lines into the BigQuery 6-column schema.

Two known formats:
  A – ClassName/command:  {token} - ClassName {api} SPAccountId {id} in BU {bu} API User {user}
  B – Controller/XML:     {token} - [In] [Controller] {action} -- data comes from request: <xml>

Detection is by cheap ``in`` hint before any regex runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Format A ──────────────────────────────────────────────────────────────────

_FORMAT_A_HINT = "ClassName "
_FORMAT_A_RE = re.compile(
    r"^(?P<session_token>(?P<customer>[A-Za-z0-9]+)-\d+-[0-9a-f]+-[0-9a-f]+)"
    r"\s+-\s+ClassName\s+(?P<api_name>\S+)"
    r"\s+SPAccountId\s+(?P<sp_account_id>\S+)"
    r"\s+in\s+BU\s+(?P<bu_name>.+?)\s+API\s+User\s+\S+"
)

# ── Format B ──────────────────────────────────────────────────────────────────

_FORMAT_B_HINT = "-- data comes from request"
_TOKEN_RE = re.compile(
    r"^(?P<session_token>(?P<customer>[A-Za-z0-9]+)-\d+-[0-9a-f]+-[0-9a-f]+)"
)
_ACTION_RE = re.compile(r"(\w+)\s+--\s+data comes from request")
_CHANNEL_PARTNER_RE = re.compile(r"<channelPartnerID>([^<]+)</channelPartnerID>")
_SP_ACCOUNT_RE = re.compile(r"<spAccountID>([^<]+)</spAccountID>")
_CP_CUSTOMER_RE = re.compile(r"<cpCustomerID>([^<]+)</cpCustomerID>")


@dataclass
class BQRow:
    bu_name: str
    timestamp: str
    session_token: str
    sp_account_id: str
    api_name: str
    channel_partner_id: str


def parse_bq_row(message: str, timestamp: str) -> BQRow | None:
    """Return a BQRow or None if the message matches neither known pattern."""
    if not message:
        return None
    if _FORMAT_A_HINT in message:
        return _parse_format_a(message, timestamp)
    if _FORMAT_B_HINT in message:
        return _parse_format_b(message, timestamp)
    return None


def _parse_format_a(message: str, timestamp: str) -> BQRow | None:
    m = _FORMAT_A_RE.match(message)
    if m is None:
        return None
    cp_m = _CHANNEL_PARTNER_RE.search(message)
    return BQRow(
        bu_name=m.group("bu_name"),
        timestamp=timestamp,
        session_token=m.group("session_token"),
        sp_account_id=m.group("sp_account_id"),
        api_name=m.group("api_name"),
        channel_partner_id=cp_m.group(1) if cp_m else "",
    )


def _parse_format_b(message: str, timestamp: str) -> BQRow | None:
    token_m = _TOKEN_RE.match(message)
    action_m = _ACTION_RE.search(message)
    if token_m is None or action_m is None:
        return None

    cp_m = _CHANNEL_PARTNER_RE.search(message)
    sp_m = _SP_ACCOUNT_RE.search(message)
    cpc_m = _CP_CUSTOMER_RE.search(message)

    sp_account_id = sp_m or cpc_m
    return BQRow(
        bu_name=token_m.group("customer"),
        timestamp=timestamp,
        session_token=token_m.group("session_token"),
        sp_account_id=sp_account_id.group(1) if sp_account_id else "",
        api_name=action_m.group(1),
        channel_partner_id=cp_m.group(1) if cp_m else "-",
    )


__all__ = ["BQRow", "parse_bq_row"]
```

### `worker/tests/test_bq_formatter.py`

```python
"""Tests for BQ log line parser."""
from app.last9.bq_formatter import BQRow, parse_bq_row


AHA_LINE = (
    "AHA-1-6a9a915b-48da52e15d3f654156570481 - ClassName CGetEntitlementsCommand"
    " SPAccountId 241230090725797443495533 in BU AHA INDIA API User ahaapiuser"
)
EKKL_LINE = (
    "Pinnacle-1-6a9a930a-0fcc40f21336225559bf1464 - ClassName CGetOAuthAccessTokenCommand"
    " SPAccountId 260904093229112484608283 in BU Ekkl API User EkklWebApiUser"
)
MARQUEE_LINE = (
    "Marquee-1-6a9a951e-3ee450ed0670d98a40ba113d - ClassName GetOAuthAccessTokenCommand"
    " SPAccountId 250404142056048402406598 in BU Marquee API User MKClientapiuser"
)
ABSCBN_LINE = (
    "ABSCBN-1-6a9a91a4-73c12a735fa51a0567d87320 - ABSCBNController getContactPostAction"
    " -- data comes from request:<GetContactRequestMessage>"
    "<cpCustomerID>f670dbde-bff7-4bca-8d27-30ce9f62b0f0</cpCustomerID>"
    "<channelPartnerID>ABSCBN</channelPartnerID>"
    "<apiUser>abscbnapiuser</apiUser></GetContactRequestMessage>"
)
FA_LINE = (
    "FA-1-6a9a6c2b-7a210ff006c02c3f6c3262a9 - In FAController addSubscriptionPostAction"
    " -- data comes from request :<AddSubscriptionRequestMessage>"
    "<spAccountID>78493126</spAccountID>"
    "<channelPartnerID>FA</channelPartnerID>"
    "</AddSubscriptionRequestMessage>"
)
VIKI_LINE = (
    "VIKI-1-6a9a96fb-4e40d57f4074e74c4615a705 - getProductsPostAction"
    " -- data comes from request : <GetProductsRequestMessage>"
    "<spAccountID>129169649u</spAccountID>"
    "<channelPartnerID>VIKI</channelPartnerID>"
    "</GetProductsRequestMessage>"
)
TS = "2026-09-04T10:00:00Z"


def test_format_a_aha():
    row = parse_bq_row(AHA_LINE, TS)
    assert row is not None
    assert row.bu_name == "AHA INDIA"
    assert row.session_token == "AHA-1-6a9a915b-48da52e15d3f654156570481"
    assert row.sp_account_id == "241230090725797443495533"
    assert row.api_name == "CGetEntitlementsCommand"
    assert row.channel_partner_id == ""
    assert row.timestamp == TS


def test_format_a_ekkl():
    row = parse_bq_row(EKKL_LINE, TS)
    assert row is not None
    assert row.bu_name == "Ekkl"
    assert row.session_token == "Pinnacle-1-6a9a930a-0fcc40f21336225559bf1464"
    assert row.sp_account_id == "260904093229112484608283"
    assert row.api_name == "CGetOAuthAccessTokenCommand"
    assert row.channel_partner_id == ""


def test_format_a_marquee():
    row = parse_bq_row(MARQUEE_LINE, TS)
    assert row is not None
    assert row.bu_name == "Marquee"
    assert row.session_token == "Marquee-1-6a9a951e-3ee450ed0670d98a40ba113d"
    assert row.sp_account_id == "250404142056048402406598"
    assert row.api_name == "GetOAuthAccessTokenCommand"


def test_format_a_with_channel_partner_in_xml():
    line = AHA_LINE.rstrip() + " <channelPartnerID>AHACHAN</channelPartnerID>"
    row = parse_bq_row(line, TS)
    assert row is not None
    assert row.channel_partner_id == "AHACHAN"


def test_format_b_abscbn():
    row = parse_bq_row(ABSCBN_LINE, TS)
    assert row is not None
    assert row.bu_name == "ABSCBN"
    assert row.session_token == "ABSCBN-1-6a9a91a4-73c12a735fa51a0567d87320"
    assert row.sp_account_id == "f670dbde-bff7-4bca-8d27-30ce9f62b0f0"
    assert row.api_name == "getContactPostAction"
    assert row.channel_partner_id == "ABSCBN"


def test_format_b_fa():
    row = parse_bq_row(FA_LINE, TS)
    assert row is not None
    assert row.bu_name == "FA"
    assert row.sp_account_id == "78493126"
    assert row.api_name == "addSubscriptionPostAction"
    assert row.channel_partner_id == "FA"


def test_format_b_viki():
    row = parse_bq_row(VIKI_LINE, TS)
    assert row is not None
    assert row.bu_name == "VIKI"
    assert row.sp_account_id == "129169649u"
    assert row.api_name == "getProductsPostAction"
    assert row.channel_partner_id == "VIKI"


def test_format_b_missing_channel_partner_id():
    line = FA_LINE.replace("<channelPartnerID>FA</channelPartnerID>", "")
    row = parse_bq_row(line, TS)
    assert row is not None
    assert row.channel_partner_id == "-"


def test_format_b_sp_account_id_fallback_to_cp_customer_id():
    row = parse_bq_row(ABSCBN_LINE, TS)
    assert row is not None
    assert row.sp_account_id == "f670dbde-bff7-4bca-8d27-30ce9f62b0f0"


def test_unknown_format_returns_none():
    assert parse_bq_row("some random log line with no structure", TS) is None


def test_empty_returns_none():
    assert parse_bq_row("", TS) is None
```

### `worker/app/last9/__init__.py` changes

Add this import after `from .formats import FormatMatcher, LogFormat, validate_formats`:
```python
from .bq_formatter import BQRow, parse_bq_row
```

Add to `__all__` in alphabetical position:
```python
    "BQRow",   # after "AggregationSpec" block
    ...
    "parse_bq_row",   # after "plan_extraction"
```

## Report file
Write your completion report to: `.superpowers/sdd/task-1-report.md`
Include: files created/modified, test results (command + output), any concerns.
