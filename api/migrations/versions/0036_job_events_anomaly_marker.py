"""One anomaly marker per job.

Revision ID: 0036
Revises: 0035

The worker's anomaly hook asks "has this job already alerted?" with a plain
SELECT and then INSERTs the marker in the same transaction. Under READ
COMMITTED two deliveries that reach the hook concurrently both see no marker
and both insert one, so the same anomaly can be emailed twice. The API
publishes every job twice (outbox row plus an immediate dispatch), so the
window is real for a fast scheduled run.

A partial unique index makes the second INSERT fail instead of duplicating.
The worker catches the violation and drops the duplicate delivery; the first
one still sends. The predicate is a constant LIKE, which PostgreSQL treats as
immutable, so it is allowed in an index predicate.

Production held zero anomaly events when this shipped, so the index cannot
fail on pre-existing duplicates. If a database does hold duplicates, remove
the extras before upgrading:

    DELETE FROM job_events a USING job_events b
     WHERE a.job_id = b.job_id
       AND a.message LIKE 'Anomaly detected%'
       AND b.message LIKE 'Anomaly detected%'
       AND a.id > b.id;
"""

from __future__ import annotations

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_job_events_anomaly_marker",
        "job_events",
        ["job_id"],
        unique=True,
        postgresql_where="message LIKE 'Anomaly detected%'",
    )


def downgrade() -> None:
    op.drop_index("uq_job_events_anomaly_marker", table_name="job_events")
