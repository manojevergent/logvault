"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  Copy,
  Download,
  Loader2,
  Pause,
  Play,
  PlayCircle,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  API_BASE,
  JOB_TONE,
  Job,
  cancelJob,
  createJob,
  getJob,
  getSettings,
  pauseJob,
  resumeJob,
  retryJob,
  useRole,
} from "@/lib/api";
import { formatDuration, formatRange, useTz } from "@/lib/time";

type Progress = {
  status: string;
  rows_written: number;
  completed_chunks: number;
  total_chunks: number;
};
type FeedItem = { level: string; message: string; rows_delta: number; ts: string | null };

const TERMINAL = ["completed", "failed", "canceled"];

function formatBytes(n: number | null): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// The link's lifetime is a server setting (`download_url_ttl_seconds`); this is
// only the fallback for users who can't read /settings (admin-only).
const DEFAULT_DOWNLOAD_TTL_SEC = 7 * 86400;

function downloadExpiry(
  finishedAt: string | null,
  ttlSeconds: number,
  now: number
): { expired: boolean; remaining: string } | null {
  if (!finishedAt) return null;
  const remaining = (Date.parse(finishedAt) + ttlSeconds * 1000 - now) / 1000;
  return { expired: remaining <= 0, remaining: formatDuration(remaining) };
}

