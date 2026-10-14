"""BigQuery config on schedules.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schedules",
        sa.Column("bq_config", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schedules", "bq_config")
