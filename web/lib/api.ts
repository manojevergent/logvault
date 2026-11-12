import * as React from "react";

/** Thin client for the LogVault API. Expanded in later phases. */

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type ReadyStatus = {
  status: "ok" | "degraded";
  checks: Record<string, string>;
};

export async function fetchReady(signal?: AbortSignal): Promise<ReadyStatus> {
  const res = await fetch(`${API_BASE}/ready`, { signal, cache: "no-store" });
  if (!res.ok) throw new Error(`API readiness check failed (${res.status})`);
  return res.json();
}

// ── auth token storage ───────────────────────────────────────────────────────

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("lv_token");
}

export function setToken(token: string, role: string): void {
  localStorage.setItem("lv_token", token);
  localStorage.setItem("lv_role", role);
  // Secure only over HTTPS: setting it unconditionally would silently drop the
  // cookie on a plain-HTTP deployment and break sign-in with no error.
  const secure =
    typeof location !== "undefined" && location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `lv_token=${token}; path=/; SameSite=Strict; max-age=86400${secure}`;
}

export function clearToken(): void {
  localStorage.removeItem("lv_token");
  localStorage.removeItem("lv_role");
  document.cookie = "lv_token=; path=/; max-age=0";
}

export function getRole(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("lv_role");
}

/** The signed-in role, for gating UI. Starts null so the server render and the
 *  first client render agree — reading localStorage during render makes the two
 *  trees differ and React discards the server HTML (hydration error #418).
 *  Mirrors the useTz pattern in lib/time.ts. */
export function useRole(): string | null {
  const [role, setRole] = React.useState<string | null>(null);
  React.useEffect(() => setRole(getRole()), []);
  return role;
}

// ── generic JSON helper ──────────────────────────────────────────────────────

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    cache: "no-store",
    ...init,
  });
  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `Request failed (${res.status})`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

// ── credentials ──────────────────────────────────────────────────────────────

export type TokenStatus = "valid" | "expiring" | "expired" | "unknown";

export type Credential = {
  id: number;
  label: string;
  org_slug: string;
  owner_scope: string;
  created_by: string | null;
  created_at: string;
  refresh_token_preview: string;
  access_token_expires_at: number | null;
  token_status: TokenStatus;
};

export type CredentialInput = {
  label: string;
  org_slug: string;
  refresh_token: string;
  owner_scope: "shared" | "personal";
};

export type TestResult = {
  ok: boolean;
  message: string;
  token_status: TokenStatus;
  expires_at: number | null;
};

export const listCredentials = () => req<Credential[]>("/credentials");
export const createCredential = (body: CredentialInput) =>
  req<Credential>("/credentials", { method: "POST", body: JSON.stringify(body) });
export const deleteCredential = (id: number) =>
  req<void>(`/credentials/${id}`, { method: "DELETE" });
export const testCredential = (id: number) =>
  req<TestResult>(`/credentials/${id}/test`, { method: "POST" });

// ── regions & indexes ────────────────────────────────────────────────────────

export type Region = { code: string; label: string };

/** A source profile: label + region + physical index + credential, so a job
 *  picks one thing instead of three. */
export type IndexTarget = {
  id: number;
  name: string;
  region_code: string;
  /** The real Last9 index; `name` is just the label. */
  physical_index: string | null;
  credential_id: number | null;
  credential_label: string | null;
  full_index_string: string;
  description: string | null;
  created_by: string | null;
  created_at: string;
};

export type IndexInput = {
  name: string;
  region_code: string;
  physical_index?: string | null;
  credential_id?: number | null;
  description?: string | null;
};

export const listRegions = () => req<Region[]>("/regions");
export const listIndexes = (region?: string) =>
  req<IndexTarget[]>(`/indexes${region ? `?region=${encodeURIComponent(region)}` : ""}`);
export const createIndex = (body: IndexInput) =>
  req<IndexTarget>("/indexes", { method: "POST", body: JSON.stringify(body) });
