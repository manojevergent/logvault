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
_TOKEN_RE = re.compile(r"^(?P<session_token>(?P<customer>[A-Za-z0-9]+)-\d+-[0-9a-f]+-[0-9a-f]+)")
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
