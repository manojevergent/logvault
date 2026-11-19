"""Worker DB access via SQLAlchemy Core.

ponytail: the table definitions mirror the api ORM (and Alembic schema) rather than
importing the api package — keeps the worker independently buildable. Core (not
raw text()) so JSON columns serialize portably on Postgres and SQLite. If a third
consumer needs these, promote to a shared package.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Engine,
    Index,
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
    text,
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
    Column("unmatched_file_path", Text),
    Column("rollup_of", JSON),
    Column("output_format", String(10)),
    Column("is_preview", Boolean),
    Column("preview", JSON),
    Column("aggregation_result", JSON),
    Column("s3_profile_id", Integer),
    Column("s3_destination", JSON),
    Column("s3_uri", Text),
    Column("s3_summary_uri", Text),
    Column("s3_counts_uri", Text),
    Column("s3_error", Text),
    Column("s3_uploaded_at", DateTime(timezone=True)),
    Column("error_message", Text),
    Column("created_by", String(255)),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    # P1 ownership / lease / completion
    Column("owner_id", String(128)),
    Column("lease_token", BigInteger),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("heartbeat_at", DateTime(timezone=True)),
    Column("progress_at", DateTime(timezone=True)),
    Column("pause_requested_at", DateTime(timezone=True)),
    Column("cancel_requested_at", DateTime(timezone=True)),
    Column("completion_state", String(16)),
    Column("gap_count", Integer),
    Column("gap_reason", Text),
    Column("retry_of", Integer),
    # P1 artifact / checkpoint pointers
    Column("store_path", Text),
    Column("spec_fingerprint", String(64)),
    Column("checkpoint_version", Integer),
)

job_dispatch_outbox = Table(
    "job_dispatch_outbox",
    metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True),
    Column("job_id", Integer),
    Column("task_name", String(80)),
    Column("payload", JSON),
    Column("status", String(16)),
    Column("attempts", Integer),
    Column("next_attempt_at", DateTime(timezone=True)),
    Column("locked_by", String(128)),
    Column("locked_until", DateTime(timezone=True)),
    Column("last_error", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("published_at", DateTime(timezone=True)),
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
    Column("s3_profile_id", Integer),
    Column("alert_recipients", JSON),
    Column("alert_on_row_drop", Boolean),
    Column("row_drop_threshold_pct", Integer),
    Column("alert_on_unmatched", Boolean),
    Column("unmatched_threshold", Integer),
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
    # Mirrors Alembic 0036: at most one anomaly marker per job. The worker's
    # duplicate-delivery guard is a SELECT-then-INSERT that two concurrent
    # deliveries can both pass; this index turns the loser's INSERT into an
    # IntegrityError the hook drops instead of sending twice.
    Index(
        "uq_job_events_anomaly_marker",
        "job_id",
        unique=True,
        postgresql_where=text("message LIKE 'Anomaly detected%'"),
        sqlite_where=text("message LIKE 'Anomaly detected%'"),
    ),
)

last9_credentials = Table(
    "last9_credentials",
    metadata,
    Column("id", Integer, primary_key=True),
    # NOT NULL in the canonical schema and on the API model; the mirror omitted
    # it, so any insert through this table (seeding, tests) failed. Read paths
    # were unaffected, which is why it went unnoticed.
    Column("label", String(120)),
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
    # NOT NULL in the canonical schema; omitted here, so inserts through this
    # mirror (seeding, tests) failed. Reads never touched it.
    Column("name", String(160)),
    Column("region_code", String(40)),
    Column("full_index_string", String(160)),
)

s3_profiles = Table(
    "s3_profiles",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(120)),
    Column("bucket", String(255)),
    Column("region", String(40)),
    Column("prefix", String(255)),
    Column("endpoint_url", Text),
    Column("encrypted_access_key_id", Text),
    Column("encrypted_secret_access_key", Text),
    Column("encrypted_session_token", Text),
    Column("key_last4", String(8)),
    Column("force_path_style", Boolean),
)

# Snapshot of every Last9-vs-New Relic comparison run. Written by the API; the
# worker only prunes old rows so the table does not grow without bound.
comparison_runs = Table(
    "comparison_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("comparison_id", Integer),
    Column("created_at", DateTime(timezone=True)),
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


def claim_job(
    conn,
    job_id: int,
    *,
    reclaim_before=None,
    owner_id: str | None = None,
    ttl_seconds: int = 60,
    **values,
) -> int | None:
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
    # Queued work, or a job the reconciler already fenced. The discriminator
    # matters: a pre-P1 running row also has a NULL lease but a zero token, and
    # that row must NOT be stealable -- three regression tests exist for exactly
    # that. The reconciler bumps the token and clears the owner, so only a
    # fenced row matches (token > 0, no owner, no lease).
    claimable = or_(
        jobs.c.status == "queued",
        and_(
            jobs.c.status == "running",
            jobs.c.lease_expires_at.is_(None),
            jobs.c.owner_id.is_(None),
            func.coalesce(jobs.c.lease_token, 0) > 0,
        ),
    )
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

    # Cancelling intent wins over a claim, and every claim increments the
    # monotonic lease token. Callers treat a falsy return as "not ours", which
    # also matches the old bool contract.
    claimable = and_(claimable, jobs.c.cancel_requested_at.is_(None))

    result = conn.execute(
        jobs.update()
        .where(jobs.c.id == job_id, claimable)
        .values(
            status="running",
            owner_id=owner_id,
            # coalesce: rows created before the column existed hold NULL.
            lease_token=func.coalesce(jobs.c.lease_token, 0) + 1,
            # Python-side timestamp: portable across Postgres and the SQLite
            # test database (SQLite has no interval arithmetic).
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=int(ttl_seconds)),
            heartbeat_at=func.now(),
            progress_at=func.now(),
            **values,
        )
        .returning(jobs.c.lease_token)
    )
    row = result.first()
    return int(row[0]) if row is not None and row[0] is not None else None


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