export const updateIndex = (
  id: number,
  body: {
    name?: string;
    physical_index?: string | null;
    credential_id?: number | null;
    description?: string | null;
  }
) => req<IndexTarget>(`/indexes/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteIndex = (id: number) => req<void>(`/indexes/${id}`, { method: "DELETE" });

// ── filter templates ("save the search") ────────────────────────────────────

export type FilterTemplate = {
  id: number;
  name: string;
  phrases: string[];
  ids: string[];
  /** Quoted phrases matched adjacently (sent as regexes). */
  exact_phrases?: string[];
  /** Logs containing any of these are excluded. */
  exclude_phrases?: string[];
  exclude_exact_phrases?: string[];
  message_types: string[];
  /** Saved parse & aggregate config — the regex comes back with the search. */
  aggregation: AggregationSpec | null;
  /** Extracts from this search land in this customer's folder. */
  customer: string | null;
  /** Remembered source — null when the search predates source memory. */
  credential_id: number | null;
  region_code: string | null;
  index_target_id: number | null;
  /** Optional default S3 destination for jobs created from this search. */
  s3_profile_id: number | null;
  s3_profile_label?: string | null;
  created_by: string | null;
  created_at: string;
};

export type FilterTemplateInput = {
  name: string;
  phrases: string[];
  ids: string[];
  /** Quoted phrases matched adjacently (sent as regexes). */
  exact_phrases?: string[];
  /** Logs containing any of these are excluded. */
  exclude_phrases?: string[];
  exclude_exact_phrases?: string[];
  message_types: string[];
  aggregation?: AggregationSpec | null;
  customer?: string;
  credential_id?: number | null;
  region_code?: string | null;
  index_target_id?: number | null;
  s3_profile_id?: number | null;
};

export const listTemplates = () => req<FilterTemplate[]>("/templates");
export const createTemplate = (body: FilterTemplateInput) =>
  req<FilterTemplate>("/templates", { method: "POST", body: JSON.stringify(body) });
export const updateTemplate = (id: number, body: FilterTemplateInput) =>
  req<FilterTemplate>(`/templates/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteTemplate = (id: number) => req<void>(`/templates/${id}`, { method: "DELETE" });

// ── jobs ──────────────────────────────────────────────────────────────────────

export type JobStatus = "queued" | "running" | "paused" | "completed" | "failed" | "canceled";

export type AggregationSpec = {
  enabled: boolean;
  /** False = parse only (extract fields, no group-by/distinct counts). */
  aggregate?: boolean;
  regex: string;
  group_by: string[];
  unique_fields: string[];
  skip_raw_output: boolean;
  /** Try every enabled format in the Log Formats library instead of `regex`. */
  use_library?: boolean;
  /** Exact columns (and order) for the raw export. Empty = the default
   *  [log_format, ...group_by, ...unique_fields]. */
  raw_columns?: string[];
  /** False drops the leading `log_format` column — only affects the implicit
   *  default column set above; an explicit raw_columns already omits it. */
  include_log_format?: boolean;
  /** False drops the `message` column from the raw export. */
  include_message?: boolean;
  /** Header text for the raw export's timestamp column. */
  timestamp_column?: string;
  /** Uniform CSV header per parsed field: regex group name -> header text.
   *  Values are still looked up by the regex's own name; only the header
   *  changes, so different shapes can emit the same column name. */
  column_labels?: Record<string, string>;
  /** Literal fallback per field when a row has no value (or the regex never
   *  defines the group) — e.g. "" or "-". */
  raw_column_defaults?: Record<string, string>;
};

export type AggregationResult = {
  group_by: string[];
  unique_fields: string[];
  rows_matched: number;
  rows_unmatched: number;
  // False for a parse-only run (regex extraction, no distinct counts).
  aggregate?: boolean;
  // First few unmatched lines, capped server-side; rows_unmatched is the total.
  unmatched_samples?: { timestamp: string; message: string }[];
  unmatched_sample_cap?: number;
  // groups is capped for display; total_groups is the real count. The complete
  // breakdown is the summary CSV (Job.summary_url).
  total_groups?: number;
  truncated?: boolean;
  groups: { key: Record<string, string>; unique_counts: Record<string, number> }[];
};

export type Job = {
  id: number;
  status: JobStatus;
  region_code: string;
  index_target_id: number;
  credential_id: number;
  start_epoch: number;
  end_epoch: number;
  chunk_hours: number;
  id_batch_size: number;
  filter_spec: {
    phrases: string[];
    ids: string[];
    exact_phrases?: string[];
    message_types?: string[];
    /** Logs containing any of these are excluded. */
    exclude_phrases?: string[];
    exclude_exact_phrases?: string[];
    aggregation?: AggregationSpec;
    /** Saved-search or schedule name; also names the downloads. */
    label?: string;
    /** Groups this job's output files into one folder per customer. */
    customer?: string;
  };
  rows_written: number;
  total_chunks: number;
  completed_chunks: number;
  current_chunk_start: number | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  output_format: string;
  is_preview: boolean;
  preview: { timestamp: string; message: string }[] | null;
  aggregation_result: AggregationResult | null;
  has_output: boolean;
  download_url: string | null;
  progress_url: string | null;
  credential_label: string | null;
  output_size_bytes: number | null;
  /** "schedule:<id>" for runs the beat created. */
  created_by: string | null;
  // Full per-group unique counts. aggregation_result above is capped for
  // display, so this is the authoritative breakdown once a job completes.
  has_summary: boolean;
  summary_url: string | null;
  // One row per distinct value with how many log lines it appeared in,
  // most frequent first — the pivot-table view, already pivoted.
  has_counts: boolean;
  counts_url: string | null;
  // Every row the parse pattern failed to match (timestamp,message). The
  // aggregation result only carries a small sample for display.
  has_unmatched: boolean;
  unmatched_url: string | null;
  s3_profile_id: number | null;
  s3_destination: {
    profile_id: number;
    name: string;
    bucket: string;
    region: string;
    prefix: string;
  } | null;
  s3_uri: string | null;
  s3_summary_uri: string | null;
  s3_counts_uri: string | null;
  s3_error: string | null;
  s3_uploaded_at: string | null;
  rollup_of: { schedule_id: number; label?: string; source_job_ids?: number[] } | null;
};

export type JobCreateInput = {
  credential_id: number;
  index_target_id: number;
  region_code: string;
  start_epoch: number;
  end_epoch: number;
  chunk_hours: number;
  id_batch_size: number;
  phrases: string[];
  ids: string[];
  /** Quoted phrases matched adjacently (sent as regexes). */
  exact_phrases?: string[];
  /** Logs containing any of these are excluded. */
  exclude_phrases?: string[];
  exclude_exact_phrases?: string[];
  message_types?: string[];
  output_format?: "csv" | "jsonl" | "bigquery";
  is_preview?: boolean;
  /** Saved-search name; names the downloads `<label>_<job id>_<timeframe>.csv`. */
  label?: string;
  /** Groups the output files into one folder per customer. */
  customer?: string;
  /** Optional S3 destination profile. */
  s3_profile_id?: number | null;
  aggregation?: (Omit<AggregationSpec, "skip_raw_output"> & { skip_raw_output?: boolean }) | null;
};

export const JOB_TONE: Record<JobStatus, "neutral" | "info" | "warning" | "success" | "danger"> = {
  queued: "neutral",
  running: "info",
  paused: "warning",
  completed: "success",
  failed: "danger",
  canceled: "neutral",
};

// Bounded by default. The list is polled every few seconds by every open tab,
// list responses omit `preview`/`aggregation_result`/`rollup_of` and carry
// only the label+customer keys of `filter_spec` — use getJob() for the rest.
// Filter-test previews are excluded unless asked (see the Previews tab).
export type ListJobsOptions = {
  includePreviews?: boolean;
  previewsOnly?: boolean;
  offset?: number;
  status?: JobStatus;
};

export const listJobs = (limit = 200, opts: ListJobsOptions | boolean = {}) => {
  // Boolean form kept for the older `listJobs(limit, true)` call site.
  const o: ListJobsOptions = typeof opts === "boolean" ? { includePreviews: opts } : opts;
  const q = new URLSearchParams({ limit: String(limit) });
  if (o.includePreviews) q.set("include_previews", "true");
  if (o.previewsOnly) q.set("previews_only", "true");
  if (o.offset) q.set("offset", String(o.offset));
  if (o.status) q.set("status", o.status);
  return req<Job[]>(`/jobs?${q.toString()}`);
};

export type JobStats = {
  total: number;
  rows_written: number;
  by_status: Record<string, number>;
  previews: number;
};

/** True totals across the whole table — the list itself is page-limited. */
export const getJobStats = () => req<JobStats>("/jobs/stats");

export type CustomerDeleteResult = {
  customer: string;
  deleted_jobs: number;
  deleted_files: number;
};

/** A customer is a label on jobs — deleting one deletes its jobs and files. */
export const deleteCustomer = (name: string) =>
  req<CustomerDeleteResult>(`/customers?name=${encodeURIComponent(name)}`, { method: "DELETE" });

export const getJob = (id: number) => req<Job>(`/jobs/${id}`);
export const createJob = (body: JobCreateInput) =>
  req<Job>("/jobs", { method: "POST", body: JSON.stringify(body) });

export type BatchItemInput = {
  template_id: number;
  /** Per-entry override; blank falls back to the search's remembered source. */
  credential_id?: number | null;
  index_target_id?: number | null;
  region_code?: string | null;
};

export type BatchCreateInput = {
  items: BatchItemInput[];
  start_epoch: number;
  end_epoch: number;
  chunk_hours?: number;
  id_batch_size?: number;
  is_preview?: boolean;
};

/** One job per saved search over a shared window. All-or-nothing server-side. */
export const createBatchJobs = (body: BatchCreateInput) =>
  req<Job[]>("/jobs/batch", { method: "POST", body: JSON.stringify(body) });
export const pauseJob = (id: number) => req<Job>(`/jobs/${id}/pause`, { method: "POST" });
export const resumeJob = (id: number) => req<Job>(`/jobs/${id}/resume`, { method: "POST" });
export const cancelJob = (id: number) => req<Job>(`/jobs/${id}/cancel`, { method: "POST" });
export const retryJob = (id: number) => req<Job>(`/jobs/${id}/retry`, { method: "POST" });
export const deleteJobFiles = (id: number) => req<Job>(`/jobs/${id}/files`, { method: "DELETE" });
/** Re-queue S3 delivery for a completed job (does not re-query Last9). */
export const retryS3Upload = (id: number) => req<Job>(`/jobs/${id}/s3-upload`, { method: "POST" });

export type BulkCancelResult = {
  canceled: number[];
  /** Reason keyed by job id — the job's actual status, or "not_found". */
  skipped: Record<number, string>;
};
export const bulkCancelJobs = (jobIds: number[]) =>
  req<BulkCancelResult>("/jobs/bulk-cancel", {
    method: "POST",
    body: JSON.stringify({ job_ids: jobIds }),
  });

// ── export / import (jobs & schedules) ───────────────────────────────────────
// A portable config: the credential and index are resolved to their names, not
// database ids, so a config exported from one environment/region can be
// imported into another where the ids won't match — as long as a credential/
// index of that name already exists there.

export type CredentialRef = { label: string; org_slug: string };
export type IndexRef = { name: string; region_code: string };

export type JobExport = {
  kind: "job";
  label: string;
  customer: string;
  region_code: string;
  index: IndexRef;
  credential: CredentialRef;
  start_epoch: number;
  end_epoch: number;
  chunk_hours: number;
  id_batch_size: number;
  output_format: "csv" | "jsonl";
  phrases: string[];
  ids: string[];
  /** Quoted phrases matched adjacently (sent as regexes). */
  exact_phrases?: string[];
  exclude_phrases?: string[];
  exclude_exact_phrases?: string[];
  message_types: string[];
  aggregation: AggregationSpec | null;
  s3_profile?: { name: string } | null;
};

export type ScheduleExport = {
  kind: "schedule";
  name: string;
  enabled: boolean;
  interval_seconds: number;
  lookback_seconds: number;
  calendar_day: boolean;
  region_code: string;
  index: IndexRef;
  credential: CredentialRef;
  chunk_hours: number;
  id_batch_size: number;
  output_format: "csv" | "jsonl" | "bigquery";
  phrases: string[];
  ids: string[];
  /** Quoted phrases matched adjacently (sent as regexes). */
  exact_phrases?: string[];
  exclude_phrases?: string[];
  exclude_exact_phrases?: string[];
  customer: string;
  aggregation: AggregationSpec | null;
  alert_recipients: string[];
  bq_config: BQConfig | null;
  s3_profile?: { name: string } | null;
};

export const exportJob = (id: number) => req<JobExport>(`/jobs/${id}/export`);
export const importJob = (body: JobExport) =>
  req<Job>("/jobs/import", { method: "POST", body: JSON.stringify(body) });

export const exportSchedule = (id: number) => req<ScheduleExport>(`/schedules/${id}/export`);
export const importSchedule = (body: ScheduleExport) =>
  req<Schedule>("/schedules/import", { method: "POST", body: JSON.stringify(body) });

/** Trigger a browser download of `data` as pretty-printed JSON. */
export function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── labels autocomplete ───────────────────────────────────────────────────────

export const listLabels = (credentialId: number) =>
  req<string[]>(`/credentials/${credentialId}/labels`);
export const listLabelValues = (credentialId: number, label: string) =>
  req<string[]>(`/credentials/${credentialId}/labels/${encodeURIComponent(label)}/values`);

// ── auth ──────────────────────────────────────────────────────────────────────

export type AuthUser = {
  id: number;
  email: string;
  name: string;
  role: string;
  created_at: string;
};
export type LoginResult = { access_token: string; token_type: string; role: string };

export type AuthProviders = { password: boolean; google: boolean };

export async function getAuthProviders(): Promise<AuthProviders> {
  const res = await fetch(`${API_BASE}/auth/providers`, { cache: "no-store" });
  if (!res.ok) return { password: true, google: false };
  return res.json();
}

export async function loginUser(email: string, password: string): Promise<LoginResult> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
  if (!res.ok) {
    const d = await res.json().catch(() => null);
    throw new Error(d?.detail ?? "Invalid credentials");
  }
  return res.json();
}

