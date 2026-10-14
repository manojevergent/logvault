"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarClock,
  FileDown,
  Loader2,
  Pencil,
  Plus,
  Power,
  Sigma,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { ImportJsonButton } from "@/components/import-json-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FieldGroup, Input, Label, fieldClass } from "@/components/ui/input";
import {
  BQConfig,
  FilterTemplate,
  Schedule,
  ScheduleExport,
  createRollup,
  createSchedule,
  deleteSchedule,
  downloadJson,
  exportSchedule,
  importSchedule,
  listCredentials,
  listIndexes,
  listRegions,
  listSchedules,
  listTemplates,
  toggleSchedule,
  updateSchedule,
} from "@/lib/api";

const EVERY = [
  { label: "Every hour", v: 3600 },
  { label: "Every 6 hours", v: 6 * 3600 },
  { label: "Every day", v: 86400 },
];
const LOOKBACK = [
  { label: "Last 1 hour", v: 3600 },
  { label: "Last 6 hours", v: 6 * 3600 },
  { label: "Last 24 hours", v: 86400 },
  { label: "Custom hours", v: 0 },
];

function human(sec: number) {
  if (sec % 86400 === 0) return `${sec / 86400}d`;
  if (sec % 3600 === 0) return `${sec / 3600}h`;
  return `${sec}s`;
}

export default function SchedulesPage() {
  const qc = useQueryClient();
  const [adding, setAdding] = React.useState(false);
  const { data: schedules, isLoading } = useQuery({
    queryKey: ["schedules"],
    queryFn: listSchedules,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["schedules"] });

  return (
    <div className="mx-auto max-w-5xl animate-fade-in px-6 py-8">
      <div className="flex items-end justify-between pb-6">
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">Schedules</h1>
          <p className="text-sm text-muted-foreground">
            Recurring extractions — each run pulls a rolling window automatically.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ImportJsonButton<ScheduleExport>
            label="Import"
            onImport={async (data) => {
              await importSchedule(data);
              invalidate();
            }}
          />
          <Button onClick={() => setAdding((v) => !v)} variant={adding ? "outline" : "primary"}>
            <Plus className="h-4 w-4" />
            {adding ? "Cancel" : "New schedule"}
          </Button>
        </div>
      </div>

      {adding && <AddScheduleForm onDone={() => setAdding(false)} />}

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {schedules && schedules.length === 0 && !adding && (
        <div className="flex flex-col items-center gap-3 border border-dashed border-border py-16 text-center">
          <div className="flex h-11 w-11 items-center justify-center bg-muted">
            <CalendarClock className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium">No schedules yet</p>
        </div>
      )}

      <div className="space-y-3">
        {schedules?.map((s) => (
          <ScheduleRow key={s.id} s={s} onChange={invalidate} />
        ))}
      </div>
    </div>
  );
}

function ScheduleRow({ s, onChange }: { s: Schedule; onChange: () => void }) {
  const [editing, setEditing] = React.useState(false);
  const [rollingUp, setRollingUp] = React.useState(false);
  const toggle = useMutation({ mutationFn: () => toggleSchedule(s.id), onSuccess: onChange });
  const del = useMutation({ mutationFn: () => deleteSchedule(s.id), onSuccess: onChange });
  // Rolling up means merging each run's unique values; a schedule that doesn't
  // parse & aggregate has none to merge.
  const canRollUp = Boolean(s.filter_spec?.aggregation?.enabled);

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="font-medium">{s.name}</span>
              <Badge tone={s.enabled ? "success" : "neutral"}>{s.enabled ? "on" : "off"}</Badge>
              <Badge tone="info">{s.output_format}</Badge>
              {s.bq_config && <Badge tone="info">→ BQ</Badge>}
            </div>
            <p className="font-mono text-xs text-muted-foreground">
              every {human(s.interval_seconds)} ·{" "}
              {s.calendar_day ? "window 00:00–23:59 UTC" : `window ${human(s.lookback_seconds)}`} ·{" "}
              {s.region_code}
              {s.last_run_at && ` · last ${s.last_run_at.slice(0, 16).replace("T", " ")}`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {s.last_run_job_id != null && (
              <Link href={`/jobs/${s.last_run_job_id}`}>
                <Button size="sm" variant="ghost" className="gap-1 text-xs">
                  Last job <ArrowRight className="h-3 w-3" />
                </Button>
              </Link>
            )}
            {canRollUp && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setRollingUp((v) => !v)}
                className="gap-1 text-xs"
              >
                <Sigma className="h-3.5 w-3.5" /> Roll up
              </Button>
            )}
            <Button
              size="icon"
              variant="ghost"
              aria-label="Export schedule config"
              title="Export config as JSON"
              onClick={async () => downloadJson(`${s.name || `schedule_${s.id}`}.json`, await exportSchedule(s.id))}
            >
              <FileDown className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              aria-label="Edit schedule"
              onClick={() => setEditing((v) => !v)}
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => toggle.mutate()}
              disabled={toggle.isPending}
            >
              <Power className="h-3.5 w-3.5" /> {s.enabled ? "Disable" : "Enable"}
            </Button>
            <Button
              size="icon"
              variant="ghost"
              aria-label="Delete schedule"
              onClick={() => del.mutate()}
              disabled={del.isPending}
            >
              <Trash2 className="h-4 w-4 text-danger" />
            </Button>
          </div>
        </div>
        {rollingUp && <RollupForm s={s} onDone={() => setRollingUp(false)} />}
        {editing && (
          <EditScheduleForm
            s={s}
            onDone={() => {
              setEditing(false);
              onChange();
            }}
          />
        )}
      </CardContent>
    </Card>
  );
}

