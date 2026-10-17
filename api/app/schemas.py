"""Pydantic request/response models. Token plaintext is never echoed back —
credentials expose only a masked preview and a derived status."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class BQConfig(BaseModel):
    project_id: str
    dataset_id: str
    table_id: str
    credentials_json: str | None = None  # None = use ADC


class CredentialRef(BaseModel):
    """Points at a credential/index by name instead of database id, so an
    exported job/schedule can be resolved in a different environment where the
    ids won't match."""

    label: str
    org_slug: str


class IndexRef(BaseModel):
    name: str
    region_code: str


class CredentialCreate(BaseModel):
    label: str
    org_slug: str
    refresh_token: str
    access_token: str | None = None  # optional initial cached token
    owner_scope: Literal["shared", "personal"] = "shared"


class CredentialOut(BaseModel):
    id: int
    label: str
    org_slug: str
    owner_scope: str
    created_by: str | None
    created_at: datetime
    refresh_token_preview: str
    access_token_expires_at: int | None
    token_status: Literal["valid", "expiring", "expired", "unknown"]


class TestConnectionResult(BaseModel):
    ok: bool
    message: str
    token_status: Literal["valid", "expiring", "expired", "unknown"]
    expires_at: int | None = None


class IndexCreate(BaseModel):
    """A source profile: label + region + physical index + credential."""

    name: str
    region_code: str
    # Defaults to `name` when omitted, which is how targets behaved before the
    # label and the physical index were separable. An explicit blank ("")
    # selects the org's Default index instead (worker sends no `index` param).
    physical_index: str | None = None
    credential_id: int | None = None
    description: str | None = None


class IndexUpdate(BaseModel):
    name: str | None = None
    physical_index: str | None = None
    credential_id: int | None = None
    description: str | None = None


class IndexOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    region_code: str
    physical_index: str | None
    credential_id: int | None
    credential_label: str | None = None
    full_index_string: str
    description: str | None
    created_by: str | None
    created_at: datetime


class RegionOut(BaseModel):
    code: str
    label: str


class FilterTemplateCreate(BaseModel):
    name: str
    phrases: list[str] = []
    ids: list[str] = []
    message_types: list[str] = []
    aggregation: AggregationSpec | None = None
    customer: str = ""
    # Remembered source: the search this was built for. All optional — a
    # search without one behaves as before (source picked at run time).
    credential_id: int | None = None
    region_code: str | None = None
    index_target_id: int | None = None


class FilterTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phrases: list[str]
    ids: list[str]
    message_types: list[str]
    aggregation: dict | None = None
    customer: str | None = None
    credential_id: int | None = None
    region_code: str | None = None
    index_target_id: int | None = None
    created_by: str | None
    created_at: datetime


# ── jobs ──────────────────────────────────────────────────────────────────────

JobStatus = Literal["queued", "running", "paused", "completed", "failed", "canceled"]


class AggregationSpec(BaseModel):
    """Parse each row's message with `regex`, group by `group_by` (named
    groups), and count DISTINCT values of each of `unique_fields` — any number
    of attributes, not just one, e.g. unique SPID *and* unique tracker ID."""

    enabled: bool = False
    regex: str = ""
    group_by: list[str] = []
    unique_fields: list[str] = []
    skip_raw_output: bool = False
    # Try every enabled format in the Log Formats library instead of `regex`.
    use_library: bool = False
    # Exact columns (and order) for the raw export, independent of group_by/
    # unique_fields. Empty means the default: [log_format, *group_by, *unique_fields].
    raw_columns: list[str] = []
    # Literal fallback for a raw_columns entry with no real data in a given
    # row — either it's not a named group in the regex at all, or the group
    # matched empty. Exempt from the "regex has no named group" check.
    raw_column_defaults: dict[str, str] = {}
    # False drops the leading `log_format` column (which pattern matched) from
    # the raw export — only meaningful in the implicit default column set;
    # raw_columns, when set explicitly, already omits it unless named there.
    include_log_format: bool = True
    # False drops the trailing `message` column from the raw export.
    include_message: bool = True
    # Rename a parsed field's CSV header independent of what the regex calls
    # it — e.g. two searches whose regexes name the same concept `spid` and
    # `channelPartnerId` can both emit a `spAccountID` column. Values are
    # still looked up by the regex's own name; only the header text changes.
    column_labels: dict[str, str] = {}
    # Header text for the raw export's timestamp column.
    timestamp_column: str = "timestamp_utc"


class LogFormatCreate(BaseModel):
    name: str
    regex: str
    # A literal every line of this format contains. Checked before the regex is
    # run, which is what keeps "try every format on every row" affordable.
    hint: str = ""
    sample_line: str = ""
    # Lower is tried first: first match wins, so a narrow format needs to be able
    # to outrank a broader one that would also match.
    priority: int = 100
    enabled: bool = True
    description: str = ""


class LogFormatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    regex: str
    hint: str | None
    sample_line: str | None
    priority: int
    enabled: bool
    description: str | None
    created_at: datetime


class LogFormatTestRequest(BaseModel):
    regex: str
    sample_line: str
    hint: str = ""


class LogFormatTestResult(BaseModel):
    matched: bool
    error: str | None
    fields: dict[str, str]


