import pytest

from app.last9.batching import batch_ids, dedupe_preserve_order


def test_dedupe_preserves_first_seen_order():
    assert dedupe_preserve_order(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_dedupe_strips_and_drops_blanks():
    assert dedupe_preserve_order(["  x  ", "", "   ", "y"]) == ["x", "y"]


def test_batches_respect_size():
    ids = [f"id{i}" for i in range(250)]
    batches = batch_ids(ids, batch_size=100)
    assert [len(b) for b in batches] == [100, 100, 50]
    assert batches[0][0] == "id0"
    assert batches[-1][-1] == "id249"


def test_batching_dedupes_first():
    batches = batch_ids(["a", "a", "b"], batch_size=100)
    assert batches == [["a", "b"]]


def test_empty_ids_no_batches():
    assert batch_ids([]) == []


def test_invalid_batch_size():
    with pytest.raises(ValueError):
        batch_ids(["a"], batch_size=0)
