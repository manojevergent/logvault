"""ID batching (§2.6).

One giant regex with thousands of IDs is rejected by Last9's pipeline size
limit, so IDs are batched (~100 per regex) and one request is issued per batch
per time window. IDs are de-duplicated while preserving first-seen order so the
batch/request count is stable and the UI preview is accurate.
"""

from __future__ import annotations

from collections.abc import Iterable

from .constants import DEFAULT_ID_BATCH_SIZE


def dedupe_preserve_order(ids: Iterable[str]) -> list[str]:
    """De-duplicate, dropping blanks, preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in ids:
        i = raw.strip()
        if not i or i in seen:
            continue
        seen.add(i)
        out.append(i)
    return out


def batch_ids(ids: Iterable[str], batch_size: int = DEFAULT_ID_BATCH_SIZE) -> list[list[str]]:
    """De-dupe then split into batches of at most ``batch_size`` IDs."""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    cleaned = dedupe_preserve_order(ids)
    return [cleaned[i : i + batch_size] for i in range(0, len(cleaned), batch_size)]
