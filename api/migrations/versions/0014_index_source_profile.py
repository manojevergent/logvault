"""Make an index target a complete source profile: it already carried the
region, so adding the credential and separating the display name from the
physical index name means picking one thing instead of three.

`name` becomes the profile label (e.g. "UMS_india") and `physical_index` holds
the real Last9 index (e.g. "UMServices"). They were the same field before, so
full_index_string derived from the label — renaming a target would silently have
pointed it at an index that does not exist.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("index_targets", sa.Column("credential_id", sa.Integer, nullable=True))
    op.add_column("index_targets", sa.Column("physical_index", sa.String(120), nullable=True))
    # Existing rows had full_index_string = "physical_index:<name>", so the label
    # was the physical name. Carry it across before anything can rename a label.
    op.execute("UPDATE index_targets SET physical_index = name WHERE physical_index IS NULL")


def downgrade() -> None:
    op.drop_column("index_targets", "physical_index")
    op.drop_column("index_targets", "credential_id")
