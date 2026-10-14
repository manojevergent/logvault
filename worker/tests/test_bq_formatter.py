"""Tests for BQ log line parser."""

from app.last9.bq_formatter import parse_bq_row

# ── Format A samples ──────────────────────────────────────────────────────────

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

# ── Format B samples ──────────────────────────────────────────────────────────

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


# ── Format A tests ────────────────────────────────────────────────────────────


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


# ── Format B tests ────────────────────────────────────────────────────────────


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
    # ABSCBN has cpCustomerID, not spAccountID — tests the fallback path
    row = parse_bq_row(ABSCBN_LINE, TS)
    assert row is not None
    assert row.sp_account_id == "f670dbde-bff7-4bca-8d27-30ce9f62b0f0"


# ── Unknown format ────────────────────────────────────────────────────────────


def test_unknown_format_returns_none():
    assert parse_bq_row("some random log line with no structure", TS) is None


def test_empty_returns_none():
    assert parse_bq_row("", TS) is None
