import pytest

from app.last9.chunking import PREVIEW_CHUNKS, count_chunks, make_chunks, preview_window_start

HOUR = 3600


def test_even_split_is_contiguous_and_non_overlapping():
    chunks = make_chunks(0, 3 * HOUR, chunk_hours=1)
    assert chunks == [(0, HOUR), (HOUR, 2 * HOUR), (2 * HOUR, 3 * HOUR)]
    # each window's end is the next window's start (no overlap, no gap)
    for (_, end), (nxt_start, _) in zip(chunks, chunks[1:], strict=False):
        assert end == nxt_start


def test_final_chunk_is_truncated():
    chunks = make_chunks(0, int(2.5 * HOUR), chunk_hours=1)
    assert chunks == [(0, HOUR), (HOUR, 2 * HOUR), (2 * HOUR, int(2.5 * HOUR))]


def test_single_chunk_when_range_smaller_than_step():
    assert make_chunks(100, 200, chunk_hours=1) == [(100, 200)]


def test_preview_samples_only_the_newest_chunks_of_a_long_window():
    week = 7 * 24 * HOUR
    start = preview_window_start(0, week, chunk_hours=1)
    assert start == week - PREVIEW_CHUNKS * HOUR
    assert make_chunks(start, week, chunk_hours=1) == [
        (week - 3 * HOUR, week - 2 * HOUR),
        (week - 2 * HOUR, week - HOUR),
        (week - HOUR, week),
    ]


def test_preview_keeps_a_window_shorter_than_the_sample():
    assert preview_window_start(0, 600, chunk_hours=1) == 0
    assert make_chunks(0, 600, chunk_hours=1) == [(0, 600)]


def test_count_matches_make():
    start, end = 1000, 1000 + 7 * HOUR + 123
    assert count_chunks(start, end, chunk_hours=2) == len(make_chunks(start, end, chunk_hours=2))


def test_invalid_ranges():
    with pytest.raises(ValueError):
        make_chunks(10, 10)
    with pytest.raises(ValueError):
        make_chunks(10, 5)
    with pytest.raises(ValueError):
        make_chunks(0, 100, chunk_hours=0)
