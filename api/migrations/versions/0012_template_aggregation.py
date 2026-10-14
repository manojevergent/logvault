"""Filter templates carry the parse & aggregate config too, so a saved search
restores its regex/group-by/count-unique instead of them being retyped.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("filter_templates", sa.Column("aggregation", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("filter_templates", "aggregation")