export const getMe = () => req<AuthUser>("/auth/me");
export const listUsers = () => req<AuthUser[]>("/auth/users");
export const createUser = (body: { email: string; name: string; password: string; role: string }) =>
  req<AuthUser>("/auth/users", { method: "POST", body: JSON.stringify(body) });
export const deleteUser = (id: number) => req<void>(`/auth/users/${id}`, { method: "DELETE" });

// ── admin ─────────────────────────────────────────────────────────────────────

export type AuditEntry = {
  id: number;
  user_id: string | null;
  action: string;
  entity: string;
  entity_id: number | null;
  metadata: Record<string, unknown> | null;
  ts: string;
};

export type Settings = {
  environment: string;
  default_org_slug: string;
  storage_dir: string;
  export_retention_days: number;
  download_url_ttl_seconds: number;
  region_count: number;
};

export type NotificationConfig = {
  slack_webhook_url: string;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password: string;
  smtp_from: string;
};

export const listAudit = () => req<AuditEntry[]>("/audit");
export const getSettings = () => req<Settings>("/settings");
export type NotificationConfigOut = Omit<NotificationConfig, "smtp_password"> & {
  // The password never leaves the server; this only says whether one is stored.
  smtp_password_set: boolean;
};

export const getNotificationConfig = () => req<NotificationConfigOut>("/settings/notifications");

