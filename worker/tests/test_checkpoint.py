from app.last9.checkpoint import Checkpoint


def test_default_checkpoint_is_zeroed():
    cp = Checkpoint()
    assert cp.completed_chunks == 0
    assert cp.rows_written == 0
    assert cp.current_chunk_start is None


def test_advance_sets_next_chunk_index_and_accumulates_rows():
    cp = Checkpoint()
    cp.advance(chunk_index=0, chunk_start=1000, chunk_end=4600, rows_delta=150)
    assert cp.completed_chunks == 1
    assert cp.rows_written == 150
    assert cp.current_chunk_start == 1000

    cp.advance(chunk_index=1, chunk_start=4600, chunk_end=8200, rows_delta=50)
    assert cp.completed_chunks == 2
    assert cp.rows_written == 200


def test_roundtrip_dict():
    cp = Checkpoint(completed_chunks=3, rows_written=999, current_chunk_start=12345)
    restored = Checkpoint.from_dict(cp.to_dict())
    assert restored == cp


def test_from_dict_handles_none_and_partial():
    assert Checkpoint.from_dict(None) == Checkpoint()
    assert Checkpoint.from_dict({"completed_chunks": 2}).completed_chunks == 2
