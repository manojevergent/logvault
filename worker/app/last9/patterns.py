"""Regex primitives shared by the aggregator and the log-format library.

Split out so ``formats`` (a library of patterns) and ``aggregate`` (what to do
with the fields a pattern yields) can both use them without importing each other.
"""

from __future__ import annotations

import re

# Last9's Builder UI produces .NET/Grok-style named groups: (?<name>...).
# Python's `re` requires (?P<name>...) — accept both so a pattern copied
# straight from Last9 works without editing.
_FOREIGN_NAMED_GROUP = re.compile(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>")


class AggregationError(Exception):
    """Bad regex, or group_by/unique_fields reference a group nothing defines."""


def normalize_pattern(pattern: str) -> str:
    return _FOREIGN_NAMED_GROUP.sub(r"(?P<\1>", pattern)


def compile_pattern(regex: str) -> re.Pattern[str]:
    try:
        return re.compile(normalize_pattern(regex))
    except re.error as exc:
        raise AggregationError(f"invalid regex: {exc}") from exc
