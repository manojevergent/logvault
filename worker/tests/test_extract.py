"""Integration tests for the extraction orchestration: chunks × batches,
per-chunk checkpointing, resume, phrases-only single pass, and bad-batch skip."""

from __future__ import annotations

import json

from app.last9.checkpoint import Checkpoint
from app.last9.client import LogRow
from app.last9.errors import TransientBadRequestError
from app.last9.extract import ExtractionSpec, iter_extraction, plan_extraction

HOUR = 3600


class FakeClient:
    """Records iter_rows calls; yields a fixed number of rows, can fail a batch."""

    def __init__(self, rows_per_call: int = 1, fail_pattern: str | None = None) -> None:
        self.calls: list[dict] = []
        self.rows_per_call = rows_per_call
        self.fail_pattern = fail_pattern

    def iter_rows(self, *, index, region, start, end, pipeline, limit):
        self.calls.append({"start": start, "end": end, "pipeline": pipeline})
        blob = json.dumps(pipeline)
        if self.fail_pattern and self.fail_pattern in blob:
            raise TransientBadRequestError("simulated persistent 400")
        for i in range(self.rows_per_call):
            yield LogRow(timestamp=str(start + i), message=f"{start}:{i}", raw="")


def base_spec(**kw) -> ExtractionSpec:
    defaults = {
        "region": "ap-southeast-1",
        "index": "physical_index:UMServices",
        "start_epoch": 0,
        "end_epoch": 3 * HOUR,
        "phrases": ["GetEntitlements"],
        "ids": [],
        "chunk_hours": 1,
        "id_batch_size": 100,
    }
    defaults.update(kw)
    return ExtractionSpec(**defaults)


def test_plan_counts_chunks_batches_requests():
    spec = base_spec(ids=[f"id{i}" for i in range(250)])
    plan = plan_extraction(spec)
    assert plan.total_chunks == 3
    assert plan.total_id_batches == 3
    assert plan.total_requests == 9  # 3 chunks × 3 batches


def test_plan_phrases_only_is_one_pass_per_chunk():
    plan = plan_extraction(base_spec(ids=[]))
    assert plan.total_id_batches == 0
    assert plan.total_requests == 3  # one pass per chunk


def test_phrases_only_makes_single_pass_per_chunk_without_regex():
    client = FakeClient(rows_per_call=2)
    rows = list(iter_extraction(client, base_spec(ids=[])))
    assert len(client.calls) == 3  # 3 chunks, 1 batch each
    assert len(rows) == 6
    # No regex clause when there are no IDs.
    assert "$regex" not in json.dumps(client.calls[0]["pipeline"])


def test_ids_produce_one_request_per_batch_per_chunk():
    client = FakeClient(rows_per_call=1)
    spec = base_spec(ids=[f"id{i}" for i in range(150)], id_batch_size=100)
    list(iter_extraction(client, spec))
    assert len(client.calls) == 6  # 3 chunks × 2 batches
    assert "$regex" in json.dumps(client.calls[0]["pipeline"])


def test_checkpoint_advances_per_chunk():
    client = FakeClient(rows_per_call=4)
    seen: list[tuple[int, int]] = []

    def on_complete(cp: Checkpoint, rows_in_chunk: int) -> float | None:
        # The callback also gets the chunk's row count and may return a new chunk
        # size (adaptive sizing); returning None keeps the current one.
        seen.append((cp.completed_chunks, cp.rows_written))
        return None

    list(iter_extraction(client, base_spec(), on_chunk_complete=on_complete))
    # 3 chunks, 4 rows each, cumulative
    assert seen == [(1, 4), (2, 8), (3, 12)]


def test_resume_skips_completed_chunks():
    client = FakeClient(rows_per_call=1)
    # Resume seeks to the saved epoch rather than counting chunks, so a run whose
    # chunk size changed mid-flight still restarts in exactly the right place.
    cp = Checkpoint(completed_chunks=2, rows_written=99, next_chunk_start=2 * HOUR)
    rows = list(iter_extraction(client, base_spec(), checkpoint=cp))

    # Only the final chunk (index 2) runs.
    assert len(client.calls) == 1
    assert client.calls[0]["start"] == 2 * HOUR
    assert len(rows) == 1
    # rows_written accumulates onto the restored value.
    assert cp.completed_chunks == 3
    assert cp.rows_written == 100


def test_bad_batch_is_skipped_but_others_run():
    # Fail only the batch containing "BAD"; the good batch still yields.
    client = FakeClient(rows_per_call=1, fail_pattern="BAD")
    spec = base_spec(
        phrases=[], ids=["GOOD-1", "BAD-1"], id_batch_size=1, end_epoch=HOUR  # 1 chunk, 2 batches
    )
    rows = list(iter_extraction(client, spec))
    # 2 batch requests; one failed and was skipped, one produced a row.
    assert len(client.calls) == 2
    assert len(rows) == 1


def test_a_skipped_batch_is_counted_not_silently_dropped():
    """A batch that keeps 400ing loses ~one batch worth of IDs from the output.

    It used to `continue` with no counter and no event, so a job missing a whole
    batch of accounts still finished as a clean "completed" with a download link
    — the CSV was simply short, and nothing anywhere said so.
    """
    client = FakeClient(rows_per_call=1, fail_pattern="BAD")
    spec = base_spec(phrases=[], ids=["GOOD-1", "BAD-1"], id_batch_size=1, end_epoch=HOUR)

    cp = Checkpoint()
    rows = list(iter_extraction(client, spec, checkpoint=cp))

    assert len(rows) == 1
    assert cp.skipped_batches == 1, "the dropped batch has to be recorded somewhere"


def test_skipped_batch_count_survives_a_resume():
    """The count rides the checkpoint, so a resumed job still reports its gaps."""
    restored = Checkpoint.from_dict({"completed_chunks": 0, "skipped_batches": 2})
    assert restored.skipped_batches == 2


def test_bad_batch_propagates_when_skip_disabled():
    client = FakeClient(rows_per_call=1, fail_pattern="BAD")
    spec = base_spec(phrases=[], ids=["BAD-1"], id_batch_size=1, end_epoch=HOUR)
    try:
        list(iter_extraction(client, spec, skip_bad_batches=False))
        raise AssertionError("expected TransientBadRequestError")
    except TransientBadRequestError:
        pass