// Blank smtp_password means "keep the stored one".
export const updateNotificationConfig = (config: Partial<NotificationConfig>) =>
  req<{ ok: boolean; message: string }>("/settings/notifications", {
    method: "PATCH",
    body: JSON.stringify(config),
  });

// ── system health alerts ────────────────────────────────────────────────────

export type HealthAlertConfig = {
  enabled: boolean;
  cpu_threshold_pct: number;
  memory_threshold_pct: number;
  disk_threshold_pct: number;
  cooldown_minutes: number;
  slack: boolean;
  email: boolean;
  recipients: string[];
  notify_on_recovery: boolean;
};

export type HealthAlertConfigOut = HealthAlertConfig & { disk_path: string | null };

export type HealthSample = {
  available: boolean;
  message?: string;
  ts?: string;
  cpu_pct?: number;
  memory_pct?: number;
  memory_used_mb?: number;
  memory_total_mb?: number;
  disk_pct?: number;
  disk_free_gb?: number;
  disk_total_gb?: number;
  disk_path?: string;
  load1?: number | null;
  /** Active alert thresholds, so any signed-in user can colour the widget. */
  thresholds?: { cpu: number; memory: number; disk: number };
  enabled?: boolean;
};

export const getHealthAlertConfig = () => req<HealthAlertConfigOut>("/settings/health-alerts");
export const updateHealthAlertConfig = (config: HealthAlertConfig) =>
  req<{ ok: boolean; message: string }>("/settings/health-alerts", {
    method: "PUT",
    body: JSON.stringify(config),
  });
