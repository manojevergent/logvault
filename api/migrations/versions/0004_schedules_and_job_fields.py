"""schedules + job preview/output_format/is_preview

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("output_format", sa.String(10), nullable=False, server_default="csv")
    )
    op.add_column(
        "jobs",
        sa.Column("is_preview", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("jobs", sa.Column("preview", sa.JSON(), nullable=True))

    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("lookback_seconds", sa.Integer(), nullable=False),
        sa.Column("region_code", sa.String(40), nullable=False),
        sa.Column("index_target_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("chunk_hours", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("id_batch_size", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("output_format", sa.String(10), nullable=False, server_default="csv"),
        sa.Column("filter_spec", sa.JSON(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("schedules")
    op.drop_column("jobs", "preview")
    op.drop_column("jobs", "is_preview")
    op.drop_column("jobs", "output_format")
