"""Dispatch outbox.

Revision ID: 0034
Revises: 0033

New table only. New-table indexes are intentionally not concurrent: the table
is empty, so there is no lock to avoid.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_dispatch_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column(
            "task_name",
            sa.String(length=80),
            nullable=False,
            server_default="logvault.run_job",
        ),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "job_id", "task_name", name="uq_job_dispatch_outbox_job_task"
        ),
    )
    op.create_index(
        "ix_job_dispatch_due", "job_dispatch_outbox", ["status", "next_attempt_at"]
    )
    op.create_index(
        "ix_job_dispatch_locked",
        "job_dispatch_outbox",
        ["locked_until"],
        postgresql_where=sa.text("locked_until IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_job_dispatch_locked", table_name="job_dispatch_outbox")
    op.drop_index("ix_job_dispatch_due", table_name="job_dispatch_outbox")
    op.drop_table("job_dispatch_outbox")
