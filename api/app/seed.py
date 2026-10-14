"""Seed sample data so the app is usable immediately. Idempotent.

Regions are static (served from REGIONS), so only a sample index is seeded.
Run: python -m app.seed
"""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import IndexTarget


def seed() -> None:
    with SessionLocal() as db:
        exists = db.scalar(
            select(IndexTarget).where(
                IndexTarget.region_code == "ap-southeast-1", IndexTarget.name == "UMServices"
            )
        )
        if exists:
            print("seed: sample index already present")
            return
        db.add(
            IndexTarget(
                name="UMServices",
                region_code="ap-southeast-1",
                full_index_string="physical_index:UMServices",
                description="Sample index (Singapore)",
            )
        )
        db.commit()
        print("seed: created sample index UMServices (Singapore)")


if __name__ == "__main__":
    seed()