export default function JobDetailPage() {
  const id = Number(useParams().id);
  const [tz, setTz] = useTz();
  const router = useRouter();

  // The preview kept the job's full start/end — only the worker narrowed the
  // window — so the real run is the same job with is_preview off.
  const runFull = useMutation({
    mutationFn: () => {
      if (!job) throw new Error("job not loaded");
      const agg = job.filter_spec?.aggregation;
      return createJob({
        credential_id: job.credential_id,
        index_target_id: job.index_target_id,
        region_code: job.region_code,
        start_epoch: job.start_epoch,
        end_epoch: job.end_epoch,
        chunk_hours: job.chunk_hours,
        id_batch_size: job.id_batch_size,
        phrases: job.filter_spec?.phrases ?? [],
        ids: job.filter_spec?.ids ?? [],
        message_types: job.filter_spec?.message_types ?? [],
        output_format: job.output_format === "jsonl" ? "jsonl" : "csv",
        is_preview: false,
        label: job.filter_spec?.label ?? "",
        customer: job.filter_spec?.customer ?? "",
        aggregation: agg ?? null,
      });
    },
    onSuccess: (created) => router.push(`/jobs/${created.id}`),
  });
  const qc = useQueryClient();

  const {
    data: job,
    error: jobError,
    refetch: refetchJob,
  } = useQuery({
    queryKey: ["job", id],
    queryFn: () => getJob(id),
    // A slow safety net, not the update mechanism: SSE pushes progress and the
    // stream's terminal event triggers a refetch. At 4s this refetched the whole
    // job row — filter_spec, preview, aggregation_result — 15x a minute per
    // viewer, duplicating data the open stream had already delivered. Kept
    // (rather than removed) so the page still updates if SSE can't connect.
    refetchInterval: 30000,
  });
  const [progress, setProgress] = React.useState<Progress | null>(null);
  const [feed, setFeed] = React.useState<FeedItem[]>([]);
  const [errorExpanded, setErrorExpanded] = React.useState(false);
  const [confirmCancel, setConfirmCancel] = React.useState(false);
  // "connecting" until the stream opens; "reconnecting" while EventSource is
  // retrying, so a frozen feed never passes for a live one.
  const [conn, setConn] = React.useState<"connecting" | "live" | "reconnecting" | "closed">(
    "connecting"
  );
  // Ticks so elapsed/ETA keep moving between polls; stopped once the job ends.
  const [now, setNow] = React.useState(() => Date.now());

  // Only admins can read /settings; everyone else uses the deployment default.
  const role = useRole();
  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
    enabled: role === "admin",
    staleTime: Infinity,
    retry: false,
  });

  React.useEffect(() => {
    if (
      typeof Notification !== "undefined" &&
      Notification.permission === "default" &&
      (job?.status === "running" || job?.status === "queued")
    ) {
      Notification.requestPermission();
    }
  }, [job?.status]);

  // Latched: the server mints a fresh ticket (new expiry) on every job fetch,
  // so depending on the live value would tear down and rebuild the stream on
  // every poll. The first one is good for 12h — far longer than any connection.
  const progressUrl = job?.progress_url ?? null;
  const progressUrlRef = React.useRef<string | null>(null);
  if (progressUrl && !progressUrlRef.current) progressUrlRef.current = progressUrl;
  const streamUrl = progressUrlRef.current;

  React.useEffect(() => {
    if (!id || !streamUrl) return;
    // EventSource can't set an Authorization header. The ticket is scoped to
    // this one job, so the session token never travels in a URL (and so never
    // lands in an access log or browser history).
    const es = new EventSource(`${API_BASE}${streamUrl}`);
    es.onopen = () => setConn("live");
    es.onmessage = (e) => {
      setConn("live");
      const msg = JSON.parse(e.data);
      if (msg.type === "progress") {
        setProgress(msg);
      } else if (msg.type === "event") {
        setFeed((f) => [{ ...msg }, ...f].slice(0, 200));
      } else if (msg.type === "error") {
        // The server ends the stream after this (the job is gone), so close
        // rather than let EventSource retry a dead job forever.
        setFeed((f) =>
          [{ level: "error", message: msg.message, rows_delta: 0, ts: null }, ...f].slice(0, 200)
        );
        es.close();
        setConn("closed");
      } else if (TERMINAL.includes(msg.type)) {
        es.close();
        setConn("closed");
        qc.invalidateQueries({ queryKey: ["job", id] });
        if (typeof Notification !== "undefined" && Notification.permission === "granted") {
          new Notification(`LogVault Job #${id}`, {
            body: msg.type === "completed" ? "Extraction completed." : `Job ${msg.type}.`,
          });
        }
      }
    };
    // Deliberately NOT closing: EventSource reconnects on its own after a
    // dropped connection (laptop sleep, VPN blip). Closing here left the feed
    // frozen on "Scanning…" for the rest of a multi-hour job.
    es.onerror = () => setConn(es.readyState === EventSource.CLOSED ? "closed" : "reconnecting");
    return () => es.close();
  }, [id, qc, streamUrl]);

  const status = progress?.status ?? job?.status ?? "queued";
  const rows = progress?.rows_written ?? job?.rows_written ?? 0;
  const completed = progress?.completed_chunks ?? job?.completed_chunks ?? 0;
  const total = progress?.total_chunks ?? job?.total_chunks ?? 0;
  const pct = total ? Math.round((completed / total) * 100) : 0;
  const done = TERMINAL.includes(status);

  React.useEffect(() => {
    if (done) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [done]);

  // Elapsed runs from the job's own start, not from when this page was opened:
  // reopening a 5-hour job at chunk 19/24 used to report ~1M rows/s and "ETA 1s".
  const startedMs = job?.started_at ? Date.parse(job.started_at) : null;
  const finishedMs = job?.finished_at ? Date.parse(job.finished_at) : null;
  const elapsed = startedMs ? Math.max(0, ((finishedMs ?? now) - startedMs) / 1000) : 0;
  const throughput = elapsed > 1 && rows ? Math.round(rows / elapsed) : 0;
  const eta =
    completed > 0 && total > completed && elapsed > 0
      ? Math.round((elapsed / completed) * (total - completed))
      : null;

  const etaDisplay =
    status === "queued"
      ? "Waiting…"
      : status === "paused"
        ? "Paused"
        : eta != null
          ? formatDuration(eta)
          : "—";

  const refresh = () => qc.invalidateQueries({ queryKey: ["job", id] });
  const pause = useMutation({ mutationFn: () => pauseJob(id), onSuccess: refresh });
  const resume = useMutation({ mutationFn: () => resumeJob(id), onSuccess: refresh });
  const cancel = useMutation({
    mutationFn: () => cancelJob(id),
    onSuccess: () => {
      setConfirmCancel(false);
      refresh();
    },
  });
  const retry = useMutation({
    mutationFn: () => retryJob(id),
    onSuccess: (newJob) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      window.location.href = `/jobs/${newJob.id}`;
    },
  });
  // A rejected pause/resume/cancel/retry used to look exactly like an applied
  // one — the button just went back to normal.
  const actionError = ([pause, resume, cancel, retry, runFull].find((m) => m.isError)?.error ??
    null) as Error | null;

  // A 404, a 403 or an API outage used to sit on "Loading…" forever.
  if (!job) {
    if (jobError) {
      return (
        <div className="mx-auto max-w-5xl animate-fade-in px-6 py-8">
          <div className="flex items-center justify-between gap-3 border border-danger bg-muted px-4 py-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 text-danger" />
              <p className="text-sm">
                Couldn&apos;t load job #{id}.{" "}
                <span className="text-muted-foreground">{(jobError as Error).message}</span>
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Link href="/jobs">
                <Button size="sm" variant="ghost">
                  All jobs
                </Button>
              </Link>
              <Button size="sm" variant="outline" onClick={() => refetchJob()}>
                Retry
              </Button>
            </div>
          </div>
        </div>
      );
    }
    return <div className="px-6 py-8 text-sm text-muted-foreground">Loading…</div>;
  }

  const expiry = downloadExpiry(
    job.finished_at,
    settings?.download_url_ttl_seconds ?? DEFAULT_DOWNLOAD_TTL_SEC,
    now
  );

  return (
    <div className="mx-auto max-w-5xl animate-fade-in px-6 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold tracking-tight">Job #{job.id}</h1>
            <Badge tone={JOB_TONE[status as keyof typeof JOB_TONE] ?? "neutral"}>{status}</Badge>
            {job.is_preview && <Badge tone="warning">preview</Badge>}
          </div>
          <p className="font-mono text-xs text-muted-foreground">
            {job.region_code} · {formatRange(job.start_epoch, job.end_epoch, tz)}{" "}
            <button
              type="button"
              onClick={() => setTz(tz === "IST" ? "UTC" : "IST")}
              className="underline decoration-dotted underline-offset-2 hover:text-foreground"
              title={`Showing ${tz} — click to switch`}
            >
              {tz}
            </button>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(status === "running" || status === "queued") && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => pause.mutate()}
              disabled={pause.isPending}
            >
              <Pause className="h-3.5 w-3.5" /> Pause
            </Button>
          )}
          {status === "paused" && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => resume.mutate()}
              disabled={resume.isPending}
            >
              <Play className="h-3.5 w-3.5" /> Resume
            </Button>
          )}
          {/* Cancel sits next to Pause and throws away everything still to
              run, so it asks first — see the confirmation strip below. */}
          {!done && !confirmCancel && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmCancel(true)}
              disabled={cancel.isPending}
            >
              <Ban className="h-3.5 w-3.5" /> Cancel
            </Button>
          )}
          {(status === "failed" || status === "canceled") && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => retry.mutate()}
              disabled={retry.isPending}
            >
              <RefreshCw className="h-3.5 w-3.5" /> Retry
            </Button>
          )}
          {/* A test run proves the filter; this carries the same settings
              straight into the real extraction over the full range, rather than
              making you rebuild the form from scratch. */}
          {job.is_preview && job.status === "completed" && (
            <Button size="sm" disabled={runFull.isPending} onClick={() => runFull.mutate()}>
              {runFull.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <PlayCircle className="h-3.5 w-3.5" />
              )}
              Run full extraction
            </Button>
          )}
          <Link href={`/jobs/new?from=${job.id}`}>
            <Button size="sm" variant="outline">
              <Copy className="h-3.5 w-3.5" /> Clone
            </Button>
          </Link>
          {/* An expired link 404s at the API, so the button stops being a
              button rather than sending you to a raw error page. */}
          {job.download_url &&
            (expiry?.expired ? (
              <Button size="sm" disabled title="The signed link for this file has expired">
                <Download className="h-3.5 w-3.5" />
                Download expired
              </Button>
            ) : (
              <a href={`${API_BASE}${job.download_url}`}>
                <Button size="sm">
                  <Download className="h-3.5 w-3.5" />
                  Download {job.output_format.toUpperCase()}
                  {job.output_size_bytes ? (
                    <span className="ml-1 opacity-60">· {formatBytes(job.output_size_bytes)}</span>
                  ) : null}
                </Button>
              </a>
            ))}
        </div>
      </div>

      {confirmCancel && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 border border-danger bg-muted px-4 py-3">
          <p className="text-sm">
            Cancel job #{job.id}?{" "}
            <span className="text-muted-foreground">
              {total > completed ? (
                <>
                  {completed} of {total} chunks ({rows.toLocaleString()} rows) are kept as a partial
                  file; the remaining {total - completed} chunk
                  {total - completed === 1 ? "" : "s"} are discarded and can&apos;t be resumed —
                  re-running starts from scratch.
                </>
              ) : (
                <>
                  Whatever has been written ({rows.toLocaleString()} rows) is kept as a partial
                  file; the job can&apos;t be resumed afterwards — re-running starts from scratch.
                </>
              )}
            </span>
          </p>
          <div className="flex shrink-0 items-center gap-2">
            <Button size="sm" variant="ghost" onClick={() => setConfirmCancel(false)}>
              Keep running
            </Button>
            <Button size="sm" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
              {cancel.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Yes, cancel
            </Button>
          </div>
        </div>
      )}

      {actionError && (
        <p className="mb-3 text-xs text-danger">That action failed: {actionError.message}</p>
      )}

      {job.download_url && expiry && (
        <p className={`mb-3 text-xs ${expiry.expired ? "text-danger" : "text-muted-foreground"}`}>
          {expiry.expired
            ? "Download link has expired — re-run the extraction to get a fresh file."
            : `Download link expires in ${expiry.remaining}`}
        </p>
      )}

      <Card className="mb-3">
        <CardContent className="space-y-2 p-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Rows written" value={rows.toLocaleString()} />
            <Stat label="Chunks" value={`${completed} / ${total || "?"}`} />
            <Stat
              label="Throughput"
              value={throughput ? `${throughput.toLocaleString()}/s` : "—"}
            />
            {/* Once a job has finished, "ETA" has no meaning — the same slot
                reports how long the run actually took. */}
            <Stat
              label={done ? "Duration" : "ETA"}
              value={done ? (elapsed > 0 ? formatDuration(elapsed) : "—") : etaDisplay}
            />
          </div>
          <div className="flex items-center gap-2">
            <div
              role="progressbar"
              aria-label="Chunks completed"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              className="h-4 w-full overflow-hidden bg-muted"
            >
              <div
                className="h-full bg-success transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="w-9 shrink-0 text-right font-mono text-xs text-muted-foreground">
              {pct}%
            </span>
          </div>
          {job.error_message && (
            <div className="space-y-0.5">
              <p className="font-mono text-xs text-danger">
                {errorExpanded
                  ? job.error_message
                  : (job.error_message.split("\n").filter(Boolean).at(-1) ?? job.error_message)}
              </p>
              {job.error_message.includes("\n") && (
                <button
                  onClick={() => setErrorExpanded((v) => !v)}
                  className="text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground"
                >
                  {errorExpanded ? "show less" : "show full error"}
                </button>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <AggregationResultCard job={job} />

      {job.preview && job.preview.length > 0 && (
        <Card className="mb-3">
          <CardHeader className="p-3 pb-1">
            <CardTitle className="text-foreground">
              Sample rows {job.is_preview && "(filter test)"}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-0">
            <ul className="max-h-44 space-y-0.5 overflow-y-auto scrollbar-thin font-mono text-xs">
              {job.preview.map((r, i) => (
                <li key={i} className="flex gap-3">
                  <span className="shrink-0 text-muted-foreground">{r.timestamp}</span>
                  <span className="truncate">{r.message}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between p-3 pb-1">
          <CardTitle className="text-foreground">Live feed</CardTitle>
          {!done && (
            <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  conn === "live" ? "bg-success" : "animate-pulse bg-warning"
                }`}
                aria-hidden
              />
              {conn === "live"
                ? "live"
                : conn === "connecting"
                  ? "connecting…"
                  : conn === "reconnecting"
                    ? "reconnecting…"
                    : "disconnected"}
            </span>
          )}
        </CardHeader>
        <CardContent className="p-3 pt-0">
          {feed.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              {!done && conn === "reconnecting"
                ? "Lost the live stream — reconnecting. Progress above keeps updating."
                : !done && conn === "closed"
                  ? "Live stream disconnected — reload to reconnect. Progress above keeps updating."
                  : status === "running"
                    ? "Scanning…"
                    : "Waiting for events…"}
            </p>
          ) : (
            <ul className="max-h-52 space-y-0.5 overflow-y-auto scrollbar-thin font-mono text-xs">
              {feed.map((item, i) => (
                <li
                  key={i}
                  className={item.level === "error" ? "text-danger" : "text-muted-foreground"}
                >
                  {item.ts && (
                    <span className="mr-2 text-muted-foreground/50">{item.ts.slice(11, 19)}</span>
                  )}
                  {item.message}
                  {item.rows_delta > 0 && (
                    <span className="text-success"> +{item.rows_delta} rows</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function csvEscape(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

function downloadAggregationCsv(jobId: number, agg: NonNullable<Job["aggregation_result"]>) {
  const cols = [...agg.group_by, ...agg.unique_fields.map((f) => `unique_${f}`)];
  const rows = agg.groups.map((g) => [
    ...agg.group_by.map((f) => g.key[f] ?? ""),
    ...agg.unique_fields.map((f) => String(g.unique_counts[f] ?? 0)),
  ]);
  const csv = [cols, ...rows].map((r) => r.map(csvEscape).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `job_${jobId}_summary.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function AggregationResultCard({ job }: { job: Job }) {
  const agg = job.aggregation_result;
  // A regex that misses a value format drops those rows silently and reports a
  // plausible but low count, so a large unmatched share is flagged loudly.
  const parsed = (agg?.rows_matched ?? 0) + (agg?.rows_unmatched ?? 0);
  const unmatchedShare = parsed > 0 ? (agg?.rows_unmatched ?? 0) / parsed : 0;
  if (!agg) return null;

  return (
    <Card className="mb-3">
      <CardHeader className="flex flex-row items-center justify-between p-3 pb-1">
        <CardTitle className="text-foreground">
          {job.rollup_of ? "Combined results" : "Parse & aggregate results"}
        </CardTitle>
        {/* The server-side summary is the complete breakdown; the client-side
            export can only reach the groups embedded in the job row, which are
            capped. Prefer the file whenever the job has finished writing one. */}
        <div className="flex items-center gap-2">
          {job.counts_url && (
            <a href={`${API_BASE}${job.counts_url}`}>
              <Button size="sm" variant="outline" title="One row per value with its occurrence count">
                <Download className="h-3.5 w-3.5" /> Counts per {agg.unique_fields[0] ?? "value"}
              </Button>
            </a>
          )}
          {job.summary_url ? (
            <a href={`${API_BASE}${job.summary_url}`}>
              <Button size="sm" variant="outline">
                <Download className="h-3.5 w-3.5" /> Summary CSV
              </Button>
            </a>
          ) : (
            <Button size="sm" variant="outline" onClick={() => downloadAggregationCsv(job.id, agg)}>
              <Download className="h-3.5 w-3.5" /> Summary CSV
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <p className="mb-2 text-xs text-muted-foreground">
          {job.rollup_of
            ? `Merged ${job.rollup_of.source_job_ids?.length ?? 0} run(s)${
                job.rollup_of.label ? ` · ${job.rollup_of.label}` : ""
              } — recurring values counted once, not once per run`
            : `${agg.rows_matched} row${agg.rows_matched === 1 ? "" : "s"} matched the parse pattern`}
          {agg.rows_unmatched > 0 &&
            ` · ${agg.rows_unmatched} row${agg.rows_unmatched === 1 ? "" : "s"} didn't match`}
        </p>
        {unmatchedShare >= 0.1 && (
          <p className="mb-2 text-xs text-danger">
            <strong>{Math.round(unmatchedShare * 100)}% of rows didn&apos;t match the parse
            pattern</strong> — these counts exclude them and are almost certainly low. Usually the
            regex is too narrow for one of the value formats (e.g. <code>\d+</code> won&apos;t match
            a UUID or hex id; <code>\S+</code> matches all three).
          </p>
        )}
        {agg.truncated && (
          <p className="mb-2 text-xs text-warning">
            Showing {agg.groups.length} of {agg.total_groups} groups — export the CSV for all of
            them.
          </p>
        )}
        {agg.groups.length === 0 ? (
          <p className="text-xs text-muted-foreground">No groups yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-muted-foreground">
                  {agg.group_by.map((f) => (
                    <th key={f} className="px-2 py-1 font-medium">
                      {f}
                    </th>
                  ))}
                  {agg.unique_fields.map((f) => (
                    <th key={f} className="px-2 py-1 font-medium">
                      Unique {f}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {agg.groups.map((g, i) => (
                  <tr key={i} className="border-t border-border">
                    {agg.group_by.map((f) => (
                      <td key={f} className="px-2 py-1">
                        {g.key[f] ?? ""}
                      </td>
                    ))}
                    {agg.unique_fields.map((f) => (
                      <td key={f} className="px-2 py-1 font-mono">
                        {g.unique_counts[f] ?? 0}
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="font-mono text-sm font-semibold tracking-tight">{value}</p>
    </div>
  );
}
