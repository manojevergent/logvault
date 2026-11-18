"""Schedule anomaly alert thresholds.

Revision ID: 0035
Revises: 0034

Both alerts are opt-in. Existing schedules get safe defaults (disabled) and a
threshold pair that is ready to use when an operator turns them on.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schedules",
        sa.Column("alert_on_row_drop", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "schedules",
        sa.Column(
            "row_drop_threshold_pct", sa.Integer(), nullable=False, server_default=sa.text("20")
        ),
    )
    op.add_column(
        "schedules",
        sa.Column("alert_on_unmatched", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "schedules",
        sa.Column(
            "unmatched_threshold", sa.Integer(), nullable=False, server_default=sa.text("100")
        ),
    )
    op.create_check_constraint(
        "ck_schedules_row_drop_threshold_pct",
        "schedules",
        "row_drop_threshold_pct BETWEEN 1 AND 100",
    )
    op.create_check_constraint(
        "ck_schedules_unmatched_threshold",
        "schedules",
        "unmatched_threshold >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_schedules_unmatched_threshold", "schedules", type_="check")
    op.drop_constraint("ck_schedules_row_drop_threshold_pct", "schedules", type_="check")
    op.drop_column("schedules", "unmatched_threshold")
    op.drop_column("schedules", "alert_on_unmatched")
    op.drop_column("schedules", "row_drop_threshold_pct")
    op.drop_column("schedules", "alert_on_row_drop")
