"""Match a log line against a library of named parse patterns.

A single regex per job only works when a job's rows all share one shape. With
many log formats in one stream, each row has to be tried against the library
until something fits.

Done naively that is O(rows x formats) — 25M rows against 200 formats is 5
billion regex attempts, which never finishes. Two things make it affordable, and
neither needs configuration to pay off:

* **Last match first.** Log streams are heavily clustered: consecutive rows are
  almost always the same format. Trying the previous winner first turns the
  common case into a single attempt.
* **Literal hints.** A format may declare a substring every one of its lines
  contains. ``in`` on a str is a memchr-backed scan, far cheaper than running a
  regex, so a hint rules a format out long before backtracking can start.

Neither changes which format matches — only how quickly the right one is found.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from .patterns import AggregationError, compile_pattern


@dataclass
class LogFormat:
    """One named pattern. ``hint`` is optional; without it the regex always runs."""

    name: str
    regex: str
    hint: str | None = None
    priority: int = 100
    compiled: re.Pattern[str] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.compiled is None:
            self.compiled = compile_pattern(self.regex)


@dataclass
class FormatMatch:
    format_name: str
    fields: dict[str, str]


class FormatMatcher:
    """Tries formats in priority order and returns the first that matches.

    Not thread-safe: it carries the last-match cursor. One per job, which is how
    the runner uses it.
    """

    def __init__(self, formats: list[LogFormat]) -> None:
        if not formats:
            raise AggregationError("no log formats to match against")
        # Stable within a priority so the order a user sees is the order used.
        self._formats = sorted(formats, key=lambda f: (f.priority, f.name))
        self._last = 0
        self.match_counts: dict[str, int] = {f.name: 0 for f in self._formats}
        self.rows_unmatched = 0
        # Fast LRU match cache: avoids re-executing regex on repeated log messages
        self._cache: dict[str, FormatMatch | None] = {}

    @property
    def formats(self) -> list[LogFormat]:
        return list(self._formats)

    def field_names(self) -> set[str]:
        """Every named group any format defines — the fields a spec may use."""
        names: set[str] = set()
        for f in self._formats:
            names.update(f.compiled.groupindex)
        return names

    def field_names_ordered(self) -> list[str]:
        """Every named group, deduped in format-priority then definition order.

        The parse-only CSV needs a fixed header before the first row arrives;
        a set would make that column order depend on hash seeds.
        """
        names: list[str] = []
        for f in self._formats:
            for name in f.compiled.groupindex:
                if name not in names:
                    names.append(name)
        return names

    def match(self, message: str) -> FormatMatch | None:
        if message in self._cache:
            hit = self._cache[message]
            if hit is not None:
                self.match_counts[hit.format_name] += 1
            else:
                self.rows_unmatched += 1
            return hit

        n = len(self._formats)
        # Start at the previous winner and wrap, so a run of same-format rows
        # costs one attempt each.
        hit: FormatMatch | None = None
        for offset in range(n):
            i = (self._last + offset) % n
            fmt = self._formats[i]
            if fmt.hint and fmt.hint not in message:
                continue
            m = fmt.compiled.search(message)
            if m is None:
                continue
            self._last = i
            hit = FormatMatch(fmt.name, {k: v or "" for k, v in m.groupdict().items()})
            break

        if hit is not None:
            self.match_counts[hit.format_name] += 1
        else:
            self.rows_unmatched += 1

        if len(self._cache) >= 2000:
            self._cache.clear()
        self._cache[message] = hit
        return hit

    def coverage(self) -> list[dict[str, object]]:
        """Rows parsed per format, most-used first.

        A format sitting at zero across a whole job is the visible symptom of a
        regex that doesn't work — otherwise it fails silently and just shows up
        as a lower match rate.
        """
        return [
            {"format": name, "rows": count}
            for name, count in sorted(self.match_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]


def validate_formats(
    formats: list[LogFormat],
    group_by: list[str],
    unique_fields: list[str],
    raw_columns: Sequence[str] = (),
) -> None:
    """Every field the spec uses has to come from somewhere.

    A field missing from *some* formats is fine and expected — those rows get an
    empty value. A field defined by *no* format is a typo that would otherwise
    produce a silent column of blanks.
    """
    known = set()
    for f in formats:
        known.update(f.compiled.groupindex)
    missing = [f for f in (*group_by, *unique_fields, *raw_columns) if f not in known]
    if missing:
        raise AggregationError(
            f"no log format defines the named group(s): {', '.join(sorted(set(missing)))}"
        )
    # Grouping by the field being counted puts every value in a group of its own,
    # so every count comes out as 1 — a report that looks fine and says nothing.
    both = [f for f in group_by if f in set(unique_fields)]
    if both:
        raise AggregationError(
            f"{', '.join(both)} cannot be both grouped by and counted — every count would be 1"
        )
