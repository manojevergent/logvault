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
    # Refuse to destroy dispatch intent. Dropping this table discards every
    # obligation that has not been delivered, so the downgrade fails loudly
    # instead of silently losing work. The runbook's drain steps exist to get
    # these counts to zero first.
    bind = op.get_bind()
    # Take the table exclusively BEFORE counting. A dispatcher that committed
    # after the count but before the DROP would otherwise lose its row silently.
    # Holding ACCESS EXCLUSIVE blocks new inserts and waits out transactions
    # that already touched the table, so the counts below see everything that
    # can still exist and nothing can be added afterwards.
    bind.execute(sa.text("LOCK TABLE job_dispatch_outbox IN ACCESS EXCLUSIVE MODE"))
    pending = bind.execute(sa.text(
        "SELECT count(*) FROM job_dispatch_outbox WHERE status IN ('pending','leased')"
    )).scalar()
    orphaned = bind.execute(sa.text(
        "SELECT count(*) FROM job_dispatch_outbox o JOIN jobs j ON j.id = o.job_id "
        "WHERE o.status = 'dead' AND j.status NOT IN ('completed','failed','canceled')"
    )).scalar()
    if pending or orphaned:
        raise RuntimeError(
            "refusing to drop job_dispatch_outbox: "
            f"{pending} pending/leased and {orphaned} dead obligations for "
            "non-terminal jobs. Drain or resolve them before downgrading."
        )
    op.drop_index("ix_job_dispatch_locked", table_name="job_dispatch_outbox")
    op.drop_index("ix_job_dispatch_due", table_name="job_dispatch_outbox")
    op.drop_table("job_dispatch_outbox")
