"""NOT / exclusion phrases on saved searches.

Saved searches can require words (AND) and now exclude words or adjacent
phrases (NOT). The Last9 query operators are `$notcontains` and `$notregex`;

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "filter_templates",
        sa.Column("exclude_phrases", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "filter_templates",
        sa.Column("exclude_exact_phrases", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("filter_templates", "exclude_exact_phrases")
    op.drop_column("filter_templates", "exclude_phrases")
