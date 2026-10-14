"""Customer on a saved search, so every extract it produces lands in that
customer's folder.

Jobs carry it in filter_spec alongside the label rather than in a column: it is
copied from the search at creation time and never queried on.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("filter_templates", sa.Column("customer", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("filter_templates", "customer")
