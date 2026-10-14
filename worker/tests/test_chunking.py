import pytest

from app.last9.chunking import count_chunks, make_chunks

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