export type TestHealthAlertResult = {
  ok: boolean;
  message: string;
  channels?: Record<string, { attempted: boolean; ok: boolean; reason?: string }>;
  failed?: Record<string, string>;
  skipped?: Record<string, string>;
};

export const testHealthAlert = () =>
  req<TestHealthAlertResult>("/settings/health-alerts/test", { method: "POST" });
export const getHealthMetrics = () => req<HealthSample>("/health/metrics");

// ── worker capacity ─────────────────────────────────────────────────────────

export type WorkerCapacity = {
  configured: number;
  running: number | null;
  /** The limit the worker process started with; a live resize does not change it. */
  started_with: number | null;
  active_jobs: number;
  nodes: number;
  available: boolean;
};

export const getWorkerCapacity = () => req<WorkerCapacity>("/admin/worker");
export const setWorkerConcurrency = (concurrency: number) =>
  req<{
    ok: boolean;
    applied: boolean;
    previous: number | null;
    running?: number | null;
    message: string;
  }>("/admin/worker/concurrency", {
    method: "POST",
    body: JSON.stringify({ concurrency }),
  });

// ── schedules (F1) ────────────────────────────────────────────────────────────

export type BQConfig = {
  project_id: string;
  dataset_id: string;
  table_id: string;
  credentials_json: string | null;
};

