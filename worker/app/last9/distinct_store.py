"""Disk-backed exact distinct-value counting.

The in-memory alternative (a Python ``set`` per group/field) fails two ways at
extraction scale: RAM grows with total distinct cardinality, and persisting it
for checkpoint/resume means re-serializing every value seen so far into the
job row after every chunk. At ~2M distinct values that is ~40 MB of JSON
written 24x/day, per job.

SQLite fixes both. Distinct-ness is a ``PRIMARY KEY`` and ``INSERT OR IGNORE``;
RAM stays flat at any cardinality, the file *is* the checkpoint (nothing to
serialize), and — because insertion is idempotent — replaying a partially
processed chunk after a pause or crash cannot inflate a count.

It also makes the month-end rollup nearly free: merging a day into a month is
``ATTACH`` + ``INSERT OR IGNORE ... SELECT``, which yields a true cross-day
distinct count. Summing per-day counts would count anything recurring across
days once per day it appeared.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from collections.abc import Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS distinct_values (
  group_key TEXT NOT NULL,
  field     TEXT NOT NULL,
  value     TEXT NOT NULL,
  n         INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (group_key, field, value)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS meta (
  k TEXT PRIMARY KEY,
  v INTEGER NOT NULL
) WITHOUT ROWID;
"""

# Marks the last chunk whose buffer reached the file. Written in the SAME
# transaction as that chunk's rows, so the two can never disagree — which is what
# lets a replayed chunk be recognised and dropped instead of counted twice.
_LAST_CHUNK = "last_chunk_committed"
# WITHOUT ROWID: the whole row is the key, so a rowid table would store every
# byte twice (once in the table, once in the unique index).

# ponytail: group_key is stored inline on every row, so a long key repeats once
# per distinct value in that group. Intern it into a groups(id, key) table if
# the files get big — roughly halves them, at the cost of a join on read.


def group_key_to_text(key: tuple[str, ...]) -> str:
    return json.dumps(list(key))


def group_key_from_text(text: str) -> tuple[str, ...]:
    return tuple(json.loads(text))


