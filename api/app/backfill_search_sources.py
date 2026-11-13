"""Fill in missing sources on saved searches.

A saved search is meant to be runnable as-is: filter, parse pattern, customer
and the index those logs live in. Searches created before the wizard remembered
their source have ``index_target_id`` NULL, so loading one left the source
picker on whatever was selected — often the wrong index, which returns zero
rows.

The most reliable evidence for the right index is the last job that ran under
the same label: it carries the exact index, credential and region the search
was last used with. For templates with an index but a missing credential or
region, the index itself supplies them.

    python -m app.backfill_search_sources            # dry run
    python -m app.backfill_search_sources --apply    # write
"""

from __future__ import annotations

import argparse

from sqlalchemy import or_, select

from app.database import SessionLocal
from app.models import FilterTemplate, IndexTarget, Job


def _latest_job_source(db, name: str) -> Job | None:
    return db.execute(
        select(Job)
        .where(Job.filter_spec["label"].as_string() == name)
        .order_by(Job.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        missing = (
            db.query(FilterTemplate)
            .filter(FilterTemplate.index_target_id.is_(None))
            .order_by(FilterTemplate.id)
            .all()
        )
        from_jobs = 0
        no_history = 0
        for tpl in missing:
            job = _latest_job_source(db, tpl.name)
            if job is None or job.index_target_id is None:
                print(f"#{tpl.id} {tpl.name}: no job history, left alone")
                no_history += 1
                continue
            print(
                f"#{tpl.id} {tpl.name}: index {job.index_target_id} "
                f"({job.region_code}) from job #{job.id}"
            )
            if args.apply:
                tpl.index_target_id = job.index_target_id
                tpl.credential_id = job.credential_id
                tpl.region_code = job.region_code
            from_jobs += 1

        # An index already knows its credential and region; fill any gaps so the
        # saved search can run without asking again.
        partial = (
            db.query(FilterTemplate)
            .filter(
                FilterTemplate.index_target_id.isnot(None),
                or_(
                    FilterTemplate.credential_id.is_(None),
                    FilterTemplate.region_code.is_(None),
                ),
            )
            .order_by(FilterTemplate.id)
            .all()
        )
        from_index = 0
        for tpl in partial:
            idx = db.get(IndexTarget, tpl.index_target_id)
            if idx is None:
                print(f"#{tpl.id} {tpl.name}: index {tpl.index_target_id} no longer exists")
                continue
            print(
                f"#{tpl.id} {tpl.name}: credential/region from index "
                f"{idx.name} ({idx.region_code})"
            )
            if args.apply:
                tpl.credential_id = idx.credential_id
                tpl.region_code = idx.region_code
            from_index += 1

        if args.apply:
            db.commit()

        print(
            f"\n{'Applied' if args.apply else 'Would apply'}: "
            f"{from_jobs} from job history, {from_index} from their index; "
            f"{no_history} without enough history."
        )
        if not args.apply and (from_jobs or from_index):
            print("Re-run with --apply to write.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