// UTC month boundaries, matching how calendar_day schedules pick a day: the
// logs are timestamped in UTC, so a "month" has to mean a UTC month or the
// rollup would include part of the day either side of it.
function utcMonthRange(month: string): { start_epoch: number; end_epoch: number } {
  const [y, m] = month.split("-").map(Number);
  const start = Date.UTC(y, m - 1, 1);
  const end = Date.UTC(m === 12 ? y + 1 : y, m === 12 ? 0 : m, 1);
  return { start_epoch: Math.floor(start / 1000), end_epoch: Math.floor(end / 1000) };
}

function previousMonth(): string {
  const now = new Date();
  const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function RollupForm({ s, onDone }: { s: Schedule; onDone: () => void }) {
  const router = useRouter();
  const [month, setMonth] = React.useState(previousMonth());
  const run = useMutation({
    mutationFn: () => createRollup({ schedule_id: s.id, label: month, ...utcMonthRange(month) }),
    onSuccess: (job) => {
      onDone();
      router.push(`/jobs/${job.id}`);
    },
  });

  return (
    <div className="mt-4 space-y-3 border-t border-border pt-4">
      <p className="text-xs text-muted-foreground">
        Combines every completed run in the month into one result. Unique counts are merged, not
        added — anything seen on several days is counted once.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1.5">
          <Label>Month (UTC)</Label>
          <Input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="w-44"
          />
        </div>
        <Button size="sm" disabled={!month || run.isPending} onClick={() => run.mutate()}>
          {run.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Roll up
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        {run.isError && <span className="text-xs text-danger">{(run.error as Error).message}</span>}
      </div>
    </div>
  );
}

function EditScheduleForm({ s, onDone }: { s: Schedule; onDone: () => void }) {
  const [f, setF] = React.useState({
    name: s.name,
    interval_seconds: s.interval_seconds,
    lookback_seconds: s.lookback_seconds,
    calendar_day: s.calendar_day,
    alert_recipients: (s.alert_recipients ?? []).join(", "),
    bq_project_id: s.bq_config?.project_id ?? "",
    bq_dataset_id: s.bq_config?.dataset_id ?? "",
    bq_table_id: s.bq_config?.table_id ?? "",
    bq_credentials_json: s.bq_config?.credentials_json ?? "",
  });
  const hasBqConfig = f.bq_project_id || f.bq_dataset_id || f.bq_table_id;
  const save = useMutation({
    mutationFn: () =>
      updateSchedule(s.id, {
        name: f.name,
        interval_seconds: f.interval_seconds,
        lookback_seconds: f.lookback_seconds,
        calendar_day: f.calendar_day,
        alert_recipients: f.alert_recipients
          .split(/[,\s]+/)
          .map((e) => e.trim())
          .filter(Boolean),
        bq_config: hasBqConfig ? {
          project_id: f.bq_project_id,
          dataset_id: f.bq_dataset_id,
          table_id: f.bq_table_id,
          credentials_json: f.bq_credentials_json.trim() || null,
        } : null,
      }),
    onSuccess: onDone,
  });
  return (
    <div className="mt-4 grid grid-cols-1 gap-3 border-t border-border pt-4 sm:grid-cols-3">
      <div className="space-y-1.5">
        <Label>Name</Label>
        <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
      </div>
      <div className="space-y-1.5">
        <Label>Run every</Label>
        <select
          className={fieldClass}
          value={f.calendar_day ? 86400 : f.interval_seconds}
          disabled={f.calendar_day}
          onChange={(e) => setF({ ...f, interval_seconds: Number(e.target.value) })}
        >
          {EVERY.map((o) => (
            <option key={o.v} value={o.v}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-1.5">
        <Label>Window</Label>
        {f.calendar_day ? (
          <p className={`${fieldClass} flex items-center text-muted-foreground`}>
            00:00–23:59 UTC (previous full day)
          </p>
        ) : (
          <select
            className={fieldClass}
            value={f.lookback_seconds}
            onChange={(e) => setF({ ...f, lookback_seconds: Number(e.target.value) })}
          >
            {LOOKBACK.map((o) => (
              <option key={o.v} value={o.v}>
                {o.label}
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="space-y-1.5 sm:col-span-3">
        <Label>Alert recipients (comma or space separated)</Label>
        <Input
          value={f.alert_recipients}
          onChange={(e) => setF({ ...f, alert_recipients: e.target.value })}
          placeholder="ops@example.com, alerts@example.com"
        />
      </div>
      <div className="sm:col-span-3">
        <p className="mb-2 text-xs font-medium text-muted-foreground">BigQuery destination (optional)</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label>GCP Project ID</Label>
            <Input value={f.bq_project_id} onChange={(e) => setF({ ...f, bq_project_id: e.target.value })} placeholder="my-gcp-project" />
          </div>
          <div className="space-y-1.5">
            <Label>Dataset ID</Label>
            <Input value={f.bq_dataset_id} onChange={(e) => setF({ ...f, bq_dataset_id: e.target.value })} placeholder="logvault_data" />
          </div>
          <div className="space-y-1.5">
            <Label>Table ID</Label>
            <Input value={f.bq_table_id} onChange={(e) => setF({ ...f, bq_table_id: e.target.value })} placeholder="extractions" />
          </div>
          <div className="space-y-1.5 sm:col-span-3">
            <Label>Service account JSON (leave blank for ADC)</Label>
            <textarea
              className={`${fieldClass} h-16 py-2 font-mono text-xs`}
              value={f.bq_credentials_json}
              onChange={(e) => setF({ ...f, bq_credentials_json: e.target.value })}
              placeholder='{"type":"service_account","project_id":"…"}'
            />
          </div>
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm sm:col-span-3">
        <input
          type="checkbox"
          checked={f.calendar_day}
          onChange={(e) =>
            setF({ ...f, calendar_day: e.target.checked, interval_seconds: 86400 })
          }
        />
        Full day (00:00–23:59 UTC) instead of a rolling window
      </label>
      <div className="flex items-center gap-2 sm:col-span-3">
        <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Save
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        {save.isError && (
          <span className="text-xs text-danger">{(save.error as Error).message}</span>
        )}
      </div>
    </div>
  );
}

function AddScheduleForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const { data: creds } = useQuery({ queryKey: ["credentials"], queryFn: listCredentials });
  const { data: regions } = useQuery({ queryKey: ["regions"], queryFn: listRegions });
  const { data: templates } = useQuery({ queryKey: ["templates"], queryFn: listTemplates });
  const [templateId, setTemplateId] = React.useState<number | "">("");
  const [f, setF] = React.useState({
    name: "",
    credential_id: "" as number | "",
    region_code: "",
    index_target_id: "" as number | "",
    interval_seconds: 86400,
    lookback_seconds: 86400,
    custom_lookback_hours: "",
    calendar_day: false,
    output_format: "csv" as "csv" | "jsonl" | "bigquery",
    phrases: "",
    ids: "",
    alert_recipients: "",
    bq_project_id: "",
    bq_dataset_id: "",
    bq_table_id: "",
    bq_credentials_json: "",
  });

  function applyTemplate(tpl: FilterTemplate) {
    // Schedules don't have a separate message-types concept — fold them into
    // phrases, since the worker treats both identically (AND'd substrings).
    setF((prev) => ({
      ...prev,
      phrases: [...tpl.phrases, ...tpl.message_types].join(", "),
      ids: tpl.ids.join("\n"),
    }));
  }

  // A saved search is the only way to put a parse pattern on a schedule — there
  // is no regex field on this form, and a daily run is exactly where one is
  // wanted. Whatever the chosen template carries goes with the schedule.
  const selectedTemplate = templates?.find((t) => t.id === templateId);
  const templateAggregation = selectedTemplate?.aggregation ?? null;

  // Unfiltered: the source picker is the one control and the region follows it.
  const { data: indexes } = useQuery({ queryKey: ["indexes", ""], queryFn: () => listIndexes() });
  const selectedIndex = indexes?.find((i) => i.id === f.index_target_id);

  const create = useMutation({
    mutationFn: () => {
      // Use custom hours if selected, otherwise use dropdown value
      const lookback = f.lookback_seconds === 0
        ? Number(f.custom_lookback_hours) * 3600
        : f.lookback_seconds;

      const bqEnabled = f.output_format === "bigquery" && f.bq_project_id && f.bq_dataset_id && f.bq_table_id;
      return createSchedule({
        name: f.name,
        credential_id: Number(f.credential_id),
        index_target_id: Number(f.index_target_id),
        region_code: f.region_code,
        interval_seconds: f.interval_seconds,
        lookback_seconds: lookback,
        calendar_day: f.calendar_day,
        output_format: f.output_format,
        aggregation: templateAggregation,
        customer: selectedTemplate?.customer ?? "",
        phrases: f.phrases
          .split(/[,\s]+/)
          .map((p) => p.trim())
          .filter(Boolean),
        ids: f.ids
          .split("\n")
          .map((i) => i.trim())
          .filter(Boolean),
        alert_recipients: f.alert_recipients
          .split(/[,\s]+/)
          .map((e) => e.trim())
          .filter(Boolean),
        bq_config: bqEnabled ? {
          project_id: f.bq_project_id,
          dataset_id: f.bq_dataset_id,
          table_id: f.bq_table_id,
          credentials_json: f.bq_credentials_json.trim() || null,
        } : null,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schedules"] });
      onDone();
    },
  });

  const valid = f.name && f.credential_id !== "" && f.index_target_id !== "";

  return (
    <Card className="mb-6">
      <CardContent className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2">
        <Field label="Load a saved search" className="sm:col-span-2">
          <select
            className={fieldClass}
            value={templateId}
            onChange={(e) => {
              const v = e.target.value ? Number(e.target.value) : "";
              setTemplateId(v);
              const tpl = templates?.find((t) => t.id === v);
              if (tpl) applyTemplate(tpl);
            }}
          >
            <option value="">{templates?.length ? "Choose a saved search…" : "No saved searches yet"}</option>
            {templates?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
                {t.aggregation?.enabled ? " (with parse & aggregate)" : ""}
              </option>
            ))}
          </select>
          {templateAggregation?.enabled && (
            <p className="text-xs text-muted-foreground">
              Counts unique <strong>{templateAggregation.unique_fields.join(", ")}</strong>
              {templateAggregation.group_by.length > 0 && (
                <> per <strong>{templateAggregation.group_by.join(" + ")}</strong></>
              )}
              , using the saved parse pattern.
            </p>
          )}
        </Field>
        <Field label="Name">
          <Input
            value={f.name}
            onChange={(e) => setF({ ...f, name: e.target.value })}
            placeholder="Daily UMServices"
          />
        </Field>
        {/* One source profile carries region + index + credential. */}
        <Field label="Source" className="sm:col-span-2">
          <select
            className={fieldClass}
            value={f.index_target_id}
            onChange={(e) => {
              const id = e.target.value ? Number(e.target.value) : "";
              const picked = indexes?.find((i) => i.id === id);
              setF({
                ...f,
                index_target_id: id,
                region_code: picked?.region_code ?? "",
                credential_id: picked?.credential_id ?? f.credential_id,
              });
            }}
          >
            <option value="">Select a source…</option>
            {indexes?.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name} · {i.region_code}
                {i.credential_label ? ` · ${i.credential_label}` : ""}
              </option>
            ))}
          </select>
        </Field>
        {/* Only asked for when the chosen source doesn't name one. */}
        {!selectedIndex?.credential_id && (
          <Field label="Credential" className="sm:col-span-2">
            <select
              className={fieldClass}
              value={f.credential_id}
              onChange={(e) =>
                setF({ ...f, credential_id: e.target.value ? Number(e.target.value) : "" })
              }
            >
              <option value="">Select…</option>
              {creds?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Run">
          <select
            className={fieldClass}
            value={f.calendar_day ? 86400 : f.interval_seconds}
            disabled={f.calendar_day}
            onChange={(e) => setF({ ...f, interval_seconds: Number(e.target.value) })}
          >
            {EVERY.map((o) => (
              <option key={o.v} value={o.v}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Window">
          {f.calendar_day ? (
            <p className={`${fieldClass} flex items-center text-muted-foreground`}>
              00:00–23:59 UTC (previous full day)
            </p>
          ) : (
            <>
              <select
                className={fieldClass}
                value={f.lookback_seconds}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setF({ ...f, lookback_seconds: v, custom_lookback_hours: "" })
                }}
              >
                {LOOKBACK.map((o) => (
                  <option key={o.v} value={o.v}>
                    {o.label}
                  </option>
                ))}
              </select>
              {f.lookback_seconds === 0 && (
                <input
                  type="number"
                  className={`${fieldClass} mt-2`}
                  value={f.custom_lookback_hours}
                  onChange={(e) => setF({ ...f, custom_lookback_hours: e.target.value })}
                  placeholder="Enter hours (1-500)"
                  min="1"
                  max="500"
                />
              )}
            </>
          )}
        </Field>
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input
            type="checkbox"
            checked={f.calendar_day}
            onChange={(e) =>
              setF({ ...f, calendar_day: e.target.checked, interval_seconds: 86400 })
            }
          />
          Full day (00:00–23:59 UTC) instead of a rolling window
        </label>
        <Field label="Format">
          <select
            className={fieldClass}
            value={f.output_format}
            onChange={(e) => setF({ ...f, output_format: e.target.value as "csv" | "jsonl" | "bigquery" })}
          >
            <option value="csv">CSV</option>
            <option value="jsonl">JSONL</option>
            <option value="bigquery">BigQuery CSV</option>
          </select>
        </Field>
        {f.output_format === "bigquery" && (
          <>
            <Field label="GCP Project ID">
              <Input
                value={f.bq_project_id}
                onChange={(e) => setF({ ...f, bq_project_id: e.target.value })}
                placeholder="my-gcp-project"
              />
            </Field>
            <Field label="Dataset ID">
              <Input
                value={f.bq_dataset_id}
                onChange={(e) => setF({ ...f, bq_dataset_id: e.target.value })}
                placeholder="logvault_data"
              />
            </Field>
            <Field label="Table ID">
              <Input
                value={f.bq_table_id}
                onChange={(e) => setF({ ...f, bq_table_id: e.target.value })}
                placeholder="extractions"
              />
            </Field>
            <Field label="Service account JSON (leave blank for ADC)" className="sm:col-span-2">
              <textarea
                className={`${fieldClass} h-20 py-2 font-mono text-xs`}
                value={f.bq_credentials_json}
                onChange={(e) => setF({ ...f, bq_credentials_json: e.target.value })}
                placeholder='{"type":"service_account","project_id":"…"}'
              />
            </Field>
          </>
        )}
        <Field label="Required words (comma or space separated, any order)">
          <Input
            value={f.phrases}
            onChange={(e) => setF({ ...f, phrases: e.target.value })}
            placeholder="ClassName CGetEntitlementsCommand"
          />
        </Field>
        <Field label="Match IDs (one per line)" className="sm:col-span-2">
          <textarea
            className={`${fieldClass} h-20 py-2`}
            value={f.ids}
            onChange={(e) => setF({ ...f, ids: e.target.value })}
          />
        </Field>
        <Field label="Alert recipients (comma or space separated emails)" className="sm:col-span-2">
          <Input
            type="email"
            value={f.alert_recipients}
            onChange={(e) => setF({ ...f, alert_recipients: e.target.value })}
            placeholder="ops@example.com, alerts@example.com"
          />
        </Field>
        <div className="sm:col-span-2">
          <Button disabled={!valid || create.isPending} onClick={() => create.mutate()}>
            {create.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Create schedule
          </Button>
          {create.isError && (
            <span className="ml-3 text-xs text-danger">{(create.error as Error).message}</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <FieldGroup>
      <div className={`space-y-1.5 ${className ?? ""}`}>
        <Label>{label}</Label>
        {children}
      </div>
    </FieldGroup>
  );
}
