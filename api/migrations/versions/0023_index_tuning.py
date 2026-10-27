"""Composite DB indexes for fast queries.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_preview_status_created "
        "ON jobs (is_preview, status, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_credential_created "
        "ON jobs (credential_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_preview_status_created")
    op.execute("DROP INDEX IF EXISTS ix_jobs_credential_created")
