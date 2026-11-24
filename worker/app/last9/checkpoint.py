"""Checkpoint model for resumable jobs (§2.9).

Granularity is one chunk: a checkpoint is advanced only after a chunk's rows are
durably written. ``completed_chunks`` doubles as the index of the next chunk to
process, so resume is "skip the first N chunks". A mid-chunk crash leaves the
checkpoint pointing at the start of the incomplete chunk, which is replayed in
full — and because chunks are non-overlapping, that produces no duplicates.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

# Bump when the persisted shape changes incompatibly. A checkpoint written by a
# newer worker is refused rather than guessed at.
SUPPORTED_VERSION = 1


def validate(
    data: Any,
    *,
    job_id: int,
    artifact_path: str | None = None,
    exists=os.path.exists,
    size_of=os.path.getsize,
) -> tuple["Checkpoint", str | None]:
    """Return ``(checkpoint, reason)``; ``reason is None`` means trusted.

    A checkpoint is never trusted merely because the file exists. Anything that
    cannot be proven consistent with this job restarts at chunk 0 instead, which
    is always safe: chunks are non-overlapping, so replay produces no duplicates
    while a bad offset can silently drop or duplicate rows.
    """
    if not data:
        return Checkpoint(), "missing"
    if not isinstance(data, dict):
        return Checkpoint(), "not a mapping"

    version = data.get("checkpoint_version")
    if version is not None:
        try:
            if int(version) > SUPPORTED_VERSION:
                return Checkpoint(), f"unsupported version {version}"
        except (TypeError, ValueError):
            return Checkpoint(), f"non-numeric version {version!r}"

    stored_job = data.get("job_id")
    if stored_job is not None:
        try:
            if int(stored_job) != int(job_id):
                return Checkpoint(), f"job id mismatch ({stored_job})"
        except (TypeError, ValueError):
            return Checkpoint(), f"invalid job id {stored_job!r}"

    try:
        completed = int(data.get("completed_chunks", 0))
        rows = int(data.get("rows_written", 0))
    except (TypeError, ValueError):
        return Checkpoint(), "non-numeric progress"
    if completed < 0 or rows < 0:
        return Checkpoint(), "negative progress"

    nxt = data.get("next_chunk_start")
    if nxt is not None and not isinstance(nxt, (int, float)):
        return Checkpoint(), "invalid resume offset"
    if completed > 0 and nxt is None:
        return Checkpoint(), "progress without resume offset"
    if completed == 0:
        return Checkpoint(), "zero completed chunks"

    # When the job has a publication pointer, the file it names must still be
    # there and non-empty: a truncated or deleted artifact cannot be appended
    # to safely. A job with no pointer yet has nothing to validate against, so
    # the offset is all we can check.
    if artifact_path is not None:
        try:
            if not exists(artifact_path):
                return Checkpoint(), "artifact missing"
            if size_of(artifact_path) <= 0:
                return Checkpoint(), "artifact empty"
        except OSError:
            return Checkpoint(), "artifact unreadable"

    return Checkpoint.from_dict(data), None


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
