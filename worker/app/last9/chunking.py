"""Time-range chunking (§2.9).

Split the full range into N-hour windows so each request stays small. Windows
are **non-overlapping and half-open** ``[start, end)`` and contiguous (each
window's end is the next window's start), so a job killed mid-chunk replays only
that chunk with no duplicate rows across chunks.
"""

from __future__ import annotations

from .constants import DEFAULT_CHUNK_HOURS


def make_chunks(
    start_epoch: int, end_epoch: int, chunk_hours: float = DEFAULT_CHUNK_HOURS
) -> list[tuple[int, int]]:
    """Return contiguous half-open ``[start, end)`` windows covering the range.

    The final window is truncated to ``end_epoch``. Raises if the range or chunk
    size is non-positive.
    """
    if end_epoch <= start_epoch:
        raise ValueError("end_epoch must be greater than start_epoch")
    if chunk_hours <= 0:
        raise ValueError("chunk_hours must be positive")

    step = int(chunk_hours * 3600)
    chunks: list[tuple[int, int]] = []
    cursor = start_epoch
    while cursor < end_epoch:
        nxt = min(cursor + step, end_epoch)
        chunks.append((cursor, nxt))
        cursor = nxt
    return chunks


def count_chunks(start_epoch: int, end_epoch: int, chunk_hours: float = DEFAULT_CHUNK_HOURS) -> int:
    """Number of chunks (for UI estimates). At 1h chunks a month is ~720 — cheap
    to just build and count."""
    return len(make_chunks(start_epoch, end_epoch, chunk_hours))


# A preview that opens a single hour can miss a sparse stream entirely (2 rows an
# hour means a 7-day filter looks broken). Sample a few of the newest chunks
# instead; the row cap still bounds the work.
PREVIEW_CHUNKS = 3


def preview_window_start(
    start_epoch: int,
    end_epoch: int,
    chunk_hours: float = DEFAULT_CHUNK_HOURS,
    max_chunks: int = PREVIEW_CHUNKS,
) -> int:
    """Where a filter-test preview begins: the last few chunks of the window.

    A preview runs only a slice of the selected window. The *first* chunk of a
    long window is the oldest hour — the least useful sample, and often empty
    even when the window is full of matching rows. The newest chunks are what
    the operator is about to extract.
    """
    if chunk_hours <= 0 or end_epoch <= start_epoch:
        return start_epoch
    span = int(chunk_hours * 3600) * max(1, max_chunks)
    return max(start_epoch, end_epoch - span)
