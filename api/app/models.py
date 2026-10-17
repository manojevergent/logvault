"""ORM models for credentials and index targets (CLAUDE_CODE_PROMPT.md §4).

ponytail: created_by is a plain email string, not a users FK — auth/users land in
Phase 6. Add the FK then.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Last9Credential(Base):
    __tablename__ = "last9_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    org_slug: Mapped[str] = mapped_column(String(120))
    encrypted_refresh_token: Mapped[str] = mapped_column(Text)
    refresh_token_last4: Mapped[str] = mapped_column(String(8))
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    owner_scope: Mapped[str] = mapped_column(String(20), default="shared")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Job lifecycle: queued -> running -> (paused <-> running) -> completed|failed|canceled
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    region_code: Mapped[str] = mapped_column(String(40))
    index_target_id: Mapped[int] = mapped_column(Integer)
    credential_id: Mapped[int] = mapped_column(Integer)
    start_epoch: Mapped[int] = mapped_column(BigInteger)
    end_epoch: Mapped[int] = mapped_column(BigInteger)
    chunk_hours: Mapped[float] = mapped_column(Integer, default=1)
    id_batch_size: Mapped[int] = mapped_column(Integer, default=100)
    filter_spec: Mapped[dict] = mapped_column(JSON, default=dict)  # {phrases:[], ids:[]}
    rows_written: Mapped[int] = mapped_column(BigInteger, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    completed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    current_chunk_start: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checkpoint: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full per-group unique counts (the aggregation_result column is capped for display).
    summary_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-value occurrence counts, most frequent first (the pivot-table view).
    counts_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set => this job merges other jobs' distinct-value stores instead of
    # querying Last9: {"schedule_id": N, "job_ids": [...], "label": "2026-08"}.
    rollup_of: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_format: Mapped[str] = mapped_column(String(10), default="csv")  # csv | jsonl
    is_preview: Mapped[bool] = mapped_column(Boolean, default=False)
    preview: Mapped[list | None] = mapped_column(JSON, nullable=True)  # first ~20 rows
    aggregation_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text)
    rows_delta: Mapped[int] = mapped_column(Integer, default=0)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Recurring extraction. ponytail: interval-based (every N seconds), no cron parser.
# Each run creates a job over [now - lookback_seconds, now].
class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer)
    lookback_seconds: Mapped[int] = mapped_column(Integer)
    # True: window is always the previous full IST calendar day (00:00-23:59),
    # not a rolling lookback from run time; lookback_seconds is ignored.
    calendar_day: Mapped[bool] = mapped_column(Boolean, default=False)
    region_code: Mapped[str] = mapped_column(String(40))
    index_target_id: Mapped[int] = mapped_column(Integer)
    credential_id: Mapped[int] = mapped_column(Integer)
    chunk_hours: Mapped[int] = mapped_column(Integer, default=1)
    id_batch_size: Mapped[int] = mapped_column(Integer, default=100)
    output_format: Mapped[str] = mapped_column(String(10), default="csv")
    filter_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    alert_recipients: Mapped[list] = mapped_column(
        JSON, default=list
    )  # email addresses to notify on failure
    bq_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# A named parse pattern. Jobs try every enabled format against each row until
# one matches, so a mixed stream needs no per-job regex — adding a format here
# makes every future job understand that shape.
class LogFormat(Base):
    __tablename__ = "log_formats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    regex: Mapped[str] = mapped_column(Text)
    # A literal every line of this format contains. Tested before the regex is
    # run, which is what makes trying hundreds of formats per row affordable.
    hint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sample_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Lower is tried first: the first match wins, so a narrow format needs to be
    # able to outrank a broader one that would also match.
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    # NULL for accounts that only ever signed in via Google — the password
    # login path rejects those explicitly rather than letting passlib choke.
    hashed_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # admin | member
    # "password" | "google": how the account was created. A password account
    # that later signs in with Google keeps working both ways.
    auth_provider: Mapped[str] = mapped_column(String(20), default="password")
    # Google's stable `sub` for the account, stamped on first Google sign-in.
    # Lookup key when present, so a changed Gmail address doesn't orphan the
    # account (or collide with someone else's). NULL until first Google login.
    oauth_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndexTarget(Base):
    __tablename__ = "index_targets"
    __table_args__ = (UniqueConstraint("region_code", "name", name="uq_index_region_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The profile label a user picks from, e.g. "UMS_india".
    name: Mapped[str] = mapped_column(String(120))
    region_code: Mapped[str] = mapped_column(String(40))
    # The real Last9 index, e.g. "UMServices". Separate from `name` because the
    # label is free text: deriving full_index_string from it would point a
    # renamed profile at an index that doesn't exist.
    physical_index: Mapped[str | None] = mapped_column(String(120), nullable=True)
    full_index_string: Mapped[str] = mapped_column(String(160))
    # The credential this source is read with. Nullable so targets predating
    # profiles still work — the job form asks for one when it is unset.
    credential_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# "Save the search" — a named phrase/ID/message-type set, loadable into a new
# job or schedule instead of retyping. The filter itself stays source-free (a
# template applies to any source), but each search remembers the source it was
# built for — credential, region, index — so batch runs and the wizard come
# pre-filled instead of asking every time. All three nullable for searches
# saved before sources were remembered.
class FilterTemplate(Base):
    __tablename__ = "filter_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    phrases: Mapped[list] = mapped_column(JSON, default=list)
    ids: Mapped[list] = mapped_column(JSON, default=list)
    message_types: Mapped[list] = mapped_column(JSON, default=list)
    credential_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    index_target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Groups this search's extracts into one folder. Free text, sanitised to a
    # single path segment before it ever reaches the filesystem.
    customer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The parse & aggregate config (regex + group_by + unique_fields), stored
    # whole because the parts are useless apart: group_by names have to be groups
    # the regex actually defines.
    aggregation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Runtime settings the admin UI can change, one row per group (currently just
# "notifications"). Schemaless on purpose: adding an SMTP field needs no
# migration. Secrets inside `value` are Fernet-encrypted before they get here.
class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
