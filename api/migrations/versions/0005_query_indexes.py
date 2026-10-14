"""Add query indexes for jobs table hot paths.

jobs(credential_id) — cascade-delete checks and per-credential filtering.
jobs(is_preview, created_at DESC) — the main list query filters is_preview=false
  and orders by created_at DESC; covering both columns avoids a full table scan.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_jobs_credential_id", "jobs", ["credential_id"])
    op.create_index(
        "ix_jobs_list",
        "jobs",
        ["is_preview", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_list", "jobs")
    op.drop_index("ix_jobs_credential_id", "jobs")
