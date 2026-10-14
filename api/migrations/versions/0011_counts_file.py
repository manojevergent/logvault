"""Jobs: counts_file_path — per-value occurrence counts (the pivot-table view).

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("counts_file_path", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "counts_file_path")
