"""Group extraction: one shared window, one job per saved search.

The group is a reporting/tracking unit only; each job remains independent so
it can run against its own source and retry without touching its siblings.

Revision ID: 0031
Revises: 0030
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extraction_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("start_epoch", sa.BigInteger(), nullable=False),
        sa.Column("end_epoch", sa.BigInteger(), nullable=False),
        sa.Column("chunk_hours", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id_batch_size", sa.Integer(), server_default="100", nullable=False),
        sa.Column("output_format", sa.String(length=10), server_default="csv", nullable=False),
        sa.Column("is_preview", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("parent_group_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_extraction_groups_parent_group_id",
        "extraction_groups",
        ["parent_group_id"],
    )
    op.add_column("jobs", sa.Column("group_id", sa.Integer(), nullable=True))
    op.create_index("ix_jobs_group_id", "jobs", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_group_id", table_name="jobs")
    op.drop_column("jobs", "group_id")
    op.drop_index("ix_extraction_groups_parent_group_id", table_name="extraction_groups")
    op.drop_table("extraction_groups")
