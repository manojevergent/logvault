"""Complete unmatched-line artifact for parse jobs.

The aggregation result carries a small sample for display; the full set of rows
that failed the parse pattern lives in its own CSV (`timestamp,message`) so a
bad regex can be corrected from the exact lines, at any volume.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("unmatched_file_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "unmatched_file_path")
