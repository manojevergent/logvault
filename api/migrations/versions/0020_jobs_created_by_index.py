"""Index jobs.created_by.

Every schedule row triggers its own "latest job for this schedule" query, the
month-end rollup filters the same column, and the jobs list filters by owner —
all of them sequential scans over the whole jobs table until now.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # id DESC alongside it so "the newest job for this owner" is answered from
    # the index rather than sorting the matches.
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_created_by_id ON jobs (created_by, id DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_created_by_id")
