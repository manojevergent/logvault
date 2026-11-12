"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  Clock3,
  Download,
  Loader2,
  Pencil,
  Play,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import { ComparisonChart } from "@/components/comparison-chart";
import { ComparisonForm } from "@/components/comparison-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldGroup, Input, Label, fieldClass } from "@/components/ui/input";
import {
  Comparison,
  ComparisonRun,
  ComparisonRunSummary,
  ComparisonSide,
  ComparisonValueMode,
  deleteComparison,
  getComparison,
  getComparisonRun,
  listComparisonRuns,
  runComparison,
} from "@/lib/api";
import {
  PRESETS,
  Tz,
  epochToLocal,
  formatDuration,
  formatEpoch,
  localToEpoch,
  useTz,
} from "@/lib/time";

const LAST9_COLOR = "#4285F4";
const NEWRELIC_COLOR = "#34A853";

function fmt(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function pct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function toneFor(pctDiff: number | null): "success" | "warning" | "danger" | "neutral" {
  if (pctDiff == null) return "neutral";
  const abs = Math.abs(pctDiff);
  if (abs <= 1) return "success";
  if (abs <= 5) return "warning";
  return "danger";
}

function labelFor(pctDiff: number | null): string {
  if (pctDiff == null) return "not comparable";
  const abs = Math.abs(pctDiff);
  if (abs <= 1) return "matched";
  if (abs <= 5) return "close";
  return "mismatch";
}

const RUN_TONE: Record<string, "success" | "warning" | "danger"> = {
  ok: "success",
  partial: "warning",
  failed: "danger",
};

const AUTO_BUCKETS = [60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400, 604800];

function autoBucket(windowSeconds: number): number {
  for (const candidate of AUTO_BUCKETS) {
    if (Math.ceil(windowSeconds / candidate) <= 60) {
      return Math.max(1, Math.min(candidate, windowSeconds));
    }
  }
  return Math.max(1, Math.ceil(windowSeconds / 60));
}

/** The fixed TIMESERIES width in a saved NRQL, mirroring the API's default. */
function nrqlTimeseriesSeconds(nrql: string): number | null {
  const match = nrql.match(/\bTIMESERIES\s+(\d+)\s*(second|minute|hour|day|week)s?\b/i);
  if (!match) return null;
  const unit = match[2].toLowerCase();
  const scale =
    unit === "second"
      ? 1
      : unit === "minute"
        ? 60
        : unit === "hour"
          ? 3600
          : unit === "day"
            ? 86400
            : 604800;
  return Number(match[1]) * scale;
}

function bucketPreview(
  comparison: Comparison,
  requested: string,
  window: number
): { bucket: number; points: number; tooMany: boolean; minBucket: number } {
  const override = Number(requested);
  const candidate =
    (Number.isFinite(override) && override > 0 ? override : null) ||
    comparison.bucket_seconds ||
    nrqlTimeseriesSeconds(comparison.nrql) ||
    autoBucket(window);
  const bucket = Math.max(1, Math.min(candidate, window));
  const points = Math.ceil(window / bucket);
  return {
    bucket,
    points,
    tooMany: points > 500,
    minBucket: Math.max(1, Math.ceil(window / 500)),
  };
}

export default function ComparisonDetailPage() {
  const id = Number(useParams().id);
  const router = useRouter();
  const qc = useQueryClient();
  const [tz, setTz] = useTz();
  const [editing, setEditing] = React.useState(false);
  const [run, setRun] = React.useState<ComparisonRun | null>(null);
  const [runError, setRunError] = React.useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const previousId = React.useRef(id);

  // Client-side navigation between two comparisons reuses this component.
  // Clear the previous run before the new comparison's latest-run query lands.
  React.useEffect(() => {
    if (previousId.current === id) return;
    previousId.current = id;
    setRun(null);
    setRunError(null);
    setEditing(false);
    setConfirmDelete(false);
  }, [id]);

  const {
    data: comparison,
    isLoading,
    error: comparisonError,
  } = useQuery({
    queryKey: ["comparison", id],
    queryFn: () => getComparison(id),
    enabled: Number.isFinite(id),
  });
  const { data: runs } = useQuery({
    queryKey: ["comparison-runs", id],
    queryFn: () => listComparisonRuns(id, 20),
    enabled: Number.isFinite(id),
  });

  const activeRun = run && run.comparison_id === id ? run : null;
  const latestFromHistory =
    runs && runs.length > 0 && runs[0].comparison_id === id ? runs[0].id : null;
  // The comparison detail already carries the latest run id, so the full result
  // can start loading in parallel with the history query instead of waiting for it.
  const latestId = !activeRun ? (comparison?.last_run_id ?? latestFromHistory) : null;
  const { data: autoRun, isError: autoRunFailed } = useQuery({
    queryKey: ["comparison-run", id, latestId],
    queryFn: () => getComparisonRun(id, latestId as number),
    enabled: latestId != null,
  });
  React.useEffect(() => {
    if (autoRun && autoRun.comparison_id === id) setRun(autoRun);
  }, [autoRun, id]);

  const loadRun = useMutation({
    mutationFn: (runId: number) => getComparisonRun(id, runId),
    onSuccess: (data) => setRun(data),
    onError: (e: Error) => setRunError(e.message),
  });

  const del = useMutation({
    mutationFn: () => deleteComparison(id),
    onSuccess: () => router.push("/compare"),
  });

  if (isLoading || !comparison || comparison.id !== id) {
    if (!isLoading && !comparison) {
      return (
        <div className="mx-auto max-w-6xl px-6 py-8">
          <p className="text-sm text-danger">
            {(comparisonError as Error)?.message ?? "Comparison not found"}
          </p>
          <Link href="/compare" className="mt-2 inline-block text-sm text-primary hover:underline">
            Back to comparisons
          </Link>
        </div>
      );
    }
    return (
      <div className="mx-auto max-w-6xl px-6 py-8">
        <p className="text-sm text-muted-foreground">Loading comparison…</p>
      </div>
    );
  }

  if (editing) {
    return (
      <div className="mx-auto max-w-6xl animate-fade-in px-6 py-8">
        <div className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
          <Link href="/compare" className="hover:text-foreground">
            Compare
          </Link>
          <span>/</span>
          <span>{comparison.name}</span>
        </div>
        <ComparisonForm
          initial={comparison}
          onCancel={() => setEditing(false)}
          onSaved={(updated) => {
            qc.setQueryData(["comparison", id], updated);
            qc.invalidateQueries({ queryKey: ["comparisons"] });
            setEditing(false);
          }}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl animate-fade-in px-6 py-8">
      <div className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
        <Link href="/compare" className="hover:text-foreground">
          Compare
        </Link>
        <span>/</span>
        <span>{comparison.name}</span>
      </div>

      <div className="flex flex-wrap items-start justify-between gap-4 pb-5">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">{comparison.name}</h1>
            {comparison.last_run_status && (
              <Badge tone={RUN_TONE[comparison.last_run_status] ?? "neutral"}>
                last run {comparison.last_run_status}
              </Badge>
            )}
          </div>
          {comparison.description && (
            <p className="max-w-3xl text-sm text-muted-foreground">{comparison.description}</p>
          )}
          <div className="flex flex-wrap items-center gap-2 pt-0.5 text-[11px]">
            <Badge tone="neutral">
              Last9 · {comparison.last9_index_name ?? "index"} · {comparison.last9_region_code}
            </Badge>
            <Badge tone="info">
              New Relic · {comparison.nr_credential_label ?? "connection"}
              {comparison.nr_account_id ? ` · ${comparison.nr_account_id}` : ""}
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <FlowActions comparison={comparison} onEdit={() => setEditing(true)} />
          {confirmDelete ? (
            <>
              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="text-danger"
                onClick={() => del.mutate()}
                disabled={del.isPending}
              >
                {del.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
                Delete
              </Button>
            </>
          ) : (
            <Button
              variant="ghost"
              size="icon"
              aria-label="Delete comparison"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="h-4 w-4 text-danger" />
            </Button>
          )}
        </div>
      </div>

      <QueryPreview comparison={comparison} />

      <RunControls
        comparison={comparison}
        tz={tz}
        setTz={setTz}
        onRun={async (body) => {
          setRunError(null);
          return runOnServer(id, body, setRun, setRunError, qc);
        }}
      />

      {runError && (
        <div className="mb-4 flex items-start gap-2 border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{runError}</span>
        </div>
      )}

      {activeRun ? (
        <RunResult run={activeRun} tz={tz} valueMode={comparison.nr_value_mode} />
      ) : latestId != null && !autoRunFailed ? (
        <div className="flex items-center gap-2 border border-dashed border-border px-4 py-10 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading the latest run…
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 border border-dashed border-border py-16 text-center">
          <div className="flex h-11 w-11 items-center justify-center bg-muted">
            <Clock3 className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium">No run yet</p>
          <p className="max-w-md text-xs text-muted-foreground">
            Pick a window and press Run. The first execution is saved to history so you can replay
            it later.
          </p>
        </div>
      )}

      {runs && runs.length > 0 && (
        <RunHistory
          runs={runs}
          activeRunId={activeRun?.id ?? null}
          loading={loadRun.isPending}
          tz={tz}
          onView={(runId) => loadRun.mutate(runId)}
        />
      )}
    </div>
  );
}

async function runOnServer(
  id: number,
  body: { start_epoch: number; end_epoch: number; bucket_seconds?: number | null },
  setRun: (run: ComparisonRun) => void,
  setError: (message: string | null) => void,
  qc: ReturnType<typeof useQueryClient>
): Promise<void> {
  try {
    const result = await runComparison(id, body);
    setRun(result);
    qc.invalidateQueries({ queryKey: ["comparison-runs", id] });
    qc.invalidateQueries({ queryKey: ["comparisons"] });
    qc.invalidateQueries({ queryKey: ["comparison", id] });
  } catch (error) {
    setError((error as Error).message);
  }
}

function FlowActions({ comparison, onEdit }: { comparison: Comparison; onEdit: () => void }) {
  return (
    <Button variant="outline" size="sm" onClick={onEdit}>
      <Pencil className="h-3.5 w-3.5" />
      Edit
    </Button>
  );
}

function QueryPreview({ comparison }: { comparison: Comparison }) {
  return (
    <details className="group mb-4 border border-border bg-card">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-xs font-medium">
        <span className="flex items-center gap-2">
          <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
          Saved queries
        </span>
        <span className="font-normal text-muted-foreground">
          Last9 pipeline · {comparison.nrql.split("\n")[0].slice(0, 72)}
          {comparison.nrql.split("\n")[0].length > 72 ? "…" : ""}
        </span>
      </summary>
      <div className="grid gap-4 border-t border-border p-4 lg:grid-cols-2">
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Last9 pipeline
          </p>
          <pre className="max-h-56 overflow-auto border border-border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed">
            {JSON.stringify(comparison.last9_pipeline, null, 2)}
          </pre>
        </div>
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            New Relic NRQL
          </p>
          <pre className="max-h-56 overflow-auto border border-border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
            {comparison.nrql}
          </pre>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Value handling:{" "}
            <span className="font-mono">
              {comparison.nr_value_mode}
              {comparison.nr_value_field ? ` · ${comparison.nr_value_field}` : ""}
            </span>
          </p>
        </div>
      </div>
    </details>
  );
}

function RunControls({
  comparison,
  tz,
  setTz,
  onRun,
}: {
  comparison: Comparison;
  tz: Tz;
  setTz: (tz: Tz) => void;
  onRun: (body: {
    start_epoch: number;
    end_epoch: number;
    bucket_seconds?: number | null;
  }) => Promise<void>;
}) {
  const nowSec = Math.floor(Date.now() / 1000);
  const [preset, setPreset] = React.useState<number | "custom">(3600);
  const [customStart, setCustomStart] = React.useState(epochToLocal(nowSec - 3600, "UTC"));
  const [customEnd, setCustomEnd] = React.useState(epochToLocal(nowSec, "UTC"));
  const [bucket, setBucket] = React.useState("");
  const [running, setRunning] = React.useState(false);

  const start = preset === "custom" ? localToEpoch(customStart, tz) : nowSec - preset;
  const end = preset === "custom" ? localToEpoch(customEnd, tz) : nowSec;
  const valid = end > start;
  const preview = valid ? bucketPreview(comparison, bucket, end - start) : null;

  async function run() {
    if (!valid || running || preview?.tooMany) return;
    // Recompute the rolling window at click time; the page may have been open
    // for a while since the render that produced the displayed preview.
    const now = Math.floor(Date.now() / 1000);
    const runStart = preset === "custom" ? localToEpoch(customStart, tz) : now - preset;
    const runEnd = preset === "custom" ? localToEpoch(customEnd, tz) : now;
    if (runEnd <= runStart) return;
    setRunning(true);
    try {
      await onRun({
        start_epoch: runStart,
        end_epoch: runEnd,
        bucket_seconds: bucket.trim() ? Number(bucket) : comparison.bucket_seconds,
      });
    } finally {
      setRunning(false);
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader className="p-4 pb-1">
        <CardTitle className="text-foreground">Run over a time window</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 p-4 pt-2">
        <div className="grid gap-3 lg:grid-cols-[auto_1fr]">
          <div className="space-y-1.5">
            <Label>Timezone</Label>
            <div className="flex items-center gap-1.5">
              {(["UTC", "IST"] as Tz[]).map((zone) => (
                <button
                  key={zone}
                  type="button"
                  onClick={() => setTz(zone)}
                  className={`border px-3 py-1.5 text-xs font-semibold transition-colors ${
                    tz === zone
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {zone}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Window</Label>
            <div className="flex flex-wrap items-center gap-1.5">
              {PRESETS.map((item) => (
                <Button
                  key={item.label}
                  type="button"
                  size="sm"
                  variant={preset === item.seconds ? "primary" : "outline"}
                  onClick={() => setPreset(item.seconds)}
                >
                  {item.label}
                </Button>
              ))}
              <Button
                type="button"
                size="sm"
                variant={preset === "custom" ? "primary" : "outline"}
                onClick={() => setPreset("custom")}
              >
                Custom
              </Button>
            </div>
          </div>
        </div>

        {preset === "custom" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>Start ({tz})</Label>
                <Input
                  type="datetime-local"
                  value={customStart}
                  onChange={(e) => setCustomStart(e.target.value)}
                />
              </div>
            </FieldGroup>
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>End ({tz})</Label>
                <Input
                  type="datetime-local"
                  value={customEnd}
                  onChange={(e) => setCustomEnd(e.target.value)}
                />
              </div>
            </FieldGroup>
          </div>
        )}

        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>Bucket override (seconds)</Label>
                <Input
                  value={bucket}
                  onChange={(e) => setBucket(e.target.value.replace(/[^0-9]/g, ""))}
                  placeholder={
                    comparison.bucket_seconds ? String(comparison.bucket_seconds) : "auto"
                  }
                  inputMode="numeric"
                  className="w-36"
                />
              </div>
            </FieldGroup>
            <p className="pb-2 font-mono text-[11px] text-muted-foreground">
              {valid ? (
                <>
                  {formatEpoch(start, tz)} → {formatEpoch(Math.max(start, end - 1), tz)} {tz}
                </>
              ) : (
                <span className="text-danger">End must be after start.</span>
              )}
            </p>
          </div>
          <Button onClick={run} disabled={!valid || running || Boolean(preview?.tooMany)}>
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {running ? "Running both queries…" : "Run comparison"}
          </Button>
        </div>
        {preview && (
          <p
            className={`font-mono text-[11px] ${
              preview.tooMany ? "text-danger" : "text-muted-foreground"
            }`}
          >
            Effective bucket: {formatDuration(preview.bucket)} · {preview.points} points
            {preview.tooMany &&
              ` — over the 500-point limit; use at least ${formatDuration(preview.minBucket)}`}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function runExportCell(value: unknown): string {
  const text = value == null ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** Export the aligned per-bucket comparison, not the uncorrelated raw rows. */
function exportComparisonRun(run: ComparisonRun, format: "csv" | "txt") {
  const starts = Array.from(
    new Set([...run.last9.series, ...run.newrelic.series].map((point) => point.start_epoch))
  ).sort((a, b) => a - b);
  const last9 = new Map(run.last9.series.map((point) => [point.start_epoch, point.value]));
  const newrelic = new Map(run.newrelic.series.map((point) => [point.start_epoch, point.value]));
  const ends = new Map(
    [...run.last9.series, ...run.newrelic.series].map((point) => [
      point.start_epoch,
      point.end_epoch,
    ])
  );
  const rows: (string | number)[][] = [
    ["bucket_start_utc", "bucket_end_utc", "last9", "newrelic", "delta"],
    ...starts.map((start) => {
      const l9 = last9.get(start);
      const nr = newrelic.get(start);
      return [
        new Date(start * 1000).toISOString(),
        new Date((ends.get(start) ?? start + run.bucket_seconds) * 1000).toISOString(),
        l9 ?? "",
        nr ?? "",
        l9 != null && nr != null ? l9 - nr : "",
      ];
    }),
  ];
  const text = `${rows.map((row) => row.map(runExportCell).join(",")).join("\n")}\n`;
  const stamp = new Date(run.start_epoch * 1000).toISOString().slice(0, 16).replace(/[:T]/g, "-");
  const blob = new Blob([text], {
    type: format === "csv" ? "text/csv" : "text/plain",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `comparison_${run.comparison_id}_run_${run.id}_${stamp}.${format}`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function RunResult({
  run,
  tz,
  valueMode,
}: {
  run: ComparisonRun;
  tz: Tz;
  valueMode: ComparisonValueMode;
}) {
  const comparable = run.last9.total != null && run.newrelic.total != null;
  const isCount = valueMode === "sum";
  const bothZero = comparable && run.last9.total === 0 && run.newrelic.total === 0;
  const pctDiff = comparable ? (bothZero ? 0 : run.pct_diff) : null;
  const tone = pctDiff == null && comparable ? "danger" : toneFor(pctDiff);
  const diffLabel = pctDiff == null && comparable ? "mismatch" : labelFor(pctDiff);

  return (
    <div className="space-y-4">
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label="Last9"
          value={fmt(run.last9.total)}
          sub={`${run.last9.series.length} buckets`}
          color={LAST9_COLOR}
        />
        <MetricCard
          label="New Relic"
          value={fmt(run.newrelic.total)}
          sub={`${run.newrelic.series.length} buckets`}
          color={NEWRELIC_COLOR}
        />
        <MetricCard
          label="Last9 − New Relic"
          value={fmt(run.delta)}
          sub={
            pctDiff == null
              ? comparable
                ? "New Relic returned 0"
                : "not comparable"
              : pct(pctDiff)
          }
        />
        <Card>
          <CardContent className="p-4">
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Difference
            </p>
            <div className="mt-2 flex items-center gap-2">
              <Badge tone={tone}>{diffLabel}</Badge>
              {!isCount && run.newrelic.ok && (
                <span className="text-[11px] text-muted-foreground">
                  value mode {String(run.newrelic.metadata?.value_field ?? "")}
                </span>
              )}
            </div>
            <p className="mt-1.5 text-xs text-muted-foreground">
              {comparable
                ? "Share of the New Relic total"
                : "One side failed — compare the errors below."}
            </p>
          </CardContent>
        </Card>
      </div>

      {(run.status !== "ok" || run.last9.error || run.newrelic.error) && (
        <div className="space-y-2">
          {run.last9.error && (
            <div className="flex items-start gap-2 border border-warning/30 bg-warning/10 px-4 py-3 text-xs text-foreground">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              <div>
                <span className="font-semibold">Last9: </span>
                {run.last9.error}
              </div>
            </div>
          )}
          {run.newrelic.error && (
            <div className="flex items-start gap-2 border border-danger/30 bg-danger/10 px-4 py-3 text-xs text-foreground">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <div>
                <span className="font-semibold">New Relic: </span>
                {run.newrelic.error}
              </div>
            </div>
          )}
        </div>
      )}

      <Card>
        <CardHeader className="p-4 pb-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-foreground">Trend</CardTitle>
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-mono text-[11px] text-muted-foreground">
                {formatEpoch(run.start_epoch, tz)} →{" "}
                {formatEpoch(Math.max(run.start_epoch, run.end_epoch - 1), tz)} {tz} ·{" "}
                {run.bucket_seconds}s buckets
              </p>
              <Button
                size="sm"
                variant="outline"
                onClick={() => exportComparisonRun(run, "csv")}
                disabled={run.last9.series.length === 0 && run.newrelic.series.length === 0}
                title="Aligned per-bucket comparison as comma-separated CSV"
              >
                <Download className="h-3.5 w-3.5" />
                Export CSV
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => exportComparisonRun(run, "txt")}
                disabled={run.last9.series.length === 0 && run.newrelic.series.length === 0}
                title="Aligned per-bucket comparison as comma-separated text"
              >
                <Download className="h-3.5 w-3.5" />
                Export TXT
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-4 pt-1">
          {run.last9.series.length > 0 && run.newrelic.series.length > 0 ? (
            <ComparisonChart
              tz={tz}
              start={run.start_epoch}
              end={run.end_epoch}
              series={[
                {
                  label: "Last9",
                  color: LAST9_COLOR,
                  points: run.last9.series,
                },
                {
                  label: "New Relic",
                  color: NEWRELIC_COLOR,
                  points: run.newrelic.series,
                },
              ]}
            />
          ) : (
            <div className="flex h-40 items-center justify-center border border-dashed border-border px-4 text-center text-xs text-muted-foreground">
              The chart needs a time series from both sides. New Relic must return buckets (use an
              aggregate query, e.g. <span className="font-mono">count(*)</span>), and Last9 must not
              be a total-only aggregate pipeline.
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <RawResult
          title="Last9 result"
          color={LAST9_COLOR}
          side={run.last9}
          total={run.last9.total}
          note={run.last9_pipeline_effective?.series ? "windowed rows" : "aggregate rows"}
        />
        <RawResult
          title="New Relic result"
          color={NEWRELIC_COLOR}
          side={run.newrelic}
          total={run.newrelic.total}
          note={
            run.newrelic.metadata?.value_field
              ? `numeric column ${String(run.newrelic.metadata.value_field)}`
              : "NRQL rows"
          }
        />
      </div>

      <details className="group border border-border bg-card">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-xs font-medium">
          <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
          Effective queries and run details
        </summary>
        <div className="grid gap-4 border-t border-border p-4 lg:grid-cols-2">
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              NRQL that ran
            </p>
            <pre className="max-h-56 overflow-auto border border-border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
              {run.nrql_effective ?? "—"}
            </pre>
            <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-muted-foreground">
              <span>New Relic took {run.newrelic.elapsed_ms ?? "—"}ms</span>
              <span>Last9 took {run.last9.elapsed_ms ?? "—"}ms</span>
              <span>Last9 reduces {run.last9_pipeline_effective?.value_mode ?? "sum"}</span>
              <span>run #{run.id}</span>
            </div>
          </div>
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Last9 pipelines that ran
            </p>
            <pre className="max-h-56 overflow-auto border border-border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed">
              {JSON.stringify(run.last9_pipeline_effective ?? {}, null, 2)}
            </pre>
          </div>
        </div>
      </details>
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub: string;
  color?: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2">
          {color && (
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} aria-hidden />
          )}
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </p>
        </div>
        <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
        <p className="mt-1 text-[11px] text-muted-foreground">{sub}</p>
      </CardContent>
    </Card>
  );
}

function RawResult({
  title,
  color,
  side,
  total,
  note,
}: {
  title: string;
  color: string;
  side: ComparisonSide;
  total: number | null;
  note: string;
}) {
  const columns = React.useMemo(() => {
    const keys = new Set<string>();
    for (const row of side.raw.slice(0, 50)) {
      for (const key of Object.keys(row)) keys.add(key);
    }
    return Array.from(keys);
  }, [side.raw]);

  return (
    <Card>
      <CardHeader className="p-4 pb-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: color }}
              aria-hidden
            />
            <CardTitle className="text-foreground">{title}</CardTitle>
          </div>
          <Badge tone={side.ok ? "success" : "danger"}>{side.ok ? "ok" : "failed"}</Badge>
        </div>
        <p className="text-[11px] text-muted-foreground">
          total {fmt(total)} · {note} · {Math.min(50, side.raw.length)} rows shown
        </p>
      </CardHeader>
      <CardContent className="p-4 pt-1">
        {side.error && (
          <p className="mb-2 border border-warning/30 bg-warning/10 px-2 py-1.5 text-[11px] text-foreground">
            {side.error}
          </p>
        )}
        {side.raw.length === 0 ? (
          <p className="py-8 text-center text-xs text-muted-foreground">No rows returned.</p>
        ) : (
          <div className="max-h-72 overflow-auto border border-border">
            <table className="w-full border-collapse text-left font-mono text-[11px]">
              <thead className="sticky top-0 bg-muted">
                <tr>
                  {columns.map((column) => (
                    <th
                      key={column}
                      className="whitespace-nowrap border-b border-border px-2 py-1.5 font-semibold text-muted-foreground"
                    >
                      {column === "__ts__" ? "window_start" : column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {side.raw.slice(0, 50).map((row, index) => (
                  <tr key={index} className="border-b border-border/60 last:border-0">
                    {columns.map((column) => (
                      <td key={column} className="max-w-[260px] truncate px-2 py-1.5">
                        {formatCell(row[column], column)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function formatCell(value: unknown, column: string): string {
  if (value == null) return "—";
  if (["__ts__", "timestamp", "beginTime", "endTime"].includes(column)) {
    const seconds = epochSeconds(value);
    if (seconds != null) {
      return `${new Date(seconds * 1000).toISOString().slice(0, 19).replace("T", " ")} UTC`;
    }
  }
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function epochSeconds(value: unknown): number | null {
  if (typeof value === "string") {
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) return parsed / 1000;
  }
  if (typeof value !== "number" && typeof value !== "string") return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  if (Math.abs(n) >= 10 ** 17) return n / 1_000_000_000;
  if (Math.abs(n) >= 10 ** 14) return n / 1_000_000;
  if (Math.abs(n) >= 10 ** 11) return n / 1_000;
  return n;
}

function RunHistory({
  runs,
  activeRunId,
  loading,
  tz,
  onView,
}: {
  runs: ComparisonRunSummary[];
  activeRunId: number | null;
  loading: boolean;
  tz: Tz;
  onView: (id: number) => void;
}) {
  return (
    <Card className="mt-4">
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-foreground">Run history</CardTitle>
      </CardHeader>
      <CardContent className="p-4 pt-1">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-2 py-2 font-medium">Run</th>
                <th className="px-2 py-2 font-medium">Window</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 font-medium">Last9</th>
                <th className="px-2 py-2 font-medium">New Relic</th>
                <th className="px-2 py-2 text-right font-medium">View</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr
                  key={run.id}
                  className={`border-t border-border/60 ${
                    run.id === activeRunId ? "bg-primary/5" : ""
                  }`}
                >
                  <td className="whitespace-nowrap px-2 py-2 font-mono">#{run.id}</td>
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">
                    {formatEpoch(run.start_epoch, tz)} → {formatEpoch(run.end_epoch - 1, tz)}
                  </td>
                  <td className="px-2 py-2">
                    <Badge tone={RUN_TONE[run.status] ?? "neutral"}>{run.status}</Badge>
                  </td>
                  <td className="px-2 py-2 font-mono">{fmt(run.last9_total)}</td>
                  <td className="px-2 py-2 font-mono">{fmt(run.newrelic_total)}</td>
                  <td className="px-2 py-2 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => onView(run.id)}
                      disabled={loading}
                    >
                      {loading ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RefreshCw className="h-3.5 w-3.5" />
                      )}
                      View
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
