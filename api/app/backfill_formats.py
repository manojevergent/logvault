"""Backfill the Log Formats catalog from patterns that already exist.

Every manually entered regex lives inside a saved search, job or schedule; this
brings them into the reusable library, deduped by normalized pattern. Safe to
re-run.

    python -m app.backfill_formats            # dry run (default)
    python -m app.backfill_formats --apply    # write the missing formats
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.format_registry import _normalized, register_aggregation_pattern
from app.models import FilterTemplate, Job, LogFormat, Schedule


def _sources(db):
    """(aggregation, source_name, source_kind, source_id) for every manual pattern."""
    for tpl in db.scalars(select(FilterTemplate).order_by(FilterTemplate.id)):
        yield tpl.aggregation, tpl.name, "saved search", tpl.id
    for sched in db.scalars(select(Schedule).order_by(Schedule.id)):
        agg = (sched.filter_spec or {}).get("aggregation")
        yield agg, sched.name, "schedule", sched.id
    # Only the two spec keys: filter_spec.ids can be 100 KB per job.
    rows = db.execute(
        select(
            Job.id,
            Job.filter_spec["label"].as_string(),
            Job.filter_spec["aggregation"],
        ).order_by(Job.id)
    ).all()
    for job_id, label, agg in rows:
        yield agg, label or f"job {job_id}", "job", job_id


def _manual_patterns(db):
    for agg, name, kind, source_id in _sources(db):
        if not agg or not agg.get("enabled") or agg.get("use_library"):
            continue
        regex = (agg.get("regex") or "").strip()
        if not regex:
            continue
        yield agg, name, kind, source_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the new formats")
    args = parser.parse_args()

    if not get_settings().auto_register_formats:
        print("AUTO_REGISTER_FORMATS is off; nothing to do.")
        return

    with SessionLocal() as db:
        existing = {_normalized(f.regex) for f in db.scalars(select(LogFormat))}
        existing.discard(None)

        sources = list(_manual_patterns(db))
        missing: list[tuple] = []
        seen: set[str] = set()
        for item in sources:
            normalized = _normalized(item[0]["regex"])
            if normalized is None or normalized in existing or normalized in seen:
                continue
            seen.add(normalized)
            missing.append(item)

        print(f"sources with a manual pattern : {len(sources):,}")
        print(f"distinct patterns in library  : {len(existing):,}")
        print(f"distinct patterns still new   : {len(missing):,}")

        if not args.apply:
            for _agg, name, kind, source_id in missing[:15]:
                print(f"  + {kind} {source_id} {name!r}")
            if len(missing) > 15:
                print(f"  ... and {len(missing) - 15} more")
            print("dry run — pass --apply to add them")
            return

        for agg, name, kind, source_id in missing:
            register_aggregation_pattern(
                db,
                aggregation=agg,
                source_name=name,
                source_kind=kind,
                source_id=source_id,
            )
        db.commit()
        total = len(list(db.scalars(select(LogFormat))))
        print(f"added {len(missing)} format(s); library now has {total:,}")


if __name__ == "__main__":
    main()
