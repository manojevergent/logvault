"""Auto-registration of manually entered parse patterns in the Log Formats library.

A regex typed on one saved search (or job/schedule) used to die with that
record: every other search had to be rebuilt from scratch. This module makes the
platform's existing pattern corpus reusable:

* normalize the pattern (Last9's ``(?<name>`` and Python's ``(?P<name>`` are the
  same shape) and dedupe against the library;
* add a new format at a lower priority than curated formats, with provenance in
  its description and no hint (a wrong hint would silently skip matching rows);
* never fail the caller's save because the catalog insert failed.

Backfill existing rows with ``python -m app.backfill_formats --apply``.
"""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.aggregation import check_pattern_cost, normalize_pattern
from app.config import get_settings
from app.models import LogFormat

# Curated formats default to 100. Auto-added ones run after them so a reviewed
# pattern still wins when both would match.
AUTO_PRIORITY = 500
_MAX_NAME = 100


def _stem(source_name: str | None, source_kind: str, source_id: int | None) -> str:
    raw = " ".join((source_name or "").split())
    if not raw:
        raw = f"{source_kind} {source_id}" if source_id is not None else f"Auto {source_kind}"
    return raw[:_MAX_NAME].rstrip() or "Auto format"


def _normalized(regex: str) -> str | None:
    """The comparison key, or None when the pattern cannot compile."""
    try:
        normalized = normalize_pattern(regex).strip()
        re.compile(normalized)
        check_pattern_cost(regex)
    except (re.error, ValueError):
        return None
    return normalized


def register_aggregation_pattern(
    db: Session,
    *,
    aggregation: dict | None,
    source_name: str | None,
    source_kind: str,
    source_id: int | None = None,
    created_by: str | None = None,
) -> LogFormat | None:
    """Add a manual regex to the library, deduped by normalized pattern.

    Returns the existing or new format, or None when there is nothing to add.
    Best-effort by design: a catalog problem must not reject the search/job that
    triggered it.
    """
    if not get_settings().auto_register_formats:
        return None
    if not aggregation or not aggregation.get("enabled"):
        return None
    if aggregation.get("use_library"):
        return None
    regex = (aggregation.get("regex") or "").strip()
    if not regex:
        return None

    normalized = _normalized(regex)
    if normalized is None:
        return None

    formats = list(db.scalars(select(LogFormat)))
    for fmt in formats:
        existing = _normalized(fmt.regex)
        if existing is not None and existing == normalized:
            return fmt

    used = {fmt.name for fmt in formats}
    stem = _stem(source_name, source_kind, source_id)
    name = stem
    if name in used:
        # Same source name, different pattern: keep both and make this one
        # traceable to the pattern itself.
        name = f"{stem} (auto {hashlib.sha1(normalized.encode()).hexdigest()[:8]})"
    candidate = name
    suffix = 2
    while candidate in used:
        candidate = f"{name} {suffix}"
        suffix += 1

    description = f"Auto-added from {source_kind}"
    if source_name:
        description += f" \u201c{source_name}\u201d"
    if source_id is not None:
        description += f" (#{source_id})"

    fmt = LogFormat(
        name=candidate,
        regex=regex,
        hint=None,  # never guess: a hint that misses would hide matching rows
        sample_line=None,
        priority=AUTO_PRIORITY,
        enabled=True,
        description=description,
        created_by=created_by,
    )
    try:
        # The caller owns the transaction; the savepoint confines a name-race
        # IntegrityError to this insert.
        with db.begin_nested():
            db.add(fmt)
            db.flush()
    except IntegrityError:
        db.expire_all()
        return db.scalar(select(LogFormat).where(LogFormat.name == candidate))
    return fmt
