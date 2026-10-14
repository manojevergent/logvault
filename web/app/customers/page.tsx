"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Download, RefreshCw, ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { API_BASE, JOB_TONE, Job, retryJob } from "@/lib/api";
import { useJobs } from "@/lib/use-jobs";
import { Tz, formatRange, useTz } from "@/lib/time";

// ── grouping ──────────────────────────────────────────────────────────────────

type DayMap = Record<string, Job[]>;        // "2026-09-04" → jobs
type MonthMap = Record<string, DayMap>;     // "2026-09"    → DayMap
type CustomerMap = Record<string, MonthMap>; // customer    → MonthMap

function groupJobs(jobs: Job[]): CustomerMap {
  const out: CustomerMap = {};
  for (const job of jobs) {
    const customer =
      job.filter_spec?.customer?.trim() ||
      job.filter_spec?.label?.trim() ||
      "(unassigned)";
    const d = new Date(job.created_at);
    const month = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
    const day = `${month}-${String(d.getUTCDate()).padStart(2, "0")}`;
    ((out[customer] ??= {})[month] ??= {})[day] ??= [];
    out[customer][month][day].push(job);
  }
  return out;
}

function fmtMonth(ym: string): string {
  const [y, m] = ym.split("-");
  return new Date(Number(y), Number(m) - 1).toLocaleString("en", { month: "long", year: "numeric" });
}

function fmtDay(ymd: string): string {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleString("en", { weekday: "short", month: "short", day: "numeric" });
}

function jobCount(map: MonthMap): number {
  return Object.values(map).flatMap(Object.values).reduce((n, a) => n + a.length, 0);
}

function dayJobCount(days: DayMap): number {
  return Object.values(days).reduce((n, a) => n + a.length, 0);
}

// ── component ─────────────────────────────────────────────────────────────────

