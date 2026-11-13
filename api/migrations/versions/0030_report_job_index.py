"""Index scheduled run history for reporting.

Reports read jobs by ``created_by = "schedule:<id>"`` and bucket them by
``created_at`` day. The existing (created_by, id) index narrows the owner but
still leaves the date filter to a scan of that schedule's history.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_created_by_created_at "
        "ON jobs (created_by, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_created_by_created_at")
