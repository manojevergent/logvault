"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Loader2,
  RefreshCw,
  Settings2,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, fieldClass } from "@/components/ui/input";
import {
  ReportAlert,
  ReportCustomer,
  ReportDay,
  ReportDayStatus,
  ReportSchedule,
  getReport,
  getReportSettings,
  getRole,
  updateReportSettings,
} from "@/lib/api";

const WINDOWS = [7, 14, 30, 60, 90, 180, 365];
const num = (n: number) => n.toLocaleString("en-US");

type Tone = "neutral" | "success" | "warning" | "danger" | "info";

const STATUS: Record<ReportDayStatus, { label: string; tone: Tone; bar: string }> = {
  ok: { label: "Success", tone: "success", bar: "bg-success" },
  failed: { label: "Failed", tone: "danger", bar: "bg-danger" },
  missed: { label: "Missed", tone: "warning", bar: "bg-warning" },
  running: { label: "Running", tone: "info", bar: "bg-primary" },
  partial: { label: "Partial", tone: "warning", bar: "bg-warning/60" },
  canceled: { label: "Canceled", tone: "neutral", bar: "bg-muted-foreground/50" },
  pending: { label: "Pending", tone: "neutral", bar: "bg-muted-foreground/25" },
  off: { label: "Disabled", tone: "neutral", bar: "bg-muted" },
  none: { label: "No run", tone: "neutral", bar: "bg-muted/50" },
};

function pct(current: number, baseline: number): number | null {
  if (baseline === 0) return null;
  return Math.round(((current - baseline) * 1000) / baseline) / 10;
}

