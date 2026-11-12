"""S3 delivery profiles and per-job destination snapshots.

Saved searches and schedules can point at a reusable S3 profile. A job copies
that profile (bucket/prefix) into `s3_destination` at creation, so editing or
deleting a profile later never rewrites where a historical run says it went.
Uploaded artifact URIs and any upload error live on the job.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "s3_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("region", sa.String(length=40), nullable=False),
        sa.Column("prefix", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("endpoint_url", sa.Text(), nullable=True),
        sa.Column("encrypted_access_key_id", sa.Text(), nullable=True),
        sa.Column("encrypted_secret_access_key", sa.Text(), nullable=True),
        sa.Column("encrypted_session_token", sa.Text(), nullable=True),
        sa.Column("key_last4", sa.String(length=8), nullable=True),
        sa.Column("force_path_style", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_s3_profiles_name"),
    )

    op.add_column("filter_templates", sa.Column("s3_profile_id", sa.Integer(), nullable=True))
    op.add_column("schedules", sa.Column("s3_profile_id", sa.Integer(), nullable=True))

    op.add_column("jobs", sa.Column("s3_profile_id", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("s3_destination", sa.JSON(), nullable=True))
    op.add_column("jobs", sa.Column("s3_uri", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("s3_summary_uri", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("s3_counts_uri", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("s3_error", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("s3_uploaded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "s3_uploaded_at")
    op.drop_column("jobs", "s3_error")
    op.drop_column("jobs", "s3_counts_uri")
    op.drop_column("jobs", "s3_summary_uri")
    op.drop_column("jobs", "s3_uri")
    op.drop_column("jobs", "s3_destination")
    op.drop_column("jobs", "s3_profile_id")
    op.drop_column("schedules", "s3_profile_id")
    op.drop_column("filter_templates", "s3_profile_id")
    op.drop_table("s3_profiles")
