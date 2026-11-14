"""Pydantic request/response models. Token plaintext is never echoed back —
credentials expose only a masked preview and a derived status."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    # Quoted phrases matched adjacently (sent as regexes); see pipeline.py.
    exact_phrases: list[str] = []
    # Logs containing any of these are excluded ($notcontains / $notregex).
    exclude_phrases: list[str] = []
    exclude_exact_phrases: list[str] = []
    message_types: list[str] = []
    aggregation: AggregationSpec | None = None
    customer: str = ""
    # Remembered source: the search this was built for. All optional — a
    # search without one behaves as before (source picked at run time).
    credential_id: int | None = None
    region_code: str | None = None
    index_target_id: int | None = None
    # Optional default destination for jobs created from this search.
    s3_profile_id: int | None = None


class FilterTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phrases: list[str]
    ids: list[str]
    exact_phrases: list[str] = []
    exclude_phrases: list[str] = []
    exclude_exact_phrases: list[str] = []
    message_types: list[str]
    aggregation: dict | None = None
    customer: str | None = None
    credential_id: int | None = None
    region_code: str | None = None
    index_target_id: int | None = None
    s3_profile_id: int | None = None
    s3_profile_label: str | None = None
    created_by: str | None
    created_at: datetime


# ── S3 destinations ──────────────────────────────────────────────────────────


class S3ProfileRef(BaseModel):
    """Portable reference used by job/schedule exports."""

    name: str


class S3ProfileCreate(BaseModel):
    name: str
    bucket: str
    region: str = "us-east-1"
    prefix: str = ""
    endpoint_url: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    session_token: str | None = None
    force_path_style: bool = False


class S3ProfileUpdate(BaseModel):
    name: str | None = None
    bucket: str | None = None
    region: str | None = None
    prefix: str | None = None
    endpoint_url: str | None = None
    # Omitted/blank keeps the stored keys. Both must be supplied to replace them.
    access_key_id: str | None = None
    secret_access_key: str | None = None
    session_token: str | None = None
    # Switch to the worker's IAM role / default credential chain.
    clear_credentials: bool = False
    force_path_style: bool | None = None


class S3ProfileOut(BaseModel):
    id: int
    name: str
    bucket: str
    region: str
    prefix: str
    endpoint_url: str | None
    key_preview: str | None
    force_path_style: bool
    created_by: str | None
    created_at: datetime


class S3TestResult(BaseModel):
    ok: bool
    message: str


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
    # False = parse only: match and write the extracted fields, but do not group
    # or count distinct values. Default True keeps every existing job/schedule/
    # search exactly as it was.
    aggregate: bool = True
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


# ── auto-detect ──────────────────────────────────────────────────────────────


class LogFormatDetectRequest(BaseModel):
    """Lines pasted from a real stream. Each is tried against every saved pattern."""

    lines: list[str]


class DetectedField(BaseModel):
    name: str
    # How many of the candidate's matched lines actually produced a value — a
    # field present on 2 of 20 lines is a bad column to count on.
    coverage: int
    distinct: int
    sample: str
    # Loose heuristic from the pasted sample: low cardinality reads as a
    # grouping key, high cardinality as something worth counting.
    suggested: Literal["group_by", "unique", "none"] = "none"


class DetectedCandidate(BaseModel):
    source: Literal["library", "saved_search"]
    id: int
    name: str
    regex: str
    hint: str | None
    priority: int
    matched: int
    fields: list[DetectedField]
    suggested_group_by: list[str]
    suggested_unique: list[str]


class InferredPattern(BaseModel):
    """A pattern derived from the pasted lines, not from anything saved."""

    regex: str
    fields: list[DetectedField]
    suggested_group_by: list[str]
    suggested_unique: list[str]
    lines_used: int


class LogFormatDetectResult(BaseModel):
    lines_analyzed: int
    matched: int
    unmatched: int
    candidates: list[DetectedCandidate]
    # Keys found when a line is JSON - offered when no saved pattern fits.
    json_fields: list[DetectedField] = []
    # A pattern built from the pasted lines themselves, offered when nothing
    # saved fits and the lines are not JSON.
    inferred: InferredPattern | None = None
    message: str | None = None


class JobDetectResult(LogFormatDetectResult):
    """Detection run against a real job's unmatched lines, not a paste."""

    job_id: int
    job_label: str = ""
    customer: str = ""
    unmatched_total: int = 0
    # "stored samples" or "unmatched artifact" - what was actually analyzed.
    source: str = ""


