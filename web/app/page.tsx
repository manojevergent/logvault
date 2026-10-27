"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Database, Inbox, KeyRound, ListChecks, Rows3 } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { IconBadge } from "@/components/ui/icon-badge";
import { Job, JOB_TONE, JobStatus, getJobStats, listCredentials, listIndexes } from "@/lib/api";
import { isActive, useJobs } from "@/lib/use-jobs";
import { formatRange } from "@/lib/time";

const STATUS_COLOR: Record<JobStatus, string> = {
  completed: "#34A853",
  running: "#4285F4",
  queued: "#9AA0A6",
  paused: "#FBBC04",
  failed: "#EA4335",
  canceled: "#BDC1C6",
};

export default function DashboardPage() {
  const { data: jobs = [] } = useJobs();
  const { data: creds = [] } = useQuery({ queryKey: ["credentials"], queryFn: listCredentials });
  const { data: indexes = [] } = useQuery({
    queryKey: ["indexes", ""],
    queryFn: () => listIndexes(),
  });
  // Whole-table aggregates. The list above is capped at 200 rows, so summing it
  // under-reported both the row count and the number of active jobs.
  const { data: stats } = useQuery({
    queryKey: ["jobs", "stats"],
    queryFn: getJobStats,
    staleTime: 5_000,
  });

  const active = jobs.filter(isActive);
  const activeCount = stats
    ? (stats.by_status.queued ?? 0) + (stats.by_status.running ?? 0) + (stats.by_status.paused ?? 0)
    : undefined;
  const totalRows = stats?.rows_written;

  const statusCounts: Record<string, number> = stats?.by_status ?? {};
  const segments = (Object.keys(statusCounts) as JobStatus[]).map((s) => ({
    label: s,
    value: statusCounts[s],
    color: STATUS_COLOR[s],
  }));

  return (
    <div className="mx-auto max-w-6xl animate-fade-in px-6 py-5">
      <div className="flex flex-col gap-2 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Dashboard</h1>
          <p className="text-xs text-muted-foreground">
            Extract logs from Last9 into downloadable CSVs — streamed, checkpointed, resumable.
          </p>
        </div>
        <Link href="/jobs/new">
          <Button size="sm">
            New extraction
            <ArrowRight className="h-4 w-4" />
          </Button>
        </Link>
      </div>

      {/* Stat cards with 3D colored icon badges */}
      <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        <StatCard
          icon={ListChecks}
          color="blue"
          label="Active jobs"
          value={activeCount ?? "—"}
        />
        <StatCard
          icon={Rows3}
          color="green"
          label="Rows extracted"
          value={totalRows == null ? "—" : totalRows.toLocaleString()}
        />
        <StatCard icon={Database} color="yellow" label="Saved indexes" value={indexes.length} />
        <StatCard icon={KeyRound} color="red" label="Credentials" value={creds.length} />
      </div>

      {active.length > 0 && (
        <Card className="mt-2.5">
          <CardHeader className="p-4 pb-1.5">
            <CardTitle className="text-foreground">Running now</CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <div className="space-y-2">
              {active.map((j) => {
                const pct = j.total_chunks
                  ? Math.round((j.completed_chunks / j.total_chunks) * 100)
                  : 0;
                return (
                  <Link key={j.id} href={`/jobs/${j.id}`} className="block group">
                    <div className="flex items-center justify-between gap-4 py-1">
                      <div className="flex min-w-0 items-center gap-2">
                        {j.status === "running" && (
                          <span
                            className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-blue-400"
                            aria-hidden
                          />
                        )}
                        <Badge tone={JOB_TONE[j.status]}>{j.status}</Badge>
                        <span className="truncate font-mono text-xs text-muted-foreground">
                          #{j.id} · {j.region_code}
                          {j.credential_label ? ` · ${j.credential_label}` : ""}
                        </span>
                      </div>
                      <div className="flex shrink-0 items-center gap-3">
                        <span className="font-mono text-xs tabular-nums text-muted-foreground">
                          {j.rows_written.toLocaleString()} rows
                        </span>
                        <span className="font-mono text-xs text-muted-foreground">
                          {j.completed_chunks}/{j.total_chunks || "?"} chunks
                        </span>
                        <span className="w-9 text-right font-mono text-xs tabular-nums text-muted-foreground">
                          {pct}%
                        </span>
                        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                      </div>
                    </div>
                    <div
                      role="progressbar"
                      aria-label={`Job ${j.id} chunks completed`}
                      aria-valuenow={pct}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      className="h-1 w-full overflow-hidden bg-muted"
                    >
                      <div
                        className="h-full bg-primary transition-all duration-500"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </Link>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-2.5 pt-2.5 lg:grid-cols-3">
        {/* Status donut */}
        <Card>
          <CardHeader className="p-4 pb-1.5">
            <CardTitle className="text-foreground">Jobs by status</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center gap-4 p-4 pt-0">
            <Donut segments={segments} />
            <ul className="space-y-1 text-xs">
              {segments.length === 0 && <li className="text-muted-foreground">No jobs yet</li>}
              {segments.map((s) => (
                <li key={s.label} className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: s.color }} />
                  <span className="capitalize text-muted-foreground">{s.label}</span>
                  <span className="font-mono font-medium">{s.value}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        {/* Recent activity bars */}
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between space-y-0 p-4 pb-1.5">
            <CardTitle className="text-foreground">Recent extractions</CardTitle>
            <Link href="/jobs" className="text-xs font-medium text-primary hover:underline">
              View all
            </Link>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            {jobs.length === 0 ? <EmptyState /> : <Bars jobs={jobs.slice(0, 8)} />}
          </CardContent>
        </Card>
      </div>

      {/* Recent scheduled runs — the jobs nobody is watching, so a failing
          schedule is otherwise invisible until someone goes looking. */}
      <ScheduledRuns jobs={jobs} />
    </div>
  );
}

function StatCard({
  icon,
  color,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  color: "blue" | "green" | "yellow" | "red";
  label: string;
  value: number | string;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-3.5">
        <IconBadge icon={icon} color={color} size="sm" />
        <div>
          <div className="font-mono text-lg font-semibold leading-tight tracking-tight">
            {value}
          </div>
          <p className="text-[11px] text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function Donut({ segments }: { segments: { value: number; color: string }[] }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  const r = 42;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg viewBox="0 0 100 100" className="h-20 w-20 -rotate-90">
      <circle cx="50" cy="50" r={r} fill="none" stroke="hsl(var(--muted))" strokeWidth="14" />
      {total > 0 &&
        segments.map((s, i) => {
          const len = (s.value / total) * c;
          const el = (
            <circle
              key={i}
              cx="50"
              cy="50"
              r={r}
              fill="none"
              stroke={s.color}
              strokeWidth="14"
              strokeDasharray={`${len} ${c - len}`}
              strokeDashoffset={-offset}
            />
          );
          offset += len;
          return el;
        })}
    </svg>
  );
}

function Bars({ jobs }: { jobs: Job[] }) {
  const max = Math.max(...jobs.map((j) => j.rows_written), 1);
  return (
    // items-end here left each bar's <a> at label height (21px), so the
    // flex-1 track inside it resolved to 0 and the bars' percentage heights
    // had nothing to resolve against. The inner items-end still bottom-anchors
    // each bar.
    <div className="flex h-24 items-stretch gap-3">
      {jobs.map((j) => (
        <Link
          key={j.id}
          href={`/jobs/${j.id}`}
          className="group flex flex-1 flex-col items-center gap-1.5"
          title={`Job #${j.id} · ${j.rows_written.toLocaleString()} rows`}
        >
          <div className="flex w-full flex-1 items-end">
            <div
              className="w-full bg-gblue/80 transition-all group-hover:bg-gblue"
              style={{ height: `${Math.max((j.rows_written / max) * 100, 4)}%` }}
            />
          </div>
          <span className="font-mono text-[10px] text-muted-foreground">#{j.id}</span>
        </Link>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center gap-2 border border-dashed border-border py-8 text-center">
      <IconBadge icon={Inbox} color="blue" size="sm" />
      <p className="text-sm font-medium">No extractions yet</p>
      <Link href="/jobs/new">
        <Button variant="outline" size="sm">
          Start an extraction
        </Button>
      </Link>
    </div>
  );
}

// Scheduled runs are created by the beat, not by a person, so nothing surfaces
// them until someone opens the jobs list. `created_by` is "schedule:<id>" for
// exactly these.
function ScheduledRuns({ jobs }: { jobs: Job[] }) {
  const runs = jobs
    .filter((j) => (j.created_by ?? "").startsWith("schedule:"))
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
    .slice(0, 10);

  return (
    <Card className="mt-2.5">
      <CardHeader className="flex-row items-center justify-between space-y-0 p-4 pb-1.5">
        <CardTitle className="text-foreground">Recent scheduled runs</CardTitle>
        <Link href="/schedules">
          <Button size="sm" variant="ghost" className="gap-1 text-xs">
            Schedules <ArrowRight className="h-3 w-3" />
          </Button>
        </Link>
      </CardHeader>
      <CardContent className="p-4 pt-0">
        {runs.length === 0 ? (
          <p className="py-6 text-center text-xs text-muted-foreground">
            No scheduled runs yet — they appear here once a schedule fires.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-1.5 pr-3 font-medium">Status</th>
                  <th className="py-1.5 pr-3 font-medium">Schedule</th>
                  <th className="py-1.5 pr-3 font-medium">Window (UTC)</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Rows</th>
                  <th className="py-1.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {runs.map((j) => (
                  <tr key={j.id} className="hover:bg-accent/40">
                    <td className="py-1.5 pr-3">
                      <Badge tone={JOB_TONE[j.status]}>{j.status}</Badge>
                    </td>
                    <td className="max-w-[220px] truncate py-1.5 pr-3">
                      {j.filter_spec?.label ?? <span className="opacity-40">—</span>}
                    </td>
                    <td className="py-1.5 pr-3 font-mono text-muted-foreground">
                      {formatRange(j.start_epoch, j.end_epoch, "UTC")}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono">
                      {j.rows_written.toLocaleString()}
                    </td>
                    <td className="py-1.5 text-right">
                      <Link href={`/jobs/${j.id}`} aria-label={`Open job ${j.id}`}>
                        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                      </Link>
                    </td>
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