function fmtWhen(value: string | null): string {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${date.toLocaleString("en-GB", {
    timeZone: "UTC",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })} UTC`;
}

function fmtDay(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  return date.toLocaleDateString("en-GB", { timeZone: "UTC", day: "2-digit", month: "short" });
}

function cadence(schedule: ReportSchedule): string {
  if (schedule.calendar_day) return "daily · calendar day";
  const seconds = schedule.interval_seconds ?? 0;
  if (seconds <= 0) return "—";
  if (seconds % 86400 === 0) return `every ${seconds / 86400}d`;
  if (seconds % 3600 === 0) return `every ${seconds / 3600}h`;
  return `every ${Math.max(1, Math.round(seconds / 60))}m`;
}

function Delta({ value, suffix }: { value: number | null | undefined; suffix?: string }) {
  if (value === undefined) return null;
  if (value === null) {
    return (
      <span className="text-[11px] text-muted-foreground" title="No count in the comparison period">
        no baseline
      </span>
    );
  }
  const tone = value > 0 ? "text-success" : value < 0 ? "text-danger" : "text-muted-foreground";
  return (
    <span className={`font-mono text-[11px] tabular-nums ${tone}`}>
      {value > 0 ? "+" : ""}
      {value.toFixed(1)}%
      {suffix ? <span className="ml-1 font-sans text-muted-foreground"> {suffix}</span> : null}
    </span>
  );
}

function StatusBadge({ status }: { status: ReportDayStatus }) {
  return <Badge tone={STATUS[status].tone}>{STATUS[status].label}</Badge>;
}

function Kpi({
  label,
  value,
  sub,
  tone = "text-foreground",
}: {
  label: string;
  value: string;
  sub: React.ReactNode;
  tone?: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
        <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{sub}</p>
      </CardContent>
    </Card>
  );
}

function Volume({
  label,
  value,
  delta,
  suffix,
  secondDelta,
  secondSuffix,
  note,
}: {
  label: string;
  value: number;
  delta?: number | null;
  suffix?: string;
  secondDelta?: number | null;
  secondSuffix?: string;
  note?: string;
}) {
  return (
    <div className="border border-border/70 bg-card p-3">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{num(value)}</p>
      <div className="mt-0.5">
        <Delta value={delta} suffix={suffix} />
      </div>
      {secondDelta !== undefined && (
        <div>
          <Delta value={secondDelta} suffix={secondSuffix} />
        </div>
      )}
      {note && <p className="mt-0.5 text-[11px] text-muted-foreground">{note}</p>}
    </div>
  );
}

function MiniStat({
  label,
  value,
  delta,
  suffix,
  secondDelta,
  secondSuffix,
}: {
  label: string;
  value: number;
  delta?: number | null;
  suffix?: string;
  secondDelta?: number | null;
  secondSuffix?: string;
}) {
  return (
    <div className="border border-border/60 bg-muted/30 p-2">
      <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums">{num(value)}</p>
      <Delta value={delta} suffix={suffix} />
      {secondDelta !== undefined && (
        <div>
          <Delta value={secondDelta} suffix={secondSuffix} />
        </div>
      )}
    </div>
  );
}

function DayStrip({ days }: { days: ReportDay[] }) {
  if (days.length === 0) return null;
  return (
    <div className="mt-2">
      <div className="flex items-end gap-0.5 overflow-x-auto pb-1">
        {days.map((day) => (
          <div
            key={day.date}
            title={`${fmtDay(day.date)}: ${STATUS[day.status].label} · ${num(day.rows)} rows · ${day.runs} run${
              day.runs === 1 ? "" : "s"
            }`}
            aria-label={`${fmtDay(day.date)} ${STATUS[day.status].label}, ${day.rows} rows, ${day.runs} runs`}
            className={`h-6 w-3 shrink-0 border border-transparent ${STATUS[day.status].bar}`}
          />
        ))}
      </div>
      <div className="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
        <span>{fmtDay(days[0].date)}</span>
        <span>{fmtDay(days[days.length - 1].date)}</span>
      </div>
    </div>
  );
}

function ScheduleRow({ schedule }: { schedule: ReportSchedule }) {
  return (
    <div className="border border-border/70 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium">{schedule.name}</p>
            {!schedule.enabled && <Badge tone="neutral">disabled</Badge>}
            {schedule.schedule_id == null && <Badge tone="warning">removed schedule</Badge>}
            <StatusBadge status={schedule.today_status} />
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {schedule.source ?? "no source"} · {cadence(schedule)} · last run{" "}
            {fmtWhen(schedule.last_run_at)}
          </p>
        </div>
        {schedule.latest_job_id != null && (
          <Link
            href={`/jobs/${schedule.latest_job_id}`}
            className="shrink-0 text-xs text-primary hover:underline"
          >
            Latest job #{schedule.latest_job_id}
          </Link>
        )}
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2">
        <MiniStat
          label="Today"
          value={schedule.today_rows}
          delta={schedule.pct_vs_yesterday}
          suffix="vs yesterday"
          secondDelta={schedule.pct_vs_last_week}
          secondSuffix="vs last week"
        />
        <MiniStat
          label="Yesterday"
          value={schedule.yesterday_rows}
          delta={schedule.pct_yesterday_vs_last_week}
          suffix="vs last week"
        />
        <MiniStat label="Same day last week" value={schedule.last_week_rows} />
      </div>

      <DayStrip days={schedule.days} />
    </div>
  );
}

function CustomerCard({ customer }: { customer: ReportCustomer }) {
  return (
    <Card className="mb-3">
      <CardHeader className="flex flex-wrap items-start justify-between gap-2 border-b border-border/60 pb-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-base font-semibold text-foreground">
              {customer.customer}
            </CardTitle>
            {customer.failed_today > 0 && (
              <Badge tone="danger">{customer.failed_today} failed today</Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {customer.schedules.length} scheduled job
            {customer.schedules.length === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span>
            Today <strong className="text-foreground">{num(customer.rows_today)}</strong>{" "}
            <Delta value={customer.pct_vs_yesterday} suffix="vs yesterday" /> ·{" "}
            <Delta value={customer.pct_vs_last_week} suffix="vs last week" />
          </span>
          <span>
            Yesterday <strong className="text-foreground">{num(customer.rows_yesterday)}</strong>{" "}
            <Delta
              value={pct(customer.rows_yesterday, customer.rows_last_week)}
              suffix="vs last week"
            />
          </span>
          <span>
            Last week <strong className="text-foreground">{num(customer.rows_last_week)}</strong>
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 p-3">
        {customer.schedules.map((schedule, index) => (
          <ScheduleRow
            key={`${schedule.schedule_id ?? "removed"}-${schedule.name}-${index}`}
            schedule={schedule}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function AlertRow({ alert }: { alert: ReportAlert }) {
  const failed = alert.kind === "failed";
  return (
    <li className="flex flex-wrap items-start gap-3 border border-border/70 p-2.5">
      <Badge tone={failed ? "danger" : "warning"}>{failed ? "Failed" : "Missed"}</Badge>
      <div className="min-w-0 flex-1">
        <p className="text-sm">
          <strong>{alert.customer}</strong> · {alert.job_name}
          {alert.occurrences > 1 && (
            <span className="ml-2 text-xs text-muted-foreground">{alert.occurrences} failures</span>
          )}
        </p>
        <p className="text-[11px] text-muted-foreground">
          {fmtWhen(alert.at)}
          {alert.recipients.length > 0 ? ` · alert to ${alert.recipients.join(", ")}` : ""}
        </p>
        {alert.error && (
          <p
            className={`mt-1 line-clamp-2 font-mono text-[11px] ${
              failed ? "text-danger" : "text-warning"
            }`}
            title={alert.error}
          >
            {alert.error}
          </p>
        )}
      </div>
      <div className="shrink-0">
        {alert.job_id != null ? (
          <Link href={`/jobs/${alert.job_id}`}>
            <Button size="sm" variant="outline">
              Job #{alert.job_id}
            </Button>
          </Link>
        ) : alert.schedule_id != null ? (
          <Link href="/schedules">
            <Button size="sm" variant="outline">
              Schedule
            </Button>
          </Link>
        ) : null}
      </div>
    </li>
  );
}

export default function ReportsPage() {
  const qc = useQueryClient();
  const [windowDays, setWindowDays] = React.useState(30);
  const [retentionInput, setRetentionInput] = React.useState("90");
  const [isAdmin, setIsAdmin] = React.useState(false);

  React.useEffect(() => setIsAdmin(getRole() === "admin"), []);

  const settingsQ = useQuery({ queryKey: ["report-settings"], queryFn: getReportSettings });
  const reportQ = useQuery({
    queryKey: ["report", windowDays],
    queryFn: () => getReport(windowDays),
    refetchInterval: 60_000,
  });
  const retention = settingsQ.data?.retention_days ?? 90;

  React.useEffect(() => {
    if (settingsQ.data) setRetentionInput(String(settingsQ.data.retention_days));
  }, [settingsQ.data]);

  React.useEffect(() => {
    if (windowDays > retention) setWindowDays(retention);
  }, [retention, windowDays]);

  const saveRetention = useMutation({
    mutationFn: updateReportSettings,
    onSuccess: (saved) => {
      setRetentionInput(String(saved.retention_days));
      qc.invalidateQueries({ queryKey: ["report-settings"] });
      qc.invalidateQueries({ queryKey: ["report"] });
      if (windowDays > saved.retention_days) setWindowDays(saved.retention_days);
    },
  });

  const windowOptions = React.useMemo(() => {
    const values = new Set(WINDOWS.filter((days) => days <= retention));
    values.add(retention);
    return [...values].sort((a, b) => a - b);
  }, [retention]);

  const retentionValue = Number(retentionInput);
  const retentionValid =
    Number.isInteger(retentionValue) && retentionValue >= 1 && retentionValue <= 365;
  const data = reportQ.data;

  return (
    <div className="mx-auto max-w-7xl animate-fade-in px-4 py-5">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Extract</p>
          <h1 className="text-xl font-semibold tracking-tight">Extraction reports</h1>
          <p className="text-xs text-muted-foreground">
            Scheduled runs by customer, compared with yesterday and the same day last week. Counts
            are rows written by completed runs, in UTC.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="w-36">
            <select
              aria-label="Report window"
              className={fieldClass}
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
            >
              {windowOptions.map((days) => (
                <option key={days} value={days}>
                  Last {days} days
                </option>
              ))}
            </select>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => reportQ.refetch()}
            disabled={reportQ.isFetching}
          >
            {reportQ.isFetching ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Refresh
          </Button>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border border-border/70 bg-card px-3 py-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Settings2 className="h-4 w-4" />
          <span>Report retention</span>
          {isAdmin ? (
            <>
              <div className="w-20">
                <Input
                  type="number"
                  min={1}
                  max={365}
                  value={retentionInput}
                  onChange={(e) => setRetentionInput(e.target.value)}
                  aria-label="Retention days"
                />
              </div>
              <span>days</span>
              <Button
                size="sm"
                variant="outline"
                disabled={
                  !retentionValid || saveRetention.isPending || retentionValue === retention
                }
                onClick={() => saveRetention.mutate(retentionValue)}
              >
                {saveRetention.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Save
              </Button>
              {saveRetention.isSuccess && !saveRetention.isPending && (
                <span className="text-success">Saved.</span>
              )}
              {saveRetention.isError && (
                <span className="text-danger">{(saveRetention.error as Error).message}</span>
              )}
            </>
          ) : (
            <span>{retention} days</span>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground">
          Limits the report window only. Raw job history and files are kept.
        </p>
      </div>

      {reportQ.isLoading && !data ? (
        <Card>
          <CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Building the report…
          </CardContent>
        </Card>
      ) : reportQ.isError ? (
        <Card>
          <CardContent className="p-6 text-sm text-danger">
            {(reportQ.error as Error).message}
          </CardContent>
        </Card>
      ) : data ? (
        <>
          <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi
              label="Rows today"
              value={num(data.totals.rows_today)}
              sub={
                <span className="flex flex-wrap items-center gap-2">
                  <Delta value={data.totals.pct_vs_yesterday} suffix="vs yesterday" />
                  <span>· {num(data.totals.rows_yesterday)} yesterday</span>
                </span>
              }
            />
            <Kpi
              label="Scheduled runs today"
              value={num(data.totals.runs_today)}
              sub={`${data.totals.completed_today} completed · ${data.totals.failed_today} failed · ${data.totals.active_today} active`}
            />
            <Kpi
              label="Success rate today"
              value={
                data.totals.success_rate_today == null
                  ? "—"
                  : `${data.totals.success_rate_today.toFixed(1)}%`
              }
              sub={
                data.totals.failed_today > 0
                  ? `${data.totals.failed_today} failed run${
                      data.totals.failed_today === 1 ? "" : "s"
                    }`
                  : "No failed runs"
              }
              tone={data.totals.failed_today > 0 ? "text-danger" : "text-foreground"}
            />
            <Kpi
              label="Customers"
              value={num(data.totals.customers)}
              sub={`${data.totals.schedules} scheduled jobs · ${data.totals.enabled_schedules} enabled`}
            />
          </div>

          <Card className="mb-4">
            <CardHeader className="border-b border-border/60 pb-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-foreground">Extraction volume</CardTitle>
                <span className="text-[11px] text-muted-foreground">
                  Last {data.window_days} days · today is partial
                </span>
              </div>
            </CardHeader>
            <CardContent className="grid gap-3 p-3 sm:grid-cols-3">
              <Volume
                label="Today"
                value={data.totals.rows_today}
                delta={data.totals.pct_vs_yesterday}
                suffix="vs yesterday"
                secondDelta={data.totals.pct_vs_last_week}
                secondSuffix="vs last week"
              />
              <Volume
                label="Yesterday"
                value={data.totals.rows_yesterday}
                delta={pct(data.totals.rows_yesterday, data.totals.rows_last_week)}
                suffix="vs last week"
              />
              <Volume
                label="Same day last week"
                value={data.totals.rows_last_week}
                note="comparison baseline"
              />
            </CardContent>
          </Card>

          <Card className="mb-4">
            <CardHeader className="flex flex-row items-center justify-between gap-2 border-b border-border/60 pb-3">
              <div className="flex items-center gap-2">
                <AlertTriangle
                  className={`h-4 w-4 ${data.alerts.length ? "text-danger" : "text-muted-foreground"}`}
                />
                <CardTitle className="text-foreground">Alerts</CardTitle>
                {data.alerts.length > 0 && (
                  <span className="flex flex-wrap items-center gap-1.5">
                    {data.alerts.some((alert) => alert.kind === "failed") && (
                      <Badge tone="danger">
                        {data.alerts.filter((alert) => alert.kind === "failed").length} failed
                      </Badge>
                    )}
                    {data.alerts.some((alert) => alert.kind === "missed") && (
                      <Badge tone="warning">
                        {data.alerts.filter((alert) => alert.kind === "missed").length} missed
                      </Badge>
                    )}
                  </span>
                )}
              </div>
              <span className="text-[11px] text-muted-foreground">
                Last {data.window_days} days
              </span>
            </CardHeader>
            <CardContent className="p-3">
              {data.alerts.length === 0 ? (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <CheckCircle2 className="h-4 w-4 text-success" />
                  No failed or missed scheduled runs in this window.
                </p>
              ) : (
                <ul className="max-h-96 space-y-2 overflow-y-auto pr-1">
                  {data.alerts.map((alert, index) => (
                    <AlertRow
                      key={`${alert.kind}-${alert.customer}-${alert.job_name}-${index}`}
                      alert={alert}
                    />
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Customers</h2>
            <span className="text-[11px] text-muted-foreground">
              Generated {fmtWhen(data.generated_at)}
            </span>
          </div>

          {data.customers.length === 0 ? (
            <Card>
              <CardContent className="p-6 text-center text-sm text-muted-foreground">
                <BarChart3 className="mx-auto mb-2 h-5 w-5" />
                No scheduled runs in this window.{" "}
                <Link href="/schedules" className="text-primary hover:underline">
                  Create a schedule
                </Link>{" "}
                to start collecting daily reports.
              </CardContent>
            </Card>
          ) : (
            data.customers.map((customer) => (
              <CustomerCard key={customer.customer} customer={customer} />
            ))
          )}

          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
            {(
              [
                "ok",
                "failed",
                "missed",
                "running",
                "partial",
                "canceled",
                "pending",
                "off",
              ] as ReportDayStatus[]
            ).map((status) => (
              <span key={status} className="flex items-center gap-1">
                <span className={`h-2.5 w-2.5 ${STATUS[status].bar}`} />
                {STATUS[status].label}
              </span>
            ))}
          </div>
          <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
            Counts are rows written by completed scheduled runs; failed and canceled runs show their
            status but contribute no rows. “Today” is partial. Days and comparisons use UTC, and
            “last week” is the same weekday seven days ago. Manual jobs and previews are excluded. A
            missed day means an enabled schedule expected to run at least daily produced no job, and
            a missed alert means nothing ran for 36 hours.
          </p>
        </>
      ) : null}
    </div>
  );
}
