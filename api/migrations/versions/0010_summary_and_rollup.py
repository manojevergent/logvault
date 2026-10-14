"""Jobs: summary_file_path (full per-group unique counts) and rollup_of
(a job that merges other jobs' distinct-value stores instead of calling Last9).

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("summary_file_path", sa.Text, nullable=True))
    op.add_column("jobs", sa.Column("rollup_of", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "rollup_of")
    op.drop_column("jobs", "summary_file_path")
