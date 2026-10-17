"""Google sign-in columns on users.

auth_provider records how the account was created, oauth_subject is Google's
stable `sub` (lookup key when present), and hashed_password becomes nullable
for accounts that never set a password.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_provider", sa.String(20), nullable=False, server_default="password"),
    )
    op.add_column("users", sa.Column("oauth_subject", sa.String(255), nullable=True))
    # NULLs never collide in Postgres (or SQLite), so pre-existing rows stay
    # valid and only real subject duplicates are rejected.
    op.create_unique_constraint("uq_users_oauth_subject", "users", ["oauth_subject"])
    op.alter_column("users", "hashed_password", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.drop_constraint("uq_users_oauth_subject", "users", type_="unique")
    op.drop_column("users", "oauth_subject")
    op.drop_column("users", "auth_provider")
    op.alter_column("users", "hashed_password", existing_type=sa.Text(), nullable=False)
