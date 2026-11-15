"""Concurrent jobs lease/owner/progress indexes.

Revision ID: 0032b
Revises: 0032

Each index is built in its own autocommit block: CREATE INDEX CONCURRENTLY
cannot run inside a transaction. IF NOT EXISTS is deliberately not used --
a leftover invalid index from a killed build would otherwise satisfy the name
check and be silently accepted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0032b"
down_revision = "0032"
branch_labels = None
depends_on = None


INDEXES = (
    ("ix_jobs_lease", ("status", "lease_expires_at"), "lease_expires_at IS NOT NULL"),
    ("ix_jobs_owner", ("owner_id",), "owner_id IS NOT NULL"),
    ("ix_jobs_progress", ("status", "progress_at"), "progress_at IS NOT NULL"),
)


def _index_is_valid(bind, name: str) -> bool:
    return bool(
        bind.execute(
            text(
                "SELECT i.indisvalid "
                "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = :name"
            ),
            {"name": name},
        ).scalar()
    )


def _drop_if_present(bind, name: str) -> None:
    exists = bind.execute(
        text("SELECT to_regclass(:n)"), {"n": f"public.{name}"}
    ).scalar()
    if exists:
        bind.execute(sa.text(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"'))


def _index_definition(bind, name: str) -> str | None:
    return bind.execute(
        text(
            "SELECT pg_get_indexdef(i.indexrelid) "
            "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name"
        ),
        {"name": name},
    ).scalar()


def _matches(definition: str | None, columns: tuple[str, ...], predicate: str) -> bool:
    """A same-named index is not enough: the definition must match too."""
    if not definition:
        return False
    flat = " ".join(definition.split())
    wanted_cols = "(" + ", ".join(columns) + ")"
    return wanted_cols in flat and predicate.replace(" ", "") in flat.replace(" ", "")


def _ensure(bind, name: str, columns: tuple[str, ...], predicate: str) -> None:
    if _index_is_valid(bind, name) and _matches(
        _index_definition(bind, name), columns, predicate
    ):
        return
    _drop_if_present(bind, name)
    op.create_index(
        name,
        "jobs",
        list(columns),
        unique=False,
        postgresql_concurrently=True,
        postgresql_where=sa.text(predicate),
    )
    if not _index_is_valid(bind, name):
        raise RuntimeError(f"{name} did not become valid")


def upgrade() -> None:
    for name, columns, predicate in INDEXES:
        with op.get_context().autocommit_block():
            _ensure(op.get_bind(), name, columns, predicate)


def downgrade() -> None:
    for name, _columns, _predicate in reversed(INDEXES):
        with op.get_context().autocommit_block():
            _drop_if_present(op.get_bind(), name)
