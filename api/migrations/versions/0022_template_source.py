"""Remembered source on saved searches.

Each search records the credential/region/index it was built for, so batch
runs and the wizard come pre-filled. Nullable: searches saved before this
land with no source and behave exactly as before.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("filter_templates", sa.Column("credential_id", sa.Integer(), nullable=True))
    op.add_column("filter_templates", sa.Column("region_code", sa.String(40), nullable=True))
    op.add_column("filter_templates", sa.Column("index_target_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("filter_templates", "index_target_id")
    op.drop_column("filter_templates", "region_code")
    op.drop_column("filter_templates", "credential_id")
