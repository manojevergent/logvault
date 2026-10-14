"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Download,
  FileDown,
  ListChecks,
  Loader2,
  Plus,
  Search,
  X,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { ImportJsonButton } from "@/components/import-json-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  API_BASE,
  JOB_TONE,
  Job,
  JobExport,
  JobStatus,
  bulkCancelJobs,
  downloadJson,
  exportJob,
  importJob,
} from "@/lib/api";
import { isActive, useJobs } from "@/lib/use-jobs";
import { Tz, formatDuration, formatEpoch, formatRange, useTz } from "@/lib/time";

const STATUS_TABS: Array<"all" | JobStatus> = [
  "all",
  "running",
  "queued",
  "paused",
  "completed",
  "failed",
  "canceled",
];

const PAGE_LIMIT = 200;

// Every one of these is an INVOICE_* extract, so the prefix is noise in a column
// where the distinguishing part is what follows it.
function extractionName(job: Job): string | null {
  const label = job.filter_spec?.label;
  if (!label) return null;
  return label.replace(/^INVOICE_/, "");
}

export default function JobsPage() {
  const [search, setSearch] = React.useState("");
  const [tab, setTab] = React.useState<"all" | JobStatus>("all");
  const [tz, setTz] = useTz();
  const searchRef = React.useRef<HTMLInputElement>(null);
  const qc = useQueryClient();

  const { data: jobs, isLoading, error, refetch, isFetching } = useJobs(PAGE_LIMIT);

  // Only active jobs are cancelable, so selection is scoped to them.
  const [selected, setSelected] = React.useState<Set<number>>(new Set());

  // A selected job can finish (or get canceled elsewhere) between a click and
  // the next poll. Pruned here rather than left for the bulk-cancel response
  // to explain, so "N selected" never promises a cancel that a background poll
  // already made moot.
  React.useEffect(() => {
    if (!jobs) return;
    const stillActive = new Set(jobs.filter(isActive).map((j) => j.id));
    setSelected((prev) => {
      if ([...prev].every((id) => stillActive.has(id))) return prev;
      return new Set([...prev].filter((id) => stillActive.has(id)));
    });
  }, [jobs]);
  const [confirmBulkCancel, setConfirmBulkCancel] = React.useState(false);
  const [bulkResult, setBulkResult] = React.useState<{
    canceled: number;
    skipped: number;
  } | null>(null);

  const bulkCancel = useMutation({
    mutationFn: (ids: number[]) => bulkCancelJobs(ids),
    onSuccess: (result) => {
      setSelected(new Set());
      setConfirmBulkCancel(false);
      setBulkResult({
        canceled: result.canceled.length,
        skipped: Object.keys(result.skipped).length,
      });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  function toggleSelected(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Ages have to keep counting on a tab left open: a job stuck in `queued` is
  // only visible as an age that grows, and the rows are memoised so a poll that
  // changes nothing about a job won't re-render it. 30s — ages are shown in
  // minutes once past the first one.
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  // "/" jumps to the filter from anywhere on the page; Escape clears and exits.
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = document.activeElement;
      const typing = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
      if (e.key === "/" && !typing) {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === "Escape" && el === searchRef.current) {
        setSearch("");
        searchRef.current?.blur();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const filtered = React.useMemo(() => {
    if (!jobs) return jobs;
    let list = tab === "all" ? jobs : jobs.filter((j) => j.status === tab);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (j) =>
          String(j.id).includes(q) ||
          j.region_code.toLowerCase().includes(q) ||
          (j.credential_label ?? "").toLowerCase().includes(q) ||
          (j.filter_spec?.label ?? "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [jobs, search, tab]);

  const counts = React.useMemo(() => {
    if (!jobs) return {} as Record<string, number>;
    return jobs.reduce<Record<string, number>>((acc, j) => {
      acc[j.status] = (acc[j.status] ?? 0) + 1;
      return acc;
    }, {});
  }, [jobs]);

  // "Select all" only ever touches the cancelable rows in the current
  // filtered view — a completed job never gets swept in by it.
  const cancelableInView = React.useMemo(
    () => (filtered ?? []).filter(isActive),
    [filtered]
  );
  const allInViewSelected =
    cancelableInView.length > 0 && cancelableInView.every((j) => selected.has(j.id));

  function toggleSelectAllInView() {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allInViewSelected) {
        for (const j of cancelableInView) next.delete(j.id);
      } else {
        for (const j of cancelableInView) next.add(j.id);
      }
      return next;
    });
  }

  return (
    <div className="mx-auto max-w-6xl animate-fade-in px-6 py-4">
      <div className="flex flex-wrap items-end justify-between gap-2 pb-3">
        <div className="space-y-0.5">
          <h1 className="text-base font-semibold tracking-tight">Jobs</h1>
          <p className="text-xs text-muted-foreground">
            Every extraction, newest first.
            {/* Always-reserved slot, so the poll indicator never shifts the layout. */}
            <span
              className={`ml-1.5 transition-opacity ${isFetching ? "opacity-60" : "opacity-0"}`}
              aria-hidden
            >
              refreshing…
            </span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              ref={searchRef}
              type="search"
              placeholder="Filter by name, ID, region…"
              aria-label="Filter jobs"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 w-56 border border-border bg-background pl-8 pr-7 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
            {search ? (
              <button
                type="button"
                onClick={() => setSearch("")}
                aria-label="Clear filter"
                className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 text-muted-foreground hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            ) : (
              <kbd
                className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 font-mono text-[10px] text-muted-foreground opacity-50"
                aria-hidden
              >
                /
              </kbd>
            )}
          </div>
          <ImportJsonButton<JobExport>
            label="Import"
            onImport={async (data) => {
              await importJob(data);
              refetch();
            }}
          />
          <Link href="/jobs/new">
            <Button>
              <Plus className="h-4 w-4" />
              New extraction
            </Button>
          </Link>
        </div>
      </div>

      {/* Status tabs */}
      <div className="flex flex-wrap gap-1 pb-3">
        {STATUS_TABS.map((s) => {
          const count = s === "all" ? (jobs?.length ?? 0) : (counts[s] ?? 0);
          const active = tab === s;
          return (
            <button
              key={s}
              onClick={() => setTab(s)}
              aria-pressed={active}
              className={`flex items-center gap-1.5 border px-3 py-1 text-xs font-medium transition-colors ${
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border text-muted-foreground hover:border-foreground hover:text-foreground"
              }`}
            >
              <span className="capitalize">{s}</span>
              <span className={`font-mono ${active ? "opacity-80" : "opacity-60"}`}>{count}</span>
            </button>
          );
        })}
      </div>

      {/* Bulk-selection toolbar. Only ever reachable by checking an active
          row, so the confirm step below never has to re-explain what
          "cancel" costs — that's covered once, same as the single-job flow. */}
      {selected.size > 0 && !confirmBulkCancel && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 border border-border bg-muted px-4 py-2">
          <p className="text-sm">
            <span className="font-medium">{selected.size}</span>{" "}
            {selected.size === 1 ? "job" : "jobs"} selected
          </p>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
            <Button size="sm" variant="outline" onClick={() => setConfirmBulkCancel(true)}>
              Cancel {selected.size}
            </Button>
          </div>
        </div>
      )}

      {confirmBulkCancel && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 border border-danger bg-muted px-4 py-3">
          <p className="text-sm">
            Cancel {selected.size} {selected.size === 1 ? "job" : "jobs"}?{" "}
            <span className="text-muted-foreground">
              Whatever each has written is kept as a partial file; none of them can be resumed —
              re-running starts from scratch.
            </span>
          </p>
          <div className="flex shrink-0 items-center gap-2">
            <Button size="sm" variant="ghost" onClick={() => setConfirmBulkCancel(false)}>
              Keep them
            </Button>
            <Button
              size="sm"
              disabled={bulkCancel.isPending}
              onClick={() => bulkCancel.mutate([...selected])}
            >
              {bulkCancel.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Yes, cancel
            </Button>
          </div>
        </div>
      )}

      {bulkCancel.isError && (
        <div className="mb-3 flex items-center gap-2 border border-danger bg-muted px-4 py-3">
          <AlertTriangle className="h-4 w-4 shrink-0 text-danger" />
          <p className="text-sm">
            Bulk cancel failed.{" "}
            <span className="text-muted-foreground">{(bulkCancel.error as Error).message}</span>
          </p>
        </div>
      )}

      {/* skipped > 0 means some selected jobs finished (or vanished) between
          selection and the click — not an error, just worth saying so the
          count that disappeared from the table isn't a silent surprise. */}
      {bulkResult && (
        <div
          className={`mb-3 flex items-center justify-between gap-3 border px-4 py-2 ${
            bulkResult.skipped > 0 ? "border-warning" : "border-success"
          } bg-muted`}
        >
          <p className="text-sm">
            Canceled {bulkResult.canceled} {bulkResult.canceled === 1 ? "job" : "jobs"}.
            {bulkResult.skipped > 0 && (
              <span className="text-muted-foreground">
                {" "}
                {bulkResult.skipped} {bulkResult.skipped === 1 ? "was" : "were"} already finished
                and skipped.
              </span>
            )}
          </p>
          <button
            type="button"
            onClick={() => setBulkResult(null)}
            aria-label="Dismiss"
            className="shrink-0 p-0.5 text-muted-foreground hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* A failed fetch used to fall through to the "No extractions yet" empty
          state, which reads as "your data is gone" rather than "try again". */}
      {error && (
        <div className="flex items-center justify-between gap-3 border border-danger bg-muted px-4 py-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0 text-danger" />
            <p className="text-sm">
              Couldn&apos;t load jobs.{" "}
              <span className="text-muted-foreground">{(error as Error).message}</span>
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      )}

      {isLoading && <JobsSkeleton />}

      {!error && jobs && jobs.length === 0 && (
        <div className="flex flex-col items-center gap-2 border border-dashed border-border py-8 text-center">
          <div className="flex h-8 w-8 items-center justify-center bg-muted">
            <ListChecks className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium">No extractions yet</p>
          <Link href="/jobs/new">
            <Button variant="outline" size="sm">
              Start one
            </Button>
          </Link>
        </div>
      )}

      {filtered && filtered.length === 0 && jobs && jobs.length > 0 && (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <p className="text-sm text-muted-foreground">No jobs match the current filter.</p>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setSearch("");
              setTab("all");
            }}
          >
            Clear filters
          </Button>
        </div>
      )}

      {filtered && filtered.length > 0 && (
        <>
          <div className="border border-border">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-surface text-xs uppercase tracking-wide text-muted-foreground shadow-[inset_0_-1px_0_hsl(var(--border))]">
                <tr>
                  <th className="w-8 px-3 py-1.5">
                    <input
                      type="checkbox"
                      aria-label="Select all cancelable jobs"
                      checked={allInViewSelected}
                      disabled={cancelableInView.length === 0}
                      onChange={toggleSelectAllInView}
                      className="h-3.5 w-3.5 accent-primary disabled:opacity-30"
                    />
                  </th>
                  <th className="px-3 py-1.5 text-left font-medium">Status</th>
                  <th className="px-3 py-1.5 text-left font-medium">Extraction</th>
                  <th className="px-3 py-1.5 text-left font-medium">Region</th>
                  <th className="px-3 py-1.5 text-left font-medium">
                    <button
                      type="button"
                      onClick={() => setTz(tz === "IST" ? "UTC" : "IST")}
                      className="uppercase tracking-wide underline decoration-dotted underline-offset-2 hover:text-foreground"
                      title={`Showing ${tz} — click to switch`}
                    >
                      Range ({tz})
                    </button>
                  </th>
                  <th
                    className="px-3 py-1.5 text-left font-medium"
                    title="Time since the job was submitted, or how long the run took"
                  >
                    Age
                  </th>
                  <th className="px-3 py-1.5 text-right font-medium">Rows</th>
                  <th className="px-3 py-1.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filtered.map((job) => (
                  <JobRow
                    key={job.id}
                    job={job}
                    tz={tz}
                    now={now}
                    selected={selected.has(job.id)}
                    onToggleSelected={toggleSelected}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {jobs && jobs.length >= PAGE_LIMIT && (
            <p className="pt-2 text-center text-xs text-muted-foreground">
              Showing the {PAGE_LIMIT} most recent extractions.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function JobsSkeleton() {
  return (
    <div className="animate-pulse-soft border border-border" aria-hidden>
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-3 border-b border-border px-3 py-2 last:border-b-0"
        >
          <div className="h-4 w-20 bg-muted" />
          <div className="h-3 w-32 bg-muted" />
          <div className="h-3 w-24 bg-muted" />
          <div className="ml-auto h-3 w-16 bg-muted" />
        </div>
      ))}
      <span className="sr-only">Loading jobs…</span>
    </div>
  );
}

// Memoised: the list re-polls every 5s, and React Query's structural sharing
// keeps the object identity of rows whose fields didn't change — so a poll that
// only moves one running job re-renders one row, not all 200.
const JobRow = React.memo(function JobRow({
  job,
  tz,
  now,
  selected,
  onToggleSelected,
}: {
  job: Job;
  tz: Tz;
  now: number;
  selected: boolean;
  onToggleSelected: (id: number) => void;
}) {
  const active = isActive(job);
  const submitted = Date.parse(job.created_at);
  const started = job.started_at ? Date.parse(job.started_at) : null;
  const finished = job.finished_at ? Date.parse(job.finished_at) : null;
  const ran = started && finished ? (finished - started) / 1000 : null;
  return (
    <tr className={`hover:bg-accent/40 ${selected ? "bg-accent/30" : ""}`}>
      <td className="px-3 py-1.5">
        {/* Only an active job can be bulk-canceled, so a finished one gets no
            checkbox at all rather than a disabled one nobody can explain. */}
        {active && (
          <input
            type="checkbox"
            aria-label={`Select job ${job.id}`}
            checked={selected}
            onChange={() => onToggleSelected(job.id)}
            className="h-3.5 w-3.5 accent-primary"
          />
        )}
      </td>
      <td className="px-3 py-1.5">
        <div className="flex items-center gap-1.5">
          {job.status === "running" && (
            <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-pulse" aria-hidden />
          )}
          <Badge tone={JOB_TONE[job.status]}>{job.status}</Badge>
        </div>
      </td>
      <td className="px-3 py-1.5 text-xs" title={job.filter_spec?.label ?? undefined}>
        {extractionName(job) ?? <span className="opacity-40">—</span>}
      </td>
      <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">{job.region_code}</td>
      <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">
        {formatRange(job.start_epoch, job.end_epoch, tz)}
      </td>
      <td
        className="px-3 py-1.5 font-mono text-xs text-muted-foreground"
        title={`Submitted ${formatEpoch(submitted / 1000, tz)} ${tz}${
          ran != null ? ` · ran ${formatDuration(ran)}` : ""
        }`}
      >
        {ran != null
          ? `ran ${formatDuration(ran)}`
          : `${formatDuration((now - submitted) / 1000)} ago`}
      </td>
      <td className={`px-3 py-1.5 text-right font-mono text-xs ${active ? "tabular-nums" : ""}`}>
        {job.rows_written.toLocaleString()}
      </td>
      <td className="px-3 py-1.5">
        <div className="flex items-center justify-end gap-1.5">
          {job.download_url && (
            <a href={`${API_BASE}${job.download_url}`} aria-label={`Download job ${job.id}`}>
              <Button size="icon" variant="ghost">
                <Download className="h-4 w-4" />
              </Button>
            </a>
          )}
          <Button
            size="icon"
            variant="ghost"
            aria-label={`Export job ${job.id} config`}
            title="Export config as JSON"
            onClick={async () =>
              downloadJson(`${job.filter_spec?.label || `job_${job.id}`}.json`, await exportJob(job.id))
            }
          >
            <FileDown className="h-4 w-4" />
          </Button>
          <Link href={`/jobs/${job.id}`}>
            <Button size="icon" variant="ghost" aria-label={`Open job ${job.id}`}>
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        </div>
      </td>
    </tr>
  );
});
