"""Matching a row against a library of named patterns.

The behaviour that matters: the right format wins, order is controllable, and
trying hundreds of formats stays affordable.
"""

from __future__ import annotations

import pytest

from app.last9.formats import FormatMatcher, LogFormat, validate_formats
from app.last9.patterns import AggregationError

AHA = LogFormat(
    name="aha",
    regex=r"SPAccountId\s+(?<cpid>\S+)\s+in\s+BU\s+(?<partner>\S+)",
    hint="SPAccountId",
)
ABSCBN = LogFormat(
    name="abscbn",
    regex=r"<cpCustomerID>(?<cpid>[^<]*)</cpCustomerID>.*?<channelPartnerID>(?<partner>[^<]*)</channelPartnerID>",
    hint="cpCustomerID",
)
AHA_LINE = "AHA-1-x - ClassName C SPAccountId  1001 in BU  AHA-INDIA API User u"
ABS_LINE = "ABSCBN-1-y - C getContact <cpCustomerID>abc-123</cpCustomerID><channelPartnerID>ABSCBN</channelPartnerID>"


def test_each_line_is_parsed_by_the_format_that_fits_it():
    m = FormatMatcher([AHA, ABSCBN])
    aha = m.match(AHA_LINE)
    abs_ = m.match(ABS_LINE)
    assert aha.format_name == "aha"
    assert aha.fields == {"cpid": "1001", "partner": "AHA-INDIA"}
    assert abs_.format_name == "abscbn"
    assert abs_.fields == {"cpid": "abc-123", "partner": "ABSCBN"}


def test_common_group_names_are_what_let_formats_aggregate_together():
    """Both formats name the customer id `cpid`, so one aggregation spans both
    log shapes — the named group is the normalisation layer."""
    m = FormatMatcher([AHA, ABSCBN])
    assert set(m.field_names()) == {"cpid", "partner"}


def test_field_names_ordered_is_stable_and_deduped():
    """The parse-only header needs a fixed order — a set would vary by hash seed."""
    extra = LogFormat(name="extra", regex=r"(?<api>\w+)\s+(?<cpid>\S+)")
    m = FormatMatcher([ABSCBN, AHA, extra])
    assert m.field_names_ordered() == ["cpid", "partner", "api"]


def test_a_line_matching_nothing_is_reported_not_guessed():
    m = FormatMatcher([AHA, ABSCBN])
    assert m.match("some unrelated line") is None
    assert m.rows_unmatched == 1


def test_lower_priority_is_tried_first_so_a_narrow_format_can_win():
    """First match wins, so a broad catch-all must not be able to shadow a
    specific format simply by being registered earlier."""
    broad = LogFormat(name="broad", regex=r"(?<cpid>\S+)", priority=99)
    narrow = LogFormat(name="narrow", regex=r"SPAccountId\s+(?<cpid>\S+)", priority=1)
    assert FormatMatcher([broad, narrow]).match(AHA_LINE).format_name == "narrow"
    # Registration order must not decide it — priority does.
    assert FormatMatcher([narrow, broad]).match(AHA_LINE).format_name == "narrow"


def test_a_hint_that_is_absent_skips_the_format_entirely():
    """The hint is a pre-filter, so a wrong one makes a format unreachable —
    which is why saving one that isn't in the sample line is refused."""
    wrong = LogFormat(name="wrong-hint", regex=r"SPAccountId\s+(?<cpid>\S+)", hint="NOT-PRESENT")
    assert FormatMatcher([wrong]).match(AHA_LINE) is None


def test_a_hint_does_not_change_which_format_matches():
    with_hint = FormatMatcher([AHA, ABSCBN]).match(AHA_LINE)
    without = FormatMatcher(
        [LogFormat(name="aha", regex=AHA.regex), LogFormat(name="abscbn", regex=ABSCBN.regex)]
    ).match(AHA_LINE)
    assert with_hint.format_name == without.format_name
    assert with_hint.fields == without.fields


