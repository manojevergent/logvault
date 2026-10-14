"""Log formats library: named parse patterns, tried against every row until one
fits, so a job can span many log shapes without one regex per job.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "log_formats",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("regex", sa.Text, nullable=False),
        # A literal substring every line of this format contains. Checked before
        # the regex, which is what keeps "try every format" affordable.
        sa.Column("hint", sa.String(200), nullable=True),
        sa.Column("sample_line", sa.Text, nullable=True),
        # Lower is tried first. Matters because the first match wins, so a
        # narrow format has to be able to outrank a broad one.
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_log_formats_priority", "log_formats", ["priority", "id"])


def downgrade() -> None:
    op.drop_index("ix_log_formats_priority", table_name="log_formats")
    op.drop_table("log_formats")