class JobCreate(BaseModel):
    credential_id: int
    index_target_id: int
    region_code: str
    start_epoch: int
    end_epoch: int
    chunk_hours: int = 1
    id_batch_size: int = 100
    phrases: list[str] = []
    ids: list[str] = []
    message_types: list[str] = []
    output_format: Literal["csv", "jsonl"] = "csv"
    is_preview: bool = False
    aggregation: AggregationSpec | None = None
    # Name of the saved search this job came from. Used to name the downloads,
    # so a file is identifiable as "which search, which window" on its own.
    label: str = ""
    # Groups the output files into one folder per customer.
    customer: str = ""


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: JobStatus
    region_code: str
    index_target_id: int
    credential_id: int
    start_epoch: int
    end_epoch: int
    chunk_hours: int
    id_batch_size: int
    filter_spec: dict
    rows_written: int
    total_chunks: int
    completed_chunks: int
    current_chunk_start: int | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    output_format: str = "csv"
    is_preview: bool = False
    preview: list | None = None
    aggregation_result: dict | None = None
    has_output: bool = False
    download_url: str | None = None
    progress_url: str | None = None
    credential_label: str | None = None
    output_size_bytes: int | None = None
    # "schedule:<id>" for beat-created runs, which is how the dashboard tells
    # scheduled runs from ones a person started.
    created_by: str | None = None
    rollup_of: dict | None = None
    has_summary: bool = False
    summary_url: str | None = None
    has_counts: bool = False
    counts_url: str | None = None


class JobExport(BaseModel):
    """Portable job config: importable in any environment that has a matching
    credential and index target already set up (see CredentialRef/IndexRef)."""

    kind: Literal["job"] = "job"
    label: str = ""
    customer: str = ""
    region_code: str
    index: IndexRef
    credential: CredentialRef
    start_epoch: int
    end_epoch: int
    # float: mirrors Job.chunk_hours, which the worker adapts to a fraction of
    # an hour mid-run (see runner.py) — exporting a job caught mid-adaptation
    # shouldn't fail just because its current value isn't a whole hour.
    chunk_hours: float = 1
    id_batch_size: int = 100
    # Not Literal: this type is also the raw export's on-disk shape, so a
    # hand-edited file with a bad value 422s from import_job's own check
    # instead of a less legible error straight out of Pydantic.
    output_format: str = "csv"
    phrases: list[str] = []
    ids: list[str] = []
    message_types: list[str] = []
    aggregation: AggregationSpec | None = None


class BatchItem(BaseModel):
    """One saved search in a batch run, pinned to its source.

    Each entry may name its own source, or leave it blank to use the search's
    remembered source (set where the search was built or edited). At least one
    of the two must resolve, or the batch 422s naming the search.
    """

    template_id: int
    credential_id: int | None = None
    index_target_id: int | None = None
    region_code: str | None = None


class BatchCreate(BaseModel):
    """Run several saved searches over the same window — e.g. month-end, when
    every invoice search extracts the same 24h. One job per item, created
    atomically: any invalid entry 422s the whole batch before anything queues.
    """

    items: list[BatchItem]
    start_epoch: int
    end_epoch: int
    chunk_hours: int = 1
    id_batch_size: int = 100
    output_format: Literal["csv", "jsonl"] = "csv"
    is_preview: bool = False


class RollupCreate(BaseModel):
    """Merge a schedule's completed runs over [start_epoch, end_epoch) into one
    job whose unique counts are exact across the whole period."""

    schedule_id: int
    start_epoch: int
    end_epoch: int
    label: str = ""


class JobEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    level: str
    message: str
    rows_delta: int


# ── admin ─────────────────────────────────────────────────────────────────────


class AuditOut(BaseModel):
    id: int
    user_id: str | None
    action: str
    entity: str
    entity_id: int | None
    metadata: dict | None
    ts: datetime


class UserCreate(BaseModel):
    email: str
    name: str
    password: str
    role: Literal["admin", "member"] = "member"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    role: str
    created_at: datetime


class ScheduleCreate(BaseModel):
    name: str
    interval_seconds: int
    lookback_seconds: int
    calendar_day: bool = False
    credential_id: int
    index_target_id: int
    region_code: str
    chunk_hours: int = 1
    id_batch_size: int = 100
    output_format: Literal["csv", "jsonl", "bigquery"] = "csv"
    phrases: list[str] = []
    ids: list[str] = []
    enabled: bool = True
    aggregation: AggregationSpec | None = None
    customer: str = ""
    alert_recipients: list[str] = []
    bq_config: BQConfig | None = None


class ScheduleUpdate(BaseModel):
    name: str | None = None
    interval_seconds: int | None = None
    lookback_seconds: int | None = None
    calendar_day: bool | None = None
    phrases: list[str] | None = None
    ids: list[str] | None = None
    aggregation: AggregationSpec | None = None
    alert_recipients: list[str] | None = None
    bq_config: BQConfig | None = None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    enabled: bool
    interval_seconds: int
    lookback_seconds: int
    calendar_day: bool
    region_code: str
    index_target_id: int
    credential_id: int
    chunk_hours: int
    id_batch_size: int
    output_format: str
    filter_spec: dict
    alert_recipients: list[str]
    bq_config: BQConfig | None = None
    last_run_at: datetime | None
    created_at: datetime
    last_run_job_id: int | None = None


class ScheduleExport(BaseModel):
    """Portable schedule config — see JobExport."""

    kind: Literal["schedule"] = "schedule"
    name: str
    enabled: bool = True
    interval_seconds: int
    lookback_seconds: int
    calendar_day: bool = False
    region_code: str
    index: IndexRef
    credential: CredentialRef
    chunk_hours: int = 1
    id_batch_size: int = 100
    # Not Literal — see JobExport.output_format.
    output_format: str = "csv"
    phrases: list[str] = []
    ids: list[str] = []
    customer: str = ""
    aggregation: AggregationSpec | None = None
    alert_recipients: list[str] = []
    bq_config: BQConfig | None = None


class SettingsOut(BaseModel):
    environment: str
    default_org_slug: str
    storage_dir: str
    export_retention_days: int
    download_url_ttl_seconds: int
    region_count: int
