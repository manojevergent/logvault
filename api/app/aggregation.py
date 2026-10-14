"""Validation for parse & aggregate regex specs at job/schedule creation time.

ponytail: duplicated (in miniature) from worker/app/last9/aggregate.py rather
than a cross-package import — the API validates fast at creation time so a bad
regex 422s immediately instead of surfacing as a failed job later; the worker
re-validates independently when it actually runs the job.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_FOREIGN_NAMED_GROUP = re.compile(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>")

# A pattern runs against every row of a multi-million-row extract, `re` has no
# timeout, and no Celery time limit is configured — so a pattern that backtracks
# catastrophically spins one worker slot until the container is restarted.
# Cancel cannot help: the status check happens between chunks, and the row never
# finishes.
MAX_PATTERN_LENGTH = 2000

# Deliberately narrow: a quantified group whose own body ends in a quantifier —
# `(\d+)+`, `(a*)*`, `(x+)*`. That is the shape that explodes. Lazy quantifiers
# (`.*?`) and quantified character classes (`[^<]*`) are left alone, because the
# real production patterns depend on them.
_NESTED_QUANTIFIER = re.compile(r"\((?:\?[P]?<[^>]+>|\?:)?[^()]*[*+][^()]*\)\s*[*+]")


def normalize_pattern(pattern: str) -> str:
    return _FOREIGN_NAMED_GROUP.sub(r"(?P<\1>", pattern)


def check_pattern_cost(pattern: str) -> None:
    """Reject patterns that can wedge a worker. Raises ValueError."""
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"regex is {len(pattern)} characters; the limit is {MAX_PATTERN_LENGTH}")
    if _NESTED_QUANTIFIER.search(pattern):
        raise ValueError(
            "regex has a quantifier applied to a group that is itself quantified "
            "(e.g. `(\\d+)+`), which can backtrack catastrophically and hang the "
            "worker. Rewrite the inner group without the repeat."
        )


def validate_aggregation(
    regex: str,
    group_by: list[str],
    unique_fields: list[str],
    raw_columns: Sequence[str] = (),
    raw_column_defaults: dict[str, str] | None = None,
    use_library: bool = False,
) -> None:
    """Raises ValueError with a caller-facing message on any problem."""
    if not unique_fields:
        raise ValueError("aggregation needs at least one field to count unique values of")
    if use_library:
        # Field names resolve against the Log Formats library at run time, not
        # against `regex` (which is empty in this mode) — only the
        # group_by/unique overlap check below applies here.
        pass
    else:
        check_pattern_cost(regex)
        try:
            compiled = re.compile(normalize_pattern(regex))
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        defined = set(compiled.groupindex)
        # A raw_columns entry with a configured default is a deliberate constant,
        # not a field the regex is expected to define.
        checked_raw = [c for c in raw_columns if c not in (raw_column_defaults or {})]
        missing = [f for f in (*group_by, *unique_fields, *checked_raw) if f not in defined]
        if missing:
            raise ValueError(f"regex has no named group(s): {', '.join(missing)}")
    # Grouping by the very field being counted puts every distinct value in a
    # group of its own, so every count comes out as exactly 1 — a report that
    # looks plausible and says nothing. There is no case where it's meaningful.
    both = [f for f in group_by if f in set(unique_fields)]
    if both:
        raise ValueError(
            f"{', '.join(both)} cannot be both grouped by and counted — every count "
            f"would be 1. Remove it from 'group by' to count unique values of it "
            f"per remaining group."
        )
