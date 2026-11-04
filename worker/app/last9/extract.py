"""High-level extraction orchestration.

Ties together chunking (§2.9), ID batching (§2.6), the query client (§2.8), and
checkpoint/resume. The Celery task (Phase 4) drives this: it iterates the rows,
streams them to the output, and after each chunk completes it persists the
checkpoint via ``on_chunk_complete`` and durably flushes the output.

Resume is chunk-granular: pass the saved :class:`Checkpoint` and the first
``completed_chunks`` chunks are skipped. A mid-chunk crash replays only that
chunk (non-overlapping windows => no duplicates).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from .batching import batch_ids
from .checkpoint import Checkpoint
from .chunking import count_chunks
from .client import Last9Client, LogRow
from .constants import DEFAULT_CHUNK_HOURS, DEFAULT_ID_BATCH_SIZE, DEFAULT_LIMIT
from .errors import TransientBadRequestError
from .pipeline import build_filter_pipeline


@dataclass
class ExtractionSpec:
    region: str
    index: str  # full index string, e.g. "physical_index:UMServices"
    start_epoch: int
    end_epoch: int
    phrases: list[str] = field(default_factory=list)
    # Quoted phrases the user wants adjacent, e.g. "API : 502". Sent as regexes;
    # `$contains` is word-based and would match a stray "502" anywhere.
    exact_phrases: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    chunk_hours: float = DEFAULT_CHUNK_HOURS
    id_batch_size: int = DEFAULT_ID_BATCH_SIZE
    limit: int = DEFAULT_LIMIT


@dataclass
class ExtractionPlan:
    total_chunks: int
    total_id_batches: int
    total_requests: int  # lower bound: one request per (chunk × batch) before paging


def plan_extraction(spec: ExtractionSpec) -> ExtractionPlan:
    """Pre-run estimate for the wizard (§5.1) — counts, not data."""
    chunks = count_chunks(spec.start_epoch, spec.end_epoch, spec.chunk_hours)
    batches = batch_ids(spec.ids, spec.id_batch_size)
    n_batches = len(batches) if batches else 1  # phrases-only => a single pass
    return ExtractionPlan(
        total_chunks=chunks,
        total_id_batches=len(batches),
        total_requests=chunks * n_batches,
    )


def iter_extraction(
    client: Last9Client,
    spec: ExtractionSpec,
    *,
    checkpoint: Checkpoint | None = None,
    on_chunk_complete: Callable[[Checkpoint, int], float | None] | None = None,
    skip_bad_batches: bool = True,
) -> Iterator[LogRow]:
    """Yield every matching row across the range, advancing the checkpoint per chunk.

    For each chunk, every ID batch is queried in turn (phrases-only jobs make a
    single pass with no regex clause). After all batches for a chunk are
    streamed, the checkpoint is advanced and ``on_chunk_complete`` is invoked so
    the caller can flush output + persist progress atomically.

    ``on_chunk_complete(cp, rows_in_chunk)`` may return a new ``chunk_hours``
    float to resize the next chunk (adaptive sizing). Return ``None`` to keep
    the current size.

    Chunks are built lazily so chunk_hours can change between iterations.
    Resume uses ``cp.next_chunk_start`` for an exact epoch seek, making
    adaptive sizing safe across pause/resume cycles.
    """
    id_batches = batch_ids(spec.ids, spec.id_batch_size)
    # `None` batch => phrases-only request (no regex clause).
    batch_plan: list[list[str] | None] = list(id_batches) if id_batches else [None]

    cp = checkpoint or Checkpoint()
    # Resume: seek directly to saved epoch so chunk_hours changes don't corrupt position.
    cursor = (
        cp.next_chunk_start
        if cp.next_chunk_start is not None and cp.completed_chunks > 0
        else spec.start_epoch
    )
    chunk_index = cp.completed_chunks
    chunk_hours = spec.chunk_hours

    while cursor < spec.end_epoch:
        chunk_start = cursor
        chunk_end = min(cursor + int(chunk_hours * 3600), spec.end_epoch)

        rows_in_chunk = 0
        for batch in batch_plan:
            pipeline = build_filter_pipeline(spec.phrases, batch, exact_phrases=spec.exact_phrases)
            try:
                for row in client.iter_rows(
                    index=spec.index,
                    region=spec.region,
                    start=chunk_start,
                    end=chunk_end,
                    pipeline=pipeline,
                    limit=spec.limit,
                ):
                    rows_in_chunk += 1
                    yield row
            except TransientBadRequestError:
                if not skip_bad_batches:
                    raise
                # §2.10 — a 400 that won't clear: skip this batch, keep going.
                # Counted, because skipping drops roughly `id_batch_size` accounts
                # from the output and the caller has to be able to say so.
                cp.skipped_batches += 1
                continue

        cp.advance(
            chunk_index=chunk_index,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
            rows_delta=rows_in_chunk,
        )
        if on_chunk_complete:
            new_hours = on_chunk_complete(cp, rows_in_chunk)
            if new_hours is not None:
                chunk_hours = new_hours

        cursor = chunk_end
        chunk_index += 1


__all__ = [
    "ExtractionPlan",
    "ExtractionSpec",
    "iter_extraction",
    "plan_extraction",
]
