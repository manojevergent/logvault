"""Index the jobs list query.

Every dashboard, jobs and customers page re-runs
``WHERE is_preview = false ORDER BY created_at DESC LIMIT n`` every few
seconds. Without a matching index that is a full scan plus a sort of the whole
jobs table on each poll.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0005 already created an index of this name over (is_preview, created_at DESC).
    # Creating it again aborted `alembic upgrade head` on any database built from
    # scratch, so 0019 never applied. Dropping first converges both histories —
    # a database that has either version, or neither — on the definition below.
    op.execute("DROP INDEX IF EXISTS ix_jobs_list")
    op.create_index(
        "ix_jobs_list",
        "jobs",
        ["is_preview", "created_at"],
        postgresql_using="btree",
    )
    # The job detail page reads events by job in id order.
    op.create_index("ix_job_events_job_id_id", "job_events", ["job_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_job_events_job_id_id", table_name="job_events")
    op.drop_index("ix_jobs_list", table_name="jobs")
