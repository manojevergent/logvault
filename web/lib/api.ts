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
  const secure = typeof location !== "undefined" && location.protocol === "https:" ? "; Secure" : "";
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
) =>
  req<IndexTarget>(`/indexes/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteIndex = (id: number) => req<void>(`/indexes/${id}`, { method: "DELETE" });

// ── filter templates ("save the search") ────────────────────────────────────

export type FilterTemplate = {
  id: number;
  name: string;
  phrases: string[];
  ids: string[];
  message_types: string[];
  /** Saved parse & aggregate config — the regex comes back with the search. */
  aggregation: AggregationSpec | null;
  /** Extracts from this search land in this customer's folder. */
  customer: string | null;
  /** Remembered source — null when the search predates source memory. */
  credential_id: number | null;
  region_code: string | null;
  index_target_id: number | null;
  created_by: string | null;
  created_at: string;
};

export type FilterTemplateInput = {
  name: string;
  phrases: string[];
  ids: string[];
  message_types: string[];
  aggregation?: AggregationSpec | null;
  customer?: string;
  credential_id?: number | null;
  region_code?: string | null;
  index_target_id?: number | null;
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
    message_types?: string[];
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
  message_types?: string[];
  output_format?: "csv" | "jsonl" | "bigquery";
  is_preview?: boolean;
  /** Saved-search name; names the downloads `<label>_<job id>_<timeframe>.csv`. */
  label?: string;
  /** Groups the output files into one folder per customer. */
  customer?: string;
  aggregation?: Omit<AggregationSpec, "skip_raw_output"> & { skip_raw_output?: boolean } | null;
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
export const listJobs = (limit = 200, includePreviews = false) =>
  req<Job[]>(`/jobs?limit=${limit}${includePreviews ? "&include_previews=true" : ""}`);
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
  message_types: string[];
  aggregation: AggregationSpec | null;
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
  customer: string;
  aggregation: AggregationSpec | null;
  alert_recipients: string[];
  bq_config: BQConfig | null;
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

export const getNotificationConfig = () =>
  req<NotificationConfigOut>("/settings/notifications");

// Blank smtp_password means "keep the stored one".
export const updateNotificationConfig = (config: Partial<NotificationConfig>) =>
  req<{ ok: boolean; message: string }>("/settings/notifications", {
    method: "PATCH",
    body: JSON.stringify(config),
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
  filter_spec: { phrases: string[]; ids: string[]; aggregation?: { enabled: boolean } };
  last_run_at: string | null;
  created_at: string;
  last_run_job_id: number | null;
  bq_config: BQConfig | null;
  alert_recipients: string[];
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
  /** Parse & aggregate config, normally carried in from a saved search. */
  aggregation?: AggregationSpec | null;
  /** Groups this schedule's runs into one folder per customer. */
  customer?: string;
  /** BigQuery destination config; null = no BQ load */
  bq_config?: BQConfig | null;
  alert_recipients?: string[];
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
