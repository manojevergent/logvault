"""Job ownership, lease, progress, and completion state.

Revision ID: 0032
Revises: 0031

Additive only: eleven columns on ``jobs``, no indexes, no backfill. Existing
rows pick up column defaults, which PostgreSQL 11+ applies as metadata.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


COLUMNS = (
    sa.Column("owner_id", sa.String(length=128), nullable=True),
    sa.Column("lease_token", sa.BigInteger(), nullable=False, server_default="0"),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("progress_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("pause_requested_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column(
        "completion_state",
        sa.String(length=16),
        nullable=False,
        server_default="unknown",
    ),
    sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("gap_reason", sa.Text(), nullable=True),
    sa.Column("retry_of", sa.Integer(), nullable=True),
)


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("jobs", column)


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("jobs", column.name)
