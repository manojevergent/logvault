"""Worker DB access via SQLAlchemy Core.

ponytail: the table definitions mirror the api ORM (and Alembic schema) rather than
importing the api package — keeps the worker independently buildable. Core (not
raw text()) so JSON columns serialize portably on Postgres and SQLite. If a third
consumer needs these, promote to a shared package.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    create_engine,
    func,
    or_,
    select,
)

from app.config import get_settings

metadata = MetaData()

jobs = Table(
    "jobs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("status", String(20)),
    Column("region_code", String(40)),
    Column("index_target_id", Integer),
    Column("credential_id", Integer),
    Column("start_epoch", BigInteger),
    Column("end_epoch", BigInteger),
    Column("chunk_hours", Integer),
    Column("id_batch_size", Integer),
    Column("filter_spec", JSON),
    Column("rows_written", BigInteger),
    Column("total_chunks", Integer),
    Column("completed_chunks", Integer),
    Column("current_chunk_start", BigInteger),
    Column("checkpoint", JSON),
    Column("output_file_path", Text),
    Column("summary_file_path", Text),
    Column("counts_file_path", Text),
    Column("rollup_of", JSON),
    Column("output_format", String(10)),
    Column("is_preview", Boolean),
    Column("preview", JSON),
    Column("aggregation_result", JSON),
    Column("error_message", Text),
    Column("created_by", String(255)),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
)

schedules = Table(
    "schedules",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(120)),
    Column("enabled", Boolean),
    Column("interval_seconds", Integer),
    Column("lookback_seconds", Integer),
    Column("calendar_day", Boolean),
    Column("region_code", String(40)),
    Column("index_target_id", Integer),
    Column("credential_id", Integer),
    Column("chunk_hours", Integer),
    Column("id_batch_size", Integer),
    Column("output_format", String(10)),
    Column("filter_spec", JSON),
    Column("bq_config", JSON),
    Column("last_run_at", DateTime(timezone=True)),
)

job_events = Table(
    "job_events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("job_id", Integer),
    Column("ts", DateTime(timezone=True), server_default=func.now()),
    Column("level", String(10)),
    Column("message", Text),
    Column("rows_delta", Integer),
)

last9_credentials = Table(
    "last9_credentials",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("org_slug", String(120)),
    Column("encrypted_refresh_token", Text),
    Column("refresh_token_last4", String(8)),
    Column("encrypted_access_token", Text),
    Column("access_token_expires_at", BigInteger),
)

log_formats = Table(
    "log_formats",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(120)),
    Column("regex", Text),
    Column("hint", String(200)),
    Column("sample_line", Text),
    Column("priority", Integer),
    Column("enabled", Boolean),
    Column("description", Text),
)

# Runtime settings the admin UI writes; the worker reads them at send time so a
# saved SMTP change applies without restarting this process.
app_settings = Table(
    "app_settings",
    metadata,
    Column("key", String(60), primary_key=True),
    Column("value", JSON),
)

index_targets = Table(
    "index_targets",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("region_code", String(40)),
    Column("full_index_string", String(160)),
)


@lru_cache
def engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, future=True)


def load(conn, table: Table, row_id: int):
    return conn.execute(select(table).where(table.c.id == row_id)).mappings().first()


def update_job(conn, job_id: int, **values) -> None:
    conn.execute(jobs.update().where(jobs.c.id == job_id).values(**values))


def current_status(conn, job_id: int) -> str | None:
    return conn.execute(select(jobs.c.status).where(jobs.c.id == job_id)).scalar_one_or_none()


def claim_job(conn, job_id: int, *, reclaim_before=None, **values) -> bool:
    """Move a job from ``queued`` to ``running``, and say whether we got it.

    The transition is the claim: conditioning the UPDATE on the current status
    means exactly one worker can win it. Without this, a resume dispatched while
    the first worker was still mid-chunk put two workers on the same CSV and the
    same value store - duplicated rows and wrong counts, reported as a clean
    "completed" - and a job cancelled while still queued started anyway, because
    the status was overwritten without ever being read.

    ``reclaim_before`` lets a *running* job be taken over, but only when it has
    gone quiet since that instant. That is the redelivery case: the broker hands
    the task to a new worker after the old one died, and the row still says
    ``running``. Without it the job sat idle until ``reap_stale_jobs`` failed it
    an hour later, and only a manual retry resumed it. The runner heartbeats
    every few minutes, so a job that is actually being worked never qualifies.
    """
    claimable = jobs.c.status == "queued"
    if reclaim_before is not None:
        last_event = (
            select(func.max(job_events.c.ts))
            .where(job_events.c.job_id == jobs.c.id)
            .correlate(jobs)
            .scalar_subquery()
        )
        last_seen = func.coalesce(last_event, jobs.c.started_at)
        claimable = or_(
            claimable,
            and_(jobs.c.status == "running", last_seen < reclaim_before),
        )

    result = conn.execute(
        jobs.update()
        .where(jobs.c.id == job_id, claimable)
        .values(status="running", **values)
        .returning(jobs.c.id)
    )
    return result.first() is not None


def load_log_formats(conn) -> list[dict]:
    """Enabled formats in the order they should be tried (lowest priority first).

    Read once per job rather than per row — the library is small and static for
    the life of a run.
    """
    rows = conn.execute(
        select(log_formats)
        .where(log_formats.c.enabled)
        .order_by(log_formats.c.priority, log_formats.c.id)
    ).mappings()
    return [dict(r) for r in rows]


def add_event(conn, job_id: int, message: str, level: str = "info", rows_delta: int = 0) -> None:
    conn.execute(
        job_events.insert().values(
            job_id=job_id, message=message, level=level, rows_delta=rows_delta
        )
    )
