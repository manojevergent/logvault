"""Repair `total_chunks` on jobs that finished under the old estimate.

`total_chunks` was computed once from the job's starting chunk size, but the
worker adapts that size (1h -> 2h -> 4h on sparse data). A 25-hour window
queued as 25 chunks really finished in 13, so a *completed* job displayed
"13 / 25" and a half-filled bar.

Completed jobs are by definition done, so re-pin their denominator to the
number of chunks actually processed. Running/paused jobs need no repair: the
worker now re-estimates the total at every chunk boundary.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE jobs
           SET total_chunks = completed_chunks
         WHERE status = 'completed'
           AND completed_chunks > 0
           AND total_chunks > completed_chunks
        """
    )


def downgrade() -> None:
    # One-way data repair; the old (wrong) estimates are not worth restoring.
    pass
