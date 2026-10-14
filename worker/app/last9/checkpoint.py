"""Checkpoint model for resumable jobs (§2.9).

Granularity is one chunk: a checkpoint is advanced only after a chunk's rows are
durably written. ``completed_chunks`` doubles as the index of the next chunk to
process, so resume is "skip the first N chunks". A mid-chunk crash leaves the
checkpoint pointing at the start of the incomplete chunk, which is replayed in
full — and because chunks are non-overlapping, that produces no duplicates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Checkpoint:
    completed_chunks: int = 0
    rows_written: int = 0
    current_chunk_start: int | None = None
    next_chunk_start: int | None = (
        None  # exact epoch to resume from; supports adaptive chunk sizing
    )
    # ID batches abandoned after a 400 that would not clear. Carried here rather
    # than in a local so it survives a resume and reaches the job row: an output
    # short a whole batch of accounts must never finish as a clean "completed".
    skipped_batches: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Checkpoint:
        if not data:
            return cls()
        return cls(
            completed_chunks=int(data.get("completed_chunks", 0)),
            rows_written=int(data.get("rows_written", 0)),
            current_chunk_start=data.get("current_chunk_start"),
            next_chunk_start=data.get("next_chunk_start"),
            skipped_batches=int(data.get("skipped_batches", 0)),
        )

    def advance(
        self, *, chunk_index: int, chunk_start: int, chunk_end: int, rows_delta: int
    ) -> None:
        """Record that the chunk at ``chunk_index`` is fully written.

        ``completed_chunks`` becomes ``chunk_index + 1`` (the next chunk to run).
        ``next_chunk_start`` is ``chunk_end`` so resume works even when chunk
        sizes varied within a run (adaptive sizing).
        """
        self.completed_chunks = chunk_index + 1
        self.rows_written += rows_delta
        self.current_chunk_start = chunk_start
        self.next_chunk_start = chunk_end
