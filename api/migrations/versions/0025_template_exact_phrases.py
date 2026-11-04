"""Quoted / exact phrases on saved searches.

`$contains` in Last9 is word-based, so a phrase such as "API : 502" cannot be
expressed with it: as words, a stray "502" anywhere (even a millisecond field in
the log's JSON) satisfies the filter. Exact phrases are sent as regexes instead,
and saved searches need somewhere to keep them.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "filter_templates",
        sa.Column("exact_phrases", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("filter_templates", "exact_phrases")
