"""Artifact and checkpoint pointers.

Revision ID: 0033
Revises: 0032b
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032b"
branch_labels = None
depends_on = None


COLUMNS = (
    sa.Column("store_path", sa.Text(), nullable=True),
    sa.Column("spec_fingerprint", sa.String(length=64), nullable=True),
    sa.Column("checkpoint_version", sa.Integer(), nullable=False, server_default="1"),
)


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("jobs", column)


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("jobs", column.name)
