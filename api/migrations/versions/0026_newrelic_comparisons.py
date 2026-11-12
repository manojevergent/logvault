"""New Relic connections and saved Last9 vs New Relic comparisons.

The comparison feature needs three tables: the encrypted New Relic
account/API-key pair, the saved comparison config, and a snapshot of every run.
Run results are JSON because both APIs return provider-shaped rows and the UI
normalizes them; totals/series are stored alongside so the history list can be
rendered without parsing the raw payload.

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "newrelic_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("region", sa.String(length=10), nullable=False, server_default="us"),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("api_key_last4", sa.String(length=8), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "comparisons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("last9_credential_id", sa.Integer(), nullable=False),
        sa.Column("last9_index_target_id", sa.Integer(), nullable=False),
        sa.Column("last9_region_code", sa.String(length=40), nullable=False),
        sa.Column("last9_pipeline", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("last9_filter_spec", sa.JSON(), nullable=True),
        sa.Column("nr_credential_id", sa.Integer(), nullable=False),
        sa.Column("nrql", sa.Text(), nullable=False),
        sa.Column("nr_value_mode", sa.String(length=10), nullable=False, server_default="sum"),
        sa.Column("nr_value_field", sa.String(length=120), nullable=True),
        sa.Column("bucket_seconds", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "comparison_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("comparison_id", sa.Integer(), nullable=False),
        sa.Column("start_epoch", sa.BigInteger(), nullable=False),
        sa.Column("end_epoch", sa.BigInteger(), nullable=False),
        sa.Column("bucket_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last9_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last9_error", sa.Text(), nullable=True),
        sa.Column("last9_total", sa.Float(), nullable=True),
        sa.Column("last9_series", sa.JSON(), nullable=True),
        sa.Column("last9_raw", sa.JSON(), nullable=True),
        sa.Column("last9_elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("newrelic_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("newrelic_error", sa.Text(), nullable=True),
        sa.Column("newrelic_total", sa.Float(), nullable=True),
        sa.Column("newrelic_series", sa.JSON(), nullable=True),
        sa.Column("newrelic_raw", sa.JSON(), nullable=True),
        sa.Column("newrelic_metadata", sa.JSON(), nullable=True),
        sa.Column("newrelic_elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("nrql_effective", sa.Text(), nullable=True),
        sa.Column("last9_pipeline_effective", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_comparison_runs_comparison_id_id",
        "comparison_runs",
        ["comparison_id", sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_comparison_runs_comparison_id_id", table_name="comparison_runs")
    op.drop_table("comparison_runs")
    op.drop_table("comparisons")
    op.drop_table("newrelic_credentials")