class JobLearnRequest(BaseModel):
    """Save a learned pattern to Log formats.

    `regex` lets the operator keep a candidate the detector offered (or edit the
    inferred one) before saving; empty means use the inferred pattern.
    """

    name: str = ""
    regex: str | None = None


class JobLearnResult(BaseModel):
    format: LogFormatOut
    detection: JobDetectResult
    created: bool


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
    # Quoted phrases matched adjacently (sent as regexes); see pipeline.py.
    exact_phrases: list[str] = []
    exclude_phrases: list[str] = []
    exclude_exact_phrases: list[str] = []
    message_types: list[str] = []
    output_format: Literal["csv", "jsonl"] = "csv"
    is_preview: bool = False
    aggregation: AggregationSpec | None = None
    # Name of the saved search this job came from. Used to name the downloads,
    # so a file is identifiable as "which search, which window" on its own.
    label: str = ""
    # Groups the output files into one folder per customer.
    customer: str = ""
    # Optional S3 delivery. The worker uploads once the extraction completes.
    s3_profile_id: int | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int | None = None
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
    has_unmatched: bool = False
    unmatched_url: str | None = None
    s3_profile_id: int | None = None
    s3_destination: dict | None = None
    s3_uri: str | None = None
    s3_summary_uri: str | None = None
    s3_counts_uri: str | None = None
    s3_error: str | None = None
    s3_uploaded_at: datetime | None = None


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
    # Quoted phrases matched adjacently (sent as regexes); see pipeline.py.
    exact_phrases: list[str] = []
    exclude_phrases: list[str] = []
    exclude_exact_phrases: list[str] = []
    message_types: list[str] = []
    aggregation: AggregationSpec | None = None
    s3_profile: S3ProfileRef | None = None


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
    """Run several saved searches over the same window - e.g. month-end, when
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


GroupStatus = Literal["queued", "running", "completed", "partial", "failed", "canceled"]


class GroupCreate(BatchCreate):
    """A named group extraction. Identical selection/window rules as a batch;
    the name is what the operator sees on the Groups page."""

    name: str = ""


class GroupSummary(BaseModel):
    id: int
    name: str
    status: GroupStatus
    created_by: str | None
    created_at: datetime
    start_epoch: int
    end_epoch: int
    is_preview: bool
    parent_group_id: int | None = None
    total_jobs: int
    completed: int
    failed: int
    canceled: int
    running: int
    queued: int
    rows_written: int


class GroupDetail(GroupSummary):
    jobs: list[JobOut]


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


class JobStats(BaseModel):
    """Server-side aggregates, so headline numbers are not capped by the list
    page size. The UI used to sum the first 200 rows and present it as a total."""

    total: int
    # Real extractions only; previews are counted separately.
    rows_written: int
    by_status: dict[str, int]
    previews: int


class CustomerDeleteResult(BaseModel):
    customer: str
    deleted_jobs: int
    deleted_files: int


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
    # Quoted phrases matched adjacently (sent as regexes); see pipeline.py.
    exact_phrases: list[str] = []
    exclude_phrases: list[str] = []
    exclude_exact_phrases: list[str] = []
    enabled: bool = True
    aggregation: AggregationSpec | None = None
    customer: str = ""
    alert_recipients: list[str] = []
    bq_config: BQConfig | None = None
    s3_profile_id: int | None = None


class ScheduleUpdate(BaseModel):
    name: str | None = None
    interval_seconds: int | None = None
    lookback_seconds: int | None = None
    calendar_day: bool | None = None
    phrases: list[str] | None = None
    ids: list[str] | None = None
    exclude_phrases: list[str] | None = None
    exclude_exact_phrases: list[str] | None = None
    aggregation: AggregationSpec | None = None
    alert_recipients: list[str] | None = None
    bq_config: BQConfig | None = None
    s3_profile_id: int | None = None


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
    s3_profile_id: int | None = None
    s3_profile_label: str | None = None
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
    # Quoted phrases matched adjacently (sent as regexes); see pipeline.py.
    exact_phrases: list[str] = []
    exclude_phrases: list[str] = []
    exclude_exact_phrases: list[str] = []
    customer: str = ""
    aggregation: AggregationSpec | None = None
    alert_recipients: list[str] = []
    bq_config: BQConfig | None = None
    s3_profile: S3ProfileRef | None = None


class SettingsOut(BaseModel):
    environment: str
    default_org_slug: str
    storage_dir: str
    export_retention_days: int
    download_url_ttl_seconds: int
    region_count: int


# ── New Relic connections ─────────────────────────────────────────────────────


class NewRelicCredentialCreate(BaseModel):
    label: str
    account_id: int
    region: Literal["us", "eu"] = "us"
    api_key: str


class NewRelicCredentialOut(BaseModel):
    id: int
    label: str
    account_id: int
    region: str
    api_key_preview: str
    created_by: str | None
    created_at: datetime


class NewRelicCredentialUpdate(BaseModel):
    label: str | None = None
    account_id: int | None = None
    region: Literal["us", "eu"] | None = None
    # Blank/omitted keeps the stored key.
    api_key: str | None = None


class NewRelicTestResult(BaseModel):
    ok: bool
    message: str
    account_name: str | None = None


# ── comparisons ───────────────────────────────────────────────────────────────


class Last9FilterSpec(BaseModel):
    """The same phrase/ID/exact-phrase set the extraction wizard builds.

    Stored next to the resolved pipeline only so the comparison editor can
    reopen in builder mode. A hand-written pipeline has no filter_spec and
    opens straight in JSON mode.
    """

    phrases: list[str] = []
    ids: list[str] = []
    exact_phrases: list[str] = []
    message_types: list[str] = []


class ComparisonCreate(BaseModel):
    name: str
    description: str = ""
    last9_index_target_id: int
    # Usually derived from the index target, but accepted so a source without
    # a saved credential can still run.
    last9_credential_id: int | None = None
    last9_filter_spec: Last9FilterSpec | None = None
    # When set, this is the exact pipeline that runs (filters are ignored for
    # execution, but still stored for the editor when supplied).
    last9_pipeline: list[dict] | None = None
    nr_credential_id: int
    nrql: str
    nr_value_mode: Literal["sum", "avg", "max", "min", "last"] = "sum"
    nr_value_field: str | None = None
    bucket_seconds: int | None = None


class ComparisonSummaryOut(BaseModel):
    """List-view shape: enough to render a saved comparison without shipping
    its (potentially very large) pipeline/NRQL to every list request."""

    id: int
    name: str
    description: str | None
    last9_credential_id: int
    last9_index_target_id: int
    last9_region_code: str
    nr_credential_id: int
    nr_value_mode: str
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    # Join labels for the list view, resolved in the router.
    last9_credential_label: str | None = None
    last9_index_name: str | None = None
    nr_credential_label: str | None = None
    nr_account_id: int | None = None
    last_run_at: datetime | None = None
    last_run_id: int | None = None
    last_run_status: str | None = None
    last_run_last9_total: float | None = None
    last_run_newrelic_total: float | None = None


class ComparisonOut(ComparisonSummaryOut):
    model_config = ConfigDict(from_attributes=True)

    last9_pipeline: list
    last9_filter_spec: dict | None
    nrql: str
    nr_value_field: str | None
    bucket_seconds: int | None


class ComparisonListOut(BaseModel):
    items: list[ComparisonSummaryOut]
    total: int
    limit: int
    offset: int


class ComparisonPoint(BaseModel):
    start_epoch: int
    end_epoch: int
    value: float


class ComparisonSideResult(BaseModel):
    ok: bool
    error: str | None = None
    elapsed_ms: int | None = None
    total: float | None = None
    series: list[ComparisonPoint] = []
    raw: list[dict] = []
    metadata: dict | None = None


class ComparisonRunRequest(BaseModel):
    start_epoch: int
    end_epoch: int
    bucket_seconds: int | None = None


class ComparisonRunSummary(BaseModel):
    id: int
    comparison_id: int
    start_epoch: int
    end_epoch: int
    bucket_seconds: int
    status: str
    last9_ok: bool
    last9_total: float | None
    newrelic_ok: bool
    newrelic_total: float | None
    created_by: str | None
    created_at: datetime


class ComparisonRunOut(ComparisonRunSummary):
    last9: ComparisonSideResult
    newrelic: ComparisonSideResult
    nrql_effective: str | None = None
    last9_pipeline_effective: dict | None = None
    # last9_total - newrelic_total, and that difference as a percentage of the
    # New Relic total. Null when either side failed or NR returned 0.
    delta: float | None = None
    pct_diff: float | None = None

# ---- Reporting -------------------------------------------------------------
# Scheduled-run reporting. Counts come from jobs the scheduler created
# (`created_by = "schedule:<id>"`), grouped by the UTC day the run started.

ReportDayStatus = Literal[
    "ok", "failed", "running", "canceled", "partial", "missed", "pending", "off", "none"
]


class ReportSettingsOut(BaseModel):
    retention_days: int
    updated_at: datetime | None = None
    updated_by: str | None = None


class ReportSettingsUpdate(BaseModel):
    retention_days: int = Field(ge=1, le=365)


class ReportDayOut(BaseModel):
    date: str  # YYYY-MM-DD
    status: ReportDayStatus
    rows: int
    runs: int
    completed: int
    failed: int


class ReportTotalsOut(BaseModel):
    customers: int
    schedules: int
    enabled_schedules: int
    runs_today: int
    completed_today: int
    failed_today: int
    active_today: int
    rows_today: int
    rows_yesterday: int
    rows_last_week: int
    pct_vs_yesterday: float | None
    pct_vs_last_week: float | None
    success_rate_today: float | None


class ReportScheduleOut(BaseModel):
    schedule_id: int | None
    name: str
    customer: str
    enabled: bool
    interval_seconds: int | None
    calendar_day: bool
    source: str | None
    last_run_at: datetime | None
    latest_job_id: int | None
    today_status: ReportDayStatus
    today_rows: int
    yesterday_rows: int
    last_week_rows: int
    pct_vs_yesterday: float | None
    pct_vs_last_week: float | None
    pct_yesterday_vs_last_week: float | None
    failed_today: int
    days: list[ReportDayOut]


class ReportCustomerOut(BaseModel):
    customer: str
    schedules: list[ReportScheduleOut]
    rows_today: int
    rows_yesterday: int
    rows_last_week: int
    pct_vs_yesterday: float | None
    pct_vs_last_week: float | None
    failed_today: int


class ReportAlertOut(BaseModel):
    kind: Literal["failed", "missed"]
    customer: str
    job_name: str
    schedule_id: int | None
    job_id: int | None
    at: datetime | None
    error: str | None
    occurrences: int
    recipients: list[str]


class ReportOut(BaseModel):
    generated_at: datetime
    retention_days: int
    window_days: int
    timezone: str
    totals: ReportTotalsOut
    customers: list[ReportCustomerOut]
    alerts: list[ReportAlertOut]