export type Schedule = {
  id: number;
  name: string;
  enabled: boolean;
  interval_seconds: number;
  lookback_seconds: number;
  calendar_day: boolean;
  region_code: string;
  index_target_id: number;
  credential_id: number;
  chunk_hours: number;
  id_batch_size: number;
  output_format: string;
  filter_spec: {
    phrases: string[];
    ids: string[];
    exact_phrases?: string[];
    exclude_phrases?: string[];
    exclude_exact_phrases?: string[];
    aggregation?: { enabled: boolean };
  };
  last_run_at: string | null;
  created_at: string;
  last_run_job_id: number | null;
  bq_config: BQConfig | null;
  alert_recipients: string[];
  s3_profile_id: number | null;
  s3_profile_label: string | null;
};

export type ScheduleInput = {
  name: string;
  interval_seconds: number;
  lookback_seconds: number;
  calendar_day?: boolean;
  credential_id: number;
  index_target_id: number;
  region_code: string;
  output_format: "csv" | "jsonl" | "bigquery";
  phrases: string[];
  ids: string[];
  /** Quoted phrases matched adjacently (sent as regexes). */
  exact_phrases?: string[];
  /** Logs containing any of these are excluded. */
  exclude_phrases?: string[];
  exclude_exact_phrases?: string[];
  /** Parse & aggregate config, normally carried in from a saved search. */
  aggregation?: AggregationSpec | null;
  /** Groups this schedule's runs into one folder per customer. */
  customer?: string;
  /** BigQuery destination config; null = no BQ load */
  bq_config?: BQConfig | null;
  alert_recipients?: string[];
  s3_profile_id?: number | null;
};

// Combine a schedule's runs over a period into one job with exact cross-period
// unique counts. Unique counts don't add — a customer seen on 10 days would be
// counted 10 times by summing — so the backend merges the runs' underlying
// distinct values instead.
export const createRollup = (body: {
  schedule_id: number;
  start_epoch: number;
  end_epoch: number;
  label?: string;
}) => req<Job>("/jobs/rollup", { method: "POST", body: JSON.stringify(body) });

export const listSchedules = () => req<Schedule[]>("/schedules");
export const createSchedule = (body: ScheduleInput) =>
  req<Schedule>("/schedules", { method: "POST", body: JSON.stringify(body) });