def test_the_last_matching_format_is_tried_first_next_time():
    """What keeps hundreds of formats affordable: a run of same-shape rows costs
    one attempt each rather than a walk through the library."""
    attempts = {"n": 0}

    class Counting(LogFormat):
        def __post_init__(self):
            super().__post_init__()
            inner = self.compiled

            class Wrapper:
                groupindex = inner.groupindex

                def search(self, s):
                    attempts["n"] += 1
                    return inner.search(s)

            self.compiled = Wrapper()

    m = FormatMatcher(
        [
            Counting(name="a", regex=r"NEVER-MATCHES-(?<cpid>\S+)"),
            Counting(name="b", regex=r"SPAccountId\s+(?<cpid>\S+)"),
        ]
    )
    m.match(AHA_LINE)  # walks past "a" to reach "b"
    first_round = attempts["n"]
    attempts["n"] = 0
    for i in range(10):
        m.match(f"{AHA_LINE} {i}")
    assert first_round == 2  # tried both
    assert attempts["n"] == 10  # then exactly one attempt per row


def test_fast_message_cache_bypasses_regex_search():
    """Identical repeated messages hit the cache, calling search() only once."""
    attempts = {"n": 0}

    class Counting(LogFormat):
        def __post_init__(self):
            super().__post_init__()
            inner = self.compiled

            class Wrapper:
                groupindex = inner.groupindex

                def search(self, s):
                    attempts["n"] += 1
                    return inner.search(s)

            self.compiled = Wrapper()

    m = FormatMatcher([Counting(name="b", regex=r"SPAccountId\s+(?<cpid>\S+)")])
    for _ in range(10):
        m.match(AHA_LINE)
    assert attempts["n"] == 1  # 1 regex search, 9 cache hits
    assert m.match_counts["b"] == 10


def test_coverage_counts_rows_per_format():
    m = FormatMatcher([AHA, ABSCBN])
    for _ in range(3):
        m.match(AHA_LINE)
    m.match(ABS_LINE)
    assert m.coverage() == [
        {"format": "aha", "rows": 3},
        {"format": "abscbn", "rows": 1},
    ]


def test_a_format_that_never_matches_shows_as_zero():
    """The visible symptom of a broken regex — otherwise it just looks like a
    lower overall match rate."""
    dead = LogFormat(name="dead", regex=r"WILL-NEVER-APPEAR-(?<cpid>\S+)")
    m = FormatMatcher([AHA, dead])
    m.match(AHA_LINE)
    assert {"format": "dead", "rows": 0} in m.coverage()


def test_a_field_no_format_defines_is_rejected():
    with pytest.raises(AggregationError, match="no log format defines"):
        validate_formats([AHA, ABSCBN], group_by=["partner"], unique_fields=["nope"])


def test_a_field_only_some_formats_define_is_allowed():
    """Formats legitimately differ: rows from one that lacks the field get an
    empty value rather than the whole spec being refused."""
    partial = LogFormat(name="partial", regex=r"only-(?<cpid>\S+)")
    validate_formats([AHA, partial], group_by=["partner"], unique_fields=["cpid"])


def test_grouping_by_the_counted_field_is_still_rejected():
    with pytest.raises(AggregationError, match="both grouped by and counted"):
        validate_formats([AHA], group_by=["cpid"], unique_fields=["cpid"])


def test_an_empty_library_is_an_error_not_a_silent_zero_match():
    with pytest.raises(AggregationError, match="no log formats"):
        FormatMatcher([])


def test_an_invalid_regex_is_reported_when_the_format_is_built():
    with pytest.raises(AggregationError, match="invalid regex"):
        LogFormat(name="bad", regex="(unclosed")


def test_dotnet_style_named_groups_work_here_too():
    fmt = LogFormat(name="dotnet", regex=r"id=(?<thing>\d+)")
    assert FormatMatcher([fmt]).match("id=42").fields == {"thing": "42"}
