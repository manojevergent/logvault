"""Alert recipients on scheduled job failure.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schedules",
        sa.Column("alert_recipients", sa.JSON, server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("schedules", "alert_recipients")