export const updateSchedule = (
  id: number,
  body: {
    name?: string;
    interval_seconds?: number;
    lookback_seconds?: number;
    calendar_day?: boolean;
    phrases?: string[];
    ids?: string[];
    alert_recipients?: string[];
    bq_config?: BQConfig | null;
    s3_profile_id?: number | null;
  }
) => req<Schedule>(`/schedules/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const toggleSchedule = (id: number) =>
  req<Schedule>(`/schedules/${id}/toggle`, { method: "POST" });
export const deleteSchedule = (id: number) => req<void>(`/schedules/${id}`, { method: "DELETE" });

// ── log formats library ──────────────────────────────────────────────────────
// Named parse patterns. A job with `use_library` tries every enabled format
// against each row until one matches, so one job can span many log shapes.

export type LogFormat = {
  id: number;
  name: string;
  regex: string;
  /** Literal every line of this format contains; checked before the regex runs. */
  hint: string | null;
  sample_line: string | null;
  /** Lower is tried first — first match wins, so a narrow format can outrank a broad one. */
  priority: number;
  enabled: boolean;
  description: string | null;
  created_at: string;
};

export type LogFormatInput = {
  name: string;
  regex: string;
  hint?: string;
  sample_line?: string;
  priority?: number;
  enabled?: boolean;
  description?: string;
};

export type LogFormatTestResult = {
  matched: boolean;
  error: string | null;
  fields: Record<string, string>;
};

export const listLogFormats = () => req<LogFormat[]>("/log-formats");
export const createLogFormat = (body: LogFormatInput) =>
  req<LogFormat>("/log-formats", { method: "POST", body: JSON.stringify(body) });
export const updateLogFormat = (id: number, body: LogFormatInput) =>
  req<LogFormat>(`/log-formats/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteLogFormat = (id: number) =>
  req<void>(`/log-formats/${id}`, { method: "DELETE" });
export const testLogFormat = (body: { regex: string; sample_line: string; hint?: string }) =>
  req<LogFormatTestResult>("/log-formats/test", { method: "POST", body: JSON.stringify(body) });

// ── auto-detect (saved formats + saved-search patterns) ─────────────────────

export type DetectedField = {
  name: string;
  /** Matched lines that produced a value for this field. */
  coverage: number;
  distinct: number;
  sample: string;
  /** Heuristic from the pasted sample: low cardinality groups, high counts. */
  suggested: "group_by" | "unique" | "none";
};

export type DetectedCandidate = {
  source: "library" | "saved_search";
  id: number;
  name: string;
  regex: string;
  hint: string | null;
  priority: number;
  matched: number;
  fields: DetectedField[];
  suggested_group_by: string[];
  suggested_unique: string[];
};

export type InferredPattern = {
  regex: string;
  fields: DetectedField[];
  suggested_group_by: string[];
  suggested_unique: string[];
  lines_used: number;
};

export type DetectResult = {
  lines_analyzed: number;
  matched: number;
  unmatched: number;
  candidates: DetectedCandidate[];
  json_fields: DetectedField[];
  /** A pattern built from the pasted lines when nothing saved matched. */
  inferred: InferredPattern | null;
  message: string | null;
};

export const detectLogFormats = (lines: string[]) =>
  req<DetectResult>("/log-formats/detect", {
    method: "POST",
    body: JSON.stringify({ lines }),
  });

// ── New Relic connections ────────────────────────────────────────────────────

export type NewRelicCredential = {
  id: number;
  label: string;
  account_id: number;
  region: "us" | "eu" | string;
  api_key_preview: string;
  created_by: string | null;
  created_at: string;
};

export type NewRelicCredentialInput = {
  label: string;
  account_id: number;
  region: "us" | "eu";
  api_key: string;
};

export type NewRelicTestResult = {
  ok: boolean;
  message: string;
  account_name: string | null;
};

export const listNewRelicCredentials = () => req<NewRelicCredential[]>("/newrelic/credentials");
export const createNewRelicCredential = (body: NewRelicCredentialInput) =>
  req<NewRelicCredential>("/newrelic/credentials", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const updateNewRelicCredential = (
  id: number,
  body: {
    label?: string;
    account_id?: number;
    region?: "us" | "eu";
    /** Blank/omitted keeps the stored key. */
    api_key?: string;
  }
) =>
  req<NewRelicCredential>(`/newrelic/credentials/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
export const deleteNewRelicCredential = (id: number) =>
  req<void>(`/newrelic/credentials/${id}`, { method: "DELETE" });
export const testNewRelicCredential = (id: number) =>
  req<NewRelicTestResult>(`/newrelic/credentials/${id}/test`, { method: "POST" });

// ── S3 destination profiles ─────────────────────────────────────────────────

export type S3Profile = {
  id: number;
  name: string;
  bucket: string;
  region: string;
  prefix: string;
  endpoint_url: string | null;
  key_preview: string | null;
  force_path_style: boolean;
  created_by: string | null;
  created_at: string;
};

export type S3ProfileInput = {
  name: string;
  bucket: string;
  region: string;
  prefix?: string;
  endpoint_url?: string | null;
  access_key_id?: string | null;
  secret_access_key?: string | null;
  session_token?: string | null;
  force_path_style?: boolean;
};

export type S3TestResult = { ok: boolean; message: string };

export const listS3Profiles = () => req<S3Profile[]>("/s3-profiles");
export const createS3Profile = (body: S3ProfileInput) =>
  req<S3Profile>("/s3-profiles", { method: "POST", body: JSON.stringify(body) });
export const updateS3Profile = (
  id: number,
  body: Partial<S3ProfileInput> & { clear_credentials?: boolean }
) =>
  req<S3Profile>(`/s3-profiles/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
export const deleteS3Profile = (id: number) =>
  req<void>(`/s3-profiles/${id}`, { method: "DELETE" });
export const testS3Profile = (id: number) =>
  req<S3TestResult>(`/s3-profiles/${id}/test`, { method: "POST" });

// ── Last9 vs New Relic comparisons ───────────────────────────────────────────

export type Last9FilterSpec = {
  phrases: string[];
  ids: string[];
  exact_phrases?: string[];
  message_types: string[];
};

/** "sum" turns a count query into a total; avg/max/min/last compare gauges. */
export type ComparisonValueMode = "sum" | "avg" | "max" | "min" | "last";

export type ComparisonSummary = {
  id: number;
  name: string;
  description: string | null;
  last9_credential_id: number;
  last9_index_target_id: number;
  last9_region_code: string;
  nr_credential_id: number;
  nr_value_mode: ComparisonValueMode;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  last9_credential_label: string | null;
  last9_index_name: string | null;
  nr_credential_label: string | null;
  nr_account_id: number | null;
  last_run_at: string | null;
  last_run_id: number | null;
  last_run_status: string | null;
  last_run_last9_total: number | null;
  last_run_newrelic_total: number | null;
};

export type Comparison = ComparisonSummary & {
  last9_pipeline: Record<string, unknown>[];
  last9_filter_spec: Last9FilterSpec | null;
  nrql: string;
  nr_value_field: string | null;
  bucket_seconds: number | null;
};

export type ComparisonList = {
  items: ComparisonSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type ComparisonInput = {
  name: string;
  description?: string;
  last9_index_target_id: number;
  last9_credential_id?: number | null;
  last9_filter_spec?: Last9FilterSpec | null;
  last9_pipeline?: Record<string, unknown>[] | null;
  nr_credential_id: number;
  nrql: string;
  nr_value_mode?: ComparisonValueMode;
  nr_value_field?: string | null;
  bucket_seconds?: number | null;
};

export type ComparisonPoint = {
  start_epoch: number;
  end_epoch: number;
  value: number;
};

export type ComparisonSide = {
  ok: boolean;
  error: string | null;
  elapsed_ms: number | null;
  total: number | null;
  series: ComparisonPoint[];
  raw: Record<string, unknown>[];
  metadata: Record<string, unknown> | null;
};

export type ComparisonRunSummary = {
  id: number;
  comparison_id: number;
  start_epoch: number;
  end_epoch: number;
  bucket_seconds: number;
  status: "ok" | "partial" | "failed";
  last9_ok: boolean;
  last9_total: number | null;
  newrelic_ok: boolean;
  newrelic_total: number | null;
  created_by: string | null;
  created_at: string;
};

export type ComparisonRun = ComparisonRunSummary & {
  last9: ComparisonSide;
  newrelic: ComparisonSide;
  nrql_effective: string | null;
  last9_pipeline_effective: {
    total?: Record<string, unknown>[] | null;
    series?: Record<string, unknown>[] | null;
    bucket_seconds?: number;
    value_mode?: string;
  } | null;
  delta: number | null;
  pct_diff: number | null;
};

export const listComparisons = (params?: { limit?: number; offset?: number; q?: string }) => {
  const query = new URLSearchParams();
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.offset != null) query.set("offset", String(params.offset));
  if (params?.q) query.set("q", params.q);
  const suffix = query.toString();
  return req<ComparisonList>(`/comparisons${suffix ? `?${suffix}` : ""}`);
};
export const getComparison = (id: number) => req<Comparison>(`/comparisons/${id}`);
export const createComparison = (body: ComparisonInput) =>
  req<Comparison>("/comparisons", { method: "POST", body: JSON.stringify(body) });
export const updateComparison = (id: number, body: ComparisonInput) =>
  req<Comparison>(`/comparisons/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteComparison = (id: number) =>
  req<void>(`/comparisons/${id}`, { method: "DELETE" });
export const runComparison = (
  id: number,
  body: { start_epoch: number; end_epoch: number; bucket_seconds?: number | null }
) =>
  req<ComparisonRun>(`/comparisons/${id}/run`, {
    method: "POST",
    body: JSON.stringify(body),
  });
export const listComparisonRuns = (id: number, limit = 20) =>
  req<ComparisonRunSummary[]>(`/comparisons/${id}/runs?limit=${limit}`);
export const getComparisonRun = (comparisonId: number, runId: number) =>
  req<ComparisonRun>(`/comparisons/${comparisonId}/runs/${runId}`);
