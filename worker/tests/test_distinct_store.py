"""DistinctStore, with emphasis on merge — the operation the month-end rollup
rests on. A bug here produces a plausible-looking number rather than an error,
so it gets tested directly rather than only through the runner."""

from __future__ import annotations

from app.last9.distinct_store import DistinctStore


def test_counts_distinct_values_not_occurrences(tmp_path):
    with DistinctStore(str(tmp_path / "a.sqlite")) as s:
        for _ in range(5):
            s.add(("india",), "spid", "1001")
        s.add(("india",), "spid", "1002")
        assert dict(s.iter_groups())[("india",)] == {"spid": 2}


def test_merge_unions_values_rather_than_adding_counts(tmp_path):
    """The reason monthly totals cannot be a sum of daily totals: spid 1001 is
    present on both days, so the correct month total is 3 — not 2 + 2 = 4."""
    day1 = tmp_path / "day1.sqlite"
    day2 = tmp_path / "day2.sqlite"
    with DistinctStore(str(day1)) as s:
        s.add(("india",), "spid", "1001")
        s.add(("india",), "spid", "1002")
    with DistinctStore(str(day2)) as s:
        s.add(("india",), "spid", "1001")  # same customer, seen again the next day
        s.add(("india",), "spid", "1003")

    with DistinctStore(str(tmp_path / "month.sqlite")) as month:
        month.merge_from(str(day1))
        month.merge_from(str(day2))
        assert dict(month.iter_groups())[("india",)] == {"spid": 3}


def test_merge_keeps_groups_separate(tmp_path):
    day1 = tmp_path / "day1.sqlite"
    with DistinctStore(str(day1)) as s:
        s.add(("india", "getEntitlements"), "spid", "1001")
        s.add(("uae", "getEntitlements"), "spid", "1001")  # same spid, different customer

    with DistinctStore(str(tmp_path / "month.sqlite")) as month:
        month.merge_from(str(day1))
        groups = dict(month.iter_groups())
    assert groups[("india", "getEntitlements")] == {"spid": 1}
    assert groups[("uae", "getEntitlements")] == {"spid": 1}


def test_merging_the_same_day_twice_is_idempotent(tmp_path):
    day1 = tmp_path / "day1.sqlite"
    with DistinctStore(str(day1)) as s:
        s.add(("india",), "spid", "1001")
        s.add(("india",), "spid", "1002")

    with DistinctStore(str(tmp_path / "month.sqlite")) as month:
        month.merge_from(str(day1))
        month.merge_from(str(day1))
        assert dict(month.iter_groups())[("india",)] == {"spid": 2}


def test_counters_survive_reopen_and_sum_across_merges(tmp_path):
    day1 = tmp_path / "day1.sqlite"
    with DistinctStore(str(day1)) as s:
        s.bump("rows_matched", 10)

    with DistinctStore(str(day1)) as s:  # reopened
        assert s.counter("rows_matched") == 10

    with DistinctStore(str(tmp_path / "month.sqlite")) as month:
        month.merge_from(str(day1))
        month.merge_from(str(day1))
        # Row tallies add, unlike the values themselves.
        assert month.counter("rows_matched") == 20


def test_fresh_wipes_an_existing_file(tmp_path):
    path = tmp_path / "a.sqlite"
    with DistinctStore(str(path)) as s:
        s.add(("india",), "spid", "1001")
        s.bump("rows_matched", 1)

    with DistinctStore(str(path), fresh=True) as s:
        assert list(s.iter_groups()) == []
        assert s.counter("rows_matched") == 0


def test_unflushed_buffer_is_lost_but_flushed_data_survives(tmp_path):
    """Buffered rows die with the process on purpose — the runner replays the
    unfinished chunk, and re-inserting is a no-op."""
    path = tmp_path / "a.sqlite"
    s = DistinctStore(str(path))
    s.add(("india",), "spid", "1001")
    s.flush()
    s.add(("india",), "spid", "1002")  # never flushed
    s._conn.close()  # simulate an abrupt death

    with DistinctStore(str(path)) as reopened:
        assert dict(reopened.iter_groups())[("india",)] == {"spid": 1}


def test_counts_occurrences_as_well_as_distinct_values(tmp_path):
    with DistinctStore(str(tmp_path / "a.sqlite")) as s:
        for _ in range(5):
            s.add(("india",), "spid", "1001")
        s.add(("india",), "spid", "1002")
        # Distinct: 2 values. Occurrences: 1001 five times, 1002 once.
        assert dict(s.iter_groups())[("india",)] == {"spid": 2}
        assert list(s.iter_value_counts("spid")) == [
            (("india",), "1001", 5),
            (("india",), "1002", 1),
        ]