class DistinctStore:
    """Per-value occurrence counts over (group_key, field), backed by a file.

    Answers both questions from one pass: how many DISTINCT values a group has
    (row count) and how many times each value OCCURRED (the ``n`` column).

    Writes are buffered and flushed at caller-chosen boundaries (one chunk, in
    the runner) so a long extraction does one batched transaction per chunk
    rather than one per row. Buffered rows are lost if the process dies before
    ``flush()`` — deliberate, because the runner replays the unfinished chunk on
    resume and nothing was committed for it.

    Replay safety needs more than that once values are counted rather than just
    recorded. Distinct-ness was idempotent on its own; addition is not. So each
    flush records the chunk it belongs to, and a flush for a chunk already on
    disk is discarded — otherwise a crash in the window between this file's
    commit and the job checkpoint's commit would silently double that chunk.
    """

    def __init__(self, path: str, fresh: bool = False) -> None:
        self.path = path
        if fresh:
            _unlink_quietly(path)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(path)
        # Durable per commit (one per chunk), not per row. Bigger page cache so
        # the btree inserts don't thrash on a large file.
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-64000")  # 64 MB
        self._conn.executescript(_SCHEMA)
        self._migrate_add_n()
        self._conn.commit()
        # Buffers hold ONE chunk's worth of work, so they are also what gets
        # thrown away when that chunk turns out to be a replay.
        self._buf: dict[tuple[str, str, str], int] = {}
        # Group keys seen so far, seeded lazily. Counting them with a GROUP BY
        # re-scanned every distinct value — millions of rows — once per chunk and
        # again per rollup merge, to produce a number that only ever grows by the
        # handful of groups a run actually has.
        self._group_keys: set[str] | None = None
        self._pending: dict[str, int] = {}
        # Free-form counters (rows_matched/rows_unmatched) live in the file too,
        # so resuming needs nothing but the path.
        self._counters: dict[str, int] = dict(self._conn.execute("SELECT k, v FROM meta"))

    def _migrate_add_n(self) -> None:
        """Add `n` to a store written before occurrence counts existed. Its rows
        keep n=0, which reads as "recorded, count unknown" rather than a wrong
        number."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(distinct_values)")}
        if "n" not in cols:
            self._conn.execute(
                "ALTER TABLE distinct_values ADD COLUMN n INTEGER NOT NULL DEFAULT 0"
            )

    def counter(self, k: str) -> int:
        return self._counters.get(k, 0) + self._pending.get(k, 0)

    def bump(self, k: str, n: int = 1) -> None:
        self._pending[k] = self._pending.get(k, 0) + n

    def add(self, key: tuple[str, ...], field: str, value: str) -> None:
        # ponytail: buffered until the chunk boundary, so peak memory is one
        # chunk's distinct values — ~43 MB per 125k of them, worst case a
        # near-unique field like session_token. Deliberately NOT flushed on a
        # size threshold: a mid-chunk flush is not idempotent, so a crash would
        # replay the chunk and re-add the committed rows (`n = n + excluded.n`),
        # inflating every occurrence count. Adaptive chunk sizing already
        # shrinks dense chunks. If a single chunk ever does blow memory, the fix
        # is to give the store a row-position marker so a replay can skip what
        # it already counted — not to flush blindly.
        group_key = group_key_to_text(key)
        if self._group_keys is not None:
            self._group_keys.add(group_key)
        row = (group_key, field, value)
        self._buf[row] = self._buf.get(row, 0) + 1

    def flush(self, chunk_index: int | None = None) -> None:
        """Commit the buffered chunk. Passing ``chunk_index`` makes the flush
        idempotent: a chunk already on disk is dropped rather than added again."""
        if chunk_index is not None and chunk_index <= self._counters.get(_LAST_CHUNK, -1):
            self._buf.clear()  # already counted before the crash — must not repeat
            self._pending.clear()
            return

        if self._buf:
            self._conn.executemany(
                "INSERT INTO distinct_values (group_key, field, value, n) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(group_key, field, value) DO UPDATE SET n = n + excluded.n",
                [(g, f, v, n) for (g, f, v), n in self._buf.items()],
            )
            self._buf.clear()
        for k, n in self._pending.items():
            self._counters[k] = self._counters.get(k, 0) + n
        self._pending.clear()
        if chunk_index is not None:
            self._counters[_LAST_CHUNK] = chunk_index
        if self._counters:
            self._conn.executemany(
                "INSERT INTO meta (k, v) VALUES (?, ?) "
                "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                list(self._counters.items()),
            )
        self._conn.commit()

    def merge_from(self, other_path: str) -> int:
        """Fold another store into this one. Returns rows newly added.

        This is what makes a monthly total exact: the union of every day's
        distinct values, deduped, rather than a sum of daily counts.
        """
        self.flush()
        # A merge introduces group keys this store never saw through add(), so
        # the memoised set no longer describes the file. Dropped rather than
        # updated: it reseeds from one DISTINCT query on next use.
        self._group_keys = None
        self._conn.execute("ATTACH DATABASE ? AS src", (other_path,))
        try:
            # Values dedupe (a customer on 10 days is still one customer) while
            # their occurrence counts add (10 days of activity is 10 days of it).
            cur = self._conn.execute(
                "INSERT INTO distinct_values (group_key, field, value, n) "
                "SELECT group_key, field, value, n FROM src.distinct_values "
                "WHERE true "  # disambiguates the following ON CONFLICT from the SELECT
                "ON CONFLICT(group_key, field, value) DO UPDATE SET n = n + excluded.n"
            )
            added = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            for k, v in self._conn.execute("SELECT k, v FROM src.meta").fetchall():
                if k != _LAST_CHUNK:  # a chunk marker is meaningless across files
                    self.bump(k, v)
            self._conn.commit()
        finally:
            self._conn.execute("DETACH DATABASE src")
        self.flush()
        return added

    def iter_value_counts(self, field: str) -> Iterator[tuple[tuple[str, ...], str, int]]:
        """Yield ``(group_key, value, occurrences)`` for one field, most frequent
        first.

        The pivot-table view. Kept per group rather than summed across groups so
        each row carries the BU (and whatever else is grouped on) it belongs to —
        without that the value alone can't be attributed to a customer.
        """
        self.flush()
        for group_key, value, n in self._conn.execute(
            "SELECT group_key, value, n FROM distinct_values WHERE field = ? "
            "ORDER BY n DESC, value",
            (field,),
        ):
            yield group_key_from_text(group_key), value, n

    def iter_groups(self) -> Iterator[tuple[tuple[str, ...], dict[str, int]]]:
        """Yield ``(group_key, {field: distinct_count})`` in key order, streaming."""
        self.flush()
        cur = self._conn.execute(
            "SELECT group_key, field, COUNT(*) FROM distinct_values "
            "GROUP BY group_key, field ORDER BY group_key, field"
        )
        current: str | None = None
        counts: dict[str, int] = {}
        for group_key, field, n in cur:
            if group_key != current:
                if current is not None:
                    yield group_key_from_text(current), counts
                current, counts = group_key, {}
            counts[field] = n
        if current is not None:
            yield group_key_from_text(current), counts

    def group_count(self) -> int:
        self.flush()
        if self._group_keys is None:
            self._group_keys = {
                row[0]
                for row in self._conn.execute("SELECT DISTINCT group_key FROM distinct_values")
            }
        return len(self._group_keys)

    def close(self) -> None:
        self.flush()
        self._conn.close()

    def __enter__(self) -> DistinctStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def store_path(storage_dir: str, job_id: int) -> str:
    return os.path.join(storage_dir, f"job_{job_id}.distinct.sqlite")


def _unlink_quietly(path: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)
