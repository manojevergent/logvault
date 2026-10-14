"""Add aggregation_result to jobs (parse & aggregate — unique-value counts).

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("aggregation_result", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "aggregation_result")