def test_value_counts_are_ordered_most_frequent_first(tmp_path):
    with DistinctStore(str(tmp_path / "a.sqlite")) as s:
        for value, times in (("low", 1), ("high", 9), ("mid", 4)):
            for _ in range(times):
                s.add(("india",), "spid", value)
        assert [v for _, v, _ in s.iter_value_counts("spid")] == ["high", "mid", "low"]


def test_value_counts_keep_their_group(tmp_path):
    """Each row must carry the BU it belongs to; summing across groups would
    make the value impossible to attribute to a customer."""
    with DistinctStore(str(tmp_path / "a.sqlite")) as s:
        s.add(("india",), "spid", "1001")
        s.add(("india",), "spid", "1001")
        s.add(("uae",), "spid", "1001")
        assert list(s.iter_value_counts("spid")) == [
            (("india",), "1001", 2),
            (("uae",), "1001", 1),
        ]


def test_replaying_a_committed_chunk_does_not_double_its_counts(tmp_path):
    """Distinct-ness was idempotent on its own; addition is not. A crash between
    this file's commit and the job checkpoint's commit replays a chunk that is
    already on disk — it must be dropped, not added again."""
    path = tmp_path / "a.sqlite"
    with DistinctStore(str(path)) as s:
        s.add(("india",), "spid", "1001")
        s.add(("india",), "spid", "1001")
        s.bump("rows_matched", 2)
        s.flush(chunk_index=0)
        assert list(s.iter_value_counts("spid")) == [(("india",), "1001", 2)]

    # Resume replays chunk 0 because the checkpoint never recorded it.
    with DistinctStore(str(path)) as s:
        s.add(("india",), "spid", "1001")
        s.add(("india",), "spid", "1001")
        s.bump("rows_matched", 2)
        s.flush(chunk_index=0)
        assert list(s.iter_value_counts("spid")) == [(("india",), "1001", 2)]  # not 4
        assert s.counter("rows_matched") == 2  # not 4


def test_a_later_chunk_still_accumulates_after_a_replayed_one(tmp_path):
    path = tmp_path / "a.sqlite"
    with DistinctStore(str(path)) as s:
        s.add(("india",), "spid", "1001")
        s.flush(chunk_index=0)
        s.add(("india",), "spid", "1001")
        s.flush(chunk_index=0)  # replay, dropped
        s.add(("india",), "spid", "1001")
        s.flush(chunk_index=1)  # genuinely new chunk
        assert list(s.iter_value_counts("spid")) == [(("india",), "1001", 2)]


def test_merge_adds_occurrence_counts_while_values_dedupe(tmp_path):
    """A customer on two days is one customer, but two days of activity."""
    day1, day2 = tmp_path / "d1.sqlite", tmp_path / "d2.sqlite"
    with DistinctStore(str(day1)) as s:
        s.add(("india",), "spid", "1001")
        s.add(("india",), "spid", "1001")
    with DistinctStore(str(day2)) as s:
        s.add(("india",), "spid", "1001")
        s.add(("india",), "spid", "1002")

    with DistinctStore(str(tmp_path / "month.sqlite")) as month:
        month.merge_from(str(day1))
        month.merge_from(str(day2))
        assert dict(month.iter_groups())[("india",)] == {"spid": 2}  # distinct
        assert list(month.iter_value_counts("spid")) == [
            (("india",), "1001", 3),
            (("india",), "1002", 1),
        ]


def test_store_written_before_counts_existed_still_opens(tmp_path):
    """Old files lack the n column; they read as count-unknown rather than
    failing or reporting a wrong number."""
    import sqlite3

    path = tmp_path / "old.sqlite"
    con = sqlite3.connect(str(path))
    con.executescript(
        "CREATE TABLE distinct_values (group_key TEXT NOT NULL, field TEXT NOT NULL,"
        " value TEXT NOT NULL, PRIMARY KEY (group_key, field, value)) WITHOUT ROWID;"
        "CREATE TABLE meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL) WITHOUT ROWID;"
    )
    con.execute("INSERT INTO distinct_values VALUES ('[\"india\"]', 'spid', '1001')")
    con.commit()
    con.close()

    with DistinctStore(str(path)) as s:
        assert dict(s.iter_groups())[("india",)] == {"spid": 1}
        assert list(s.iter_value_counts("spid")) == [(("india",), "1001", 0)]