export default function CustomersPage() {
  const [tz, setTz] = useTz();
  const { data: jobs, isLoading, error, refetch } = useJobs();

  const grouped = React.useMemo(
    () => (jobs ? groupJobs(jobs.filter((j) => !j.is_preview)) : {}),
    [jobs]
  );

  const customers = React.useMemo(
    () => Object.keys(grouped).sort((a, b) => a.localeCompare(b)),
    [grouped]
  );

  // open sets — default first customer + its first month open
  const [openCustomers, setOpenCustomers] = React.useState<Set<string>>(new Set());
  const [openMonths, setOpenMonths] = React.useState<Set<string>>(new Set());
  const [openDays, setOpenDays] = React.useState<Set<string>>(new Set());

  React.useEffect(() => {
    if (customers.length === 0) return;
    const first = customers[0];
    setOpenCustomers(new Set([first]));
    const months = Object.keys(grouped[first]).sort().reverse();
    const firstMonth = months[0];
    setOpenMonths(new Set([`${first}::${firstMonth}`]));
    const days = Object.keys(grouped[first][firstMonth]).sort().reverse();
    setOpenDays(new Set([`${first}::${firstMonth}::${days[0]}`]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customers.join(",")]);

  function toggle<T>(set: Set<T>, key: T): Set<T> {
    const next = new Set(set);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  }

  if (isLoading)
    return (
      <div className="mx-auto max-w-4xl animate-pulse-soft px-6 py-4" aria-busy>
        <div className="mb-3 h-4 w-32 bg-muted" />
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-11 border border-border bg-muted/40" />
          ))}
        </div>
        <span className="sr-only">Loading customers…</span>
      </div>
    );

  // Without this, a failed fetch fell through to "no jobs with a customer set
  // yet" — an empty state, for what is actually a broken request.
  if (error)
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <h1 className="pb-2 text-base font-semibold tracking-tight">Customers</h1>
        <p className="pb-3 text-sm text-danger">{(error as Error).message}</p>
        <Button size="sm" variant="outline" onClick={() => refetch()}>
          Retry
        </Button>
      </div>
    );

  if (customers.length === 0)
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <h1 className="pb-4 text-base font-semibold tracking-tight">Customers</h1>
        <p className="text-sm text-muted-foreground">
          No jobs with a customer set yet. Add a customer name when creating an extraction.
        </p>
      </div>
    );

  return (
    <div className="mx-auto max-w-4xl animate-fade-in px-6 py-4">
      <div className="flex items-end justify-between pb-3">
        <div className="space-y-0.5">
          <h1 className="text-base font-semibold tracking-tight">Customers</h1>
          <p className="text-xs text-muted-foreground">Jobs grouped by customer, month, and day.</p>
        </div>
        <button
          type="button"
          onClick={() => setTz(tz === "IST" ? "UTC" : "IST")}
          className="text-xs text-muted-foreground underline decoration-dotted underline-offset-2 hover:text-foreground"
        >
          {tz}
        </button>
      </div>

      <div className="space-y-2">
        {customers.map((customer) => {
          const months = grouped[customer];
          const isOpen = openCustomers.has(customer);
          const total = jobCount(months);
          return (
            <div key={customer} className="border border-border">
              {/* Customer row */}
              <button
                type="button"
                onClick={() => setOpenCustomers(toggle(openCustomers, customer))}
                className="flex w-full items-center justify-between px-4 py-2.5 text-left hover:bg-accent/40"
              >
                <div className="flex items-center gap-2">
                  {isOpen ? (
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                  )}
                  <span className="text-sm font-semibold">{customer}</span>
                </div>
                <span className="font-mono text-xs text-muted-foreground">
                  {total} job{total === 1 ? "" : "s"}
                </span>
              </button>

              {isOpen && (
                <div className="border-t border-border">
                  {Object.keys(months)
                    .sort()
                    .reverse()
                    .map((month) => {
                      const monthKey = `${customer}::${month}`;
                      const isMonthOpen = openMonths.has(monthKey);
                      const days = months[month];
                      const monthTotal = dayJobCount(days);
                      return (
                        <div key={month} className="border-b border-border last:border-b-0">
                          {/* Month row */}
                          <button
                            type="button"
                            onClick={() => setOpenMonths(toggle(openMonths, monthKey))}
                            className="flex w-full items-center justify-between bg-surface/50 px-8 py-2 text-left hover:bg-accent/30"
                          >
                            <div className="flex items-center gap-2">
                              {isMonthOpen ? (
                                <ChevronDown className="h-3 w-3 text-muted-foreground" />
                              ) : (
                                <ChevronRight className="h-3 w-3 text-muted-foreground" />
                              )}
                              <span className="text-xs font-medium">{fmtMonth(month)}</span>
                            </div>
                            <span className="font-mono text-xs text-muted-foreground">
                              {monthTotal}
                            </span>
                          </button>

                          {isMonthOpen && (
                            <div>
                              {Object.keys(days)
                                .sort()
                                .reverse()
                                .map((day) => {
                                  const dayKey = `${customer}::${month}::${day}`;
                                  const isDayOpen = openDays.has(dayKey);
                                  const dayJobs = days[day];
                                  return (
                                    <div key={day} className="border-t border-border/50">
                                      {/* Day row */}
                                      <button
                                        type="button"
                                        onClick={() => setOpenDays(toggle(openDays, dayKey))}
                                        className="flex w-full items-center justify-between px-12 py-1.5 text-left hover:bg-accent/20"
                                      >
                                        <div className="flex items-center gap-2">
                                          {isDayOpen ? (
                                            <ChevronDown className="h-3 w-3 text-muted-foreground" />
                                          ) : (
                                            <ChevronRight className="h-3 w-3 text-muted-foreground" />
                                          )}
                                          <span className="text-xs text-muted-foreground">
                                            {fmtDay(day)}
                                          </span>
                                        </div>
                                        <span className="font-mono text-xs text-muted-foreground">
                                          {dayJobs.length}
                                        </span>
                                      </button>

                                      {isDayOpen && (
                                        <div className="divide-y divide-border/40">
                                          {dayJobs.map((job) => (
                                            <JobDetailRow key={job.id} job={job} tz={tz} />
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  );
                                })}
                            </div>
                          )}
                        </div>
                      );
                    })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── job detail row ─────────────────────────────────────────────────────────────

function JobDetailRow({ job, tz }: { job: Job; tz: Tz }) {
  const router = useRouter();
  const qc = useQueryClient();
  const retry = useMutation({
    mutationFn: () => retryJob(job.id),
    onSuccess: (newJob) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      router.push(`/jobs/${newJob.id}`);
    },
  });

  const canRetry = job.status === "failed" || job.status === "canceled";

  return (
    <div className="flex items-center gap-3 px-16 py-2 hover:bg-accent/10">
      <div className="w-20 shrink-0">
        <Badge tone={JOB_TONE[job.status]}>{job.status}</Badge>
      </div>
      <span className="flex-1 font-mono text-xs text-muted-foreground">
        {formatRange(job.start_epoch, job.end_epoch, tz)}
      </span>
      <span className="w-20 text-right font-mono text-xs text-muted-foreground">
        {job.rows_written > 0 ? job.rows_written.toLocaleString() : "—"}
      </span>
      <div className="flex items-center gap-1">
        {job.download_url && (
          <a href={`${API_BASE}${job.download_url}`} aria-label="Download">
            <Button size="icon" variant="ghost" className="h-7 w-7">
              <Download className="h-3.5 w-3.5" />
            </Button>
          </a>
        )}
        {canRetry && (
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            aria-label="Retry job"
            disabled={retry.isPending}
            onClick={() => retry.mutate()}
            title="Retry this job"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${retry.isPending ? "animate-spin" : ""}`} />
          </Button>
        )}
        <Link href={`/jobs/${job.id}`}>
          <Button size="icon" variant="ghost" className="h-7 w-7" aria-label="Open job">
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </Link>
      </div>
    </div>
  );
}
