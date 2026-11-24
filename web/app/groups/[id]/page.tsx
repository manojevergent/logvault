"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, Loader2, PencilLine, RefreshCw, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { RerunGroupDialog } from "@/components/rerun-group-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  API_BASE,
  GroupDetail,
  GroupRerunInput,
  GroupStatus,
  Job,
  cancelGroup,
  getGroup,
  listIndexes,
  rerunGroup,
  retryGroup,
} from "@/lib/api";
import { Tz, formatEpoch, useTz } from "@/lib/time";

const GROUP_STATUS: Record<
  GroupStatus,
  { label: string; tone: "neutral" | "success" | "warning" | "danger" | "info" }
> = {
  queued: { label: "Queued", tone: "neutral" },
  running: { label: "Running", tone: "info" },
  completed: { label: "Completed", tone: "success" },
  partial: { label: "Partial", tone: "warning" },
  failed: { label: "Failed", tone: "danger" },
  canceled: { label: "Canceled", tone: "neutral" },
};

const JOB_STATUS: Record<
  string,
  { label: string; tone: "neutral" | "success" | "warning" | "danger" | "info" }
> = {
  queued: { label: "Queued", tone: "neutral" },
  running: { label: "Running", tone: "info" },
  paused: { label: "Paused", tone: "warning" },
  completed: { label: "Completed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  canceled: { label: "Canceled", tone: "neutral" },
};

const num = (value: number) => value.toLocaleString("en-US");
const active = (group: GroupDetail) => group.status === "queued" || group.status === "running";

function fmtWhen(value: string | null | undefined, tz: Tz = "UTC"): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${date.toLocaleString("en-GB", {
    timeZone: tz === "IST" ? "Asia/Kolkata" : "UTC",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })} ${tz}`;
}

function JobRow({ job, source }: { job: Job; source: string }) {
  const meta = JOB_STATUS[job.status] ?? { label: job.status, tone: "neutral" as const };
  const label = job.filter_spec.label || `Job #${job.id}`;
  return (
    <tr className="border-t border-border/60 align-top">
      <td className="px-3 py-2">
        <Link href={`/jobs/${job.id}`} className="font-medium text-primary hover:underline">
          {label}
        </Link>
        <p className="font-mono text-[10px] text-muted-foreground">#{job.id}</p>
      </td>
      <td className="px-3 py-2 font-mono text-[11px] text-muted-foreground">{source}</td>
      <td className="px-3 py-2">
        <Badge tone={meta.tone}>{meta.label}</Badge>
      </td>
      <td className="px-3 py-2 text-right font-mono text-xs">{num(job.rows_written)}</td>
      <td className="max-w-[18rem] px-3 py-2 text-xs text-danger">
        {job.error_message ? (
          <span className="line-clamp-2" title={job.error_message}>
            {job.error_message}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
      <td className="px-3 py-2">
        <div className="flex items-center justify-end gap-2">
          {job.download_url ? (
            <a
              href={`${API_BASE}${job.download_url}`}
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              <Download className="h-3.5 w-3.5" />
              {job.output_format === "jsonl" ? "JSONL" : "CSV"}
            </a>
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          )}
        </div>
      </td>
    </tr>
  );
}

export default function GroupDetailPage() {
  const id = Number(useParams().id);
  const router = useRouter();
  const qc = useQueryClient();
  const [tz, setTz] = useTz();
  const [confirmCancel, setConfirmCancel] = React.useState(false);
  const [rerunOpen, setRerunOpen] = React.useState(false);

  const group = useQuery({
    queryKey: ["group", id],
    queryFn: () => getGroup(id),
    // Poll only while the group is still moving. A finished group's page used to
    // poll forever, and each poll stats every job's output file on the volume
    // that also hosts pgdata.
    refetchInterval: (query) => {
      const data = query.state.data as GroupDetail | undefined;
      return data && active(data) ? 4_000 : false;
    },
    enabled: Number.isFinite(id),
  });
  const indexes = useQuery({ queryKey: ["indexes", ""], queryFn: () => listIndexes() });

  const cancel = useMutation({
    mutationFn: () => cancelGroup(id),
    onSuccess: () => {
      setConfirmCancel(false);
      qc.invalidateQueries({ queryKey: ["group", id] });
      qc.invalidateQueries({ queryKey: ["groups"] });
    },
  });
  const retry = useMutation({
    mutationFn: () => retryGroup(id),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["groups"] });
      router.push(`/groups/${created.id}`);
    },
  });
  const rerun = useMutation({
    mutationFn: (body: GroupRerunInput) => rerunGroup(id, body),
    onSuccess: (created) => {
      setRerunOpen(false);
      qc.invalidateQueries({ queryKey: ["groups"] });
      router.push(`/groups/${created.id}`);
    },
  });

  if (group.isLoading && !group.data) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-5">
        <Card>
          <CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading group…
          </CardContent>
        </Card>
      </div>
    );
  }
  if (group.isError || !group.data) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-5">
        <Card>
          <CardContent className="p-6 text-sm text-danger">
            {(group.error as Error)?.message ?? "Group not found."}
          </CardContent>
        </Card>
      </div>
    );
  }

  const data = group.data;
  const meta = GROUP_STATUS[data.status];
  const done = data.completed + data.failed + data.canceled;
  const pct = data.total_jobs ? Math.round((done / data.total_jobs) * 100) : 0;
  const failures = data.failed + data.canceled;
  const sourceFor = (job: Job) => {
    const index = indexes.data?.find((item) => item.id === job.index_target_id);
    return index ? `${index.name} · ${index.region_code}` : job.region_code;
  };

  const byCustomer = new Map<string, Job[]>();
  for (const job of data.jobs) {
    const customer = job.filter_spec.customer?.trim() || "(unassigned)";
    const bucket = byCustomer.get(customer);
    if (bucket) bucket.push(job);
    else byCustomer.set(customer, [job]);
  }
  const customers = [...byCustomer.entries()].sort((a, b) => a[0].localeCompare(b[0]));

  return (
    <div className="mx-auto max-w-7xl animate-fade-in px-4 py-5">
      <Link
        href="/groups"
        className="mb-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Groups
      </Link>

      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">{data.name}</h1>
            <Badge tone={meta.tone}>{meta.label}</Badge>
            {data.is_preview && <Badge tone="neutral">preview</Badge>}
            {data.parent_group_id != null && (
              <Link
                href={`/groups/${data.parent_group_id}`}
                className="text-xs text-primary hover:underline"
              >
                retry of #{data.parent_group_id}
              </Link>
            )}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {data.total_jobs} search{data.total_jobs === 1 ? "" : "es"} ·{" "}
            <button
              type="button"
              onClick={() => setTz(tz === "IST" ? "UTC" : "IST")}
              className="uppercase tracking-wide underline decoration-dotted underline-offset-2 hover:text-foreground"
              title={`Showing ${tz} — click to switch`}
            >
              {formatEpoch(data.start_epoch, tz)} → {formatEpoch(data.end_epoch, tz)} ({tz})
            </button>
            {data.created_by ? ` · ${data.created_by}` : ""} · {fmtWhen(data.created_at, tz)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={rerun.isPending || data.total_jobs === 0}
            onClick={() => setRerunOpen(true)}
            title="Re-run these searches with an edited window and settings"
          >
            <PencilLine className="h-3.5 w-3.5" />
            Re-run with edit
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={retry.isPending || failures === 0}
            onClick={() => retry.mutate()}
            title="Re-run only failed and canceled searches as a new group"
          >
            {retry.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Retry failed{failures ? ` (${failures})` : ""}
          </Button>
          {active(data) && (
            <Button
              variant="outline"
              size="sm"
              className="border-danger/50 text-danger hover:bg-danger/10 hover:text-danger"
              onClick={() => setConfirmCancel(true)}
            >
              <X className="h-3.5 w-3.5" />
              Cancel group
            </Button>
          )}
          <Link href="/groups/new">
            <Button size="sm">New group</Button>
          </Link>
        </div>
      </div>

      {retry.isError && (
        <p className="mb-3 text-xs text-danger">{(retry.error as Error).message}</p>
      )}

      <Card className="mb-3">
        <CardContent className="space-y-3 p-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
            {[
              ["Searches", num(data.total_jobs)],
              ["Completed", num(data.completed)],
              ["Failed", num(data.failed)],
              ["Running", num(data.running)],
              ["Queued", num(data.queued)],
              ["Rows", num(data.rows_written)],
            ].map(([label, value]) => (
              <div key={label}>
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
                  {label}
                </p>
                <p className="mt-0.5 text-xl font-semibold tabular-nums">{value}</p>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <div className="h-2.5 w-full overflow-hidden bg-muted">
              <div
                className={`h-full transition-all duration-300 ${
                  data.status === "failed"
                    ? "bg-danger"
                    : data.status === "partial"
                      ? "bg-warning"
                      : "bg-success"
                }`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="w-10 shrink-0 text-right font-mono text-xs text-muted-foreground">
              {pct}%
            </span>
          </div>
          {data.is_preview && (
            <p className="text-xs text-muted-foreground">
              Preview group: each job sampled the newest part of the window (up to 100 rows). Run a
              full group for complete extracts.
            </p>
          )}
        </CardContent>
      </Card>

      {customers.map(([customer, jobs]) => (
        <Card key={customer} className="mb-3">
          <CardHeader className="flex flex-row items-center justify-between gap-2 border-b border-border/60 pb-2">
            <CardTitle className="text-sm font-semibold text-foreground">{customer}</CardTitle>
            <span className="text-[11px] text-muted-foreground">
              {jobs.length} search{jobs.length === 1 ? "" : "es"} ·{" "}
              {num(jobs.reduce((sum, job) => sum + (job.rows_written || 0), 0))} rows
            </span>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Search</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Rows</th>
                  <th className="px-3 py-2 font-medium">Error</th>
                  <th className="px-3 py-2 text-right font-medium">Download</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <JobRow key={job.id} job={job} source={sourceFor(job)} />
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ))}

      <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
        Each search runs as its own job against the index saved with it, so one failure never stops
        the others. Retry failed creates a new group with only the failed/canceled searches; Re-run
        with edit repeats any selection of these searches over a new window or with different run
        settings. Either way the original group and its files stay intact. Cancel stops active jobs
        and keeps whatever they already wrote as partial output.
      </p>

      <RerunGroupDialog
        open={rerunOpen}
        group={data}
        tz={tz}
        pending={rerun.isPending}
        error={rerun.isError ? (rerun.error as Error).message : null}
        onSubmit={(body) => rerun.mutate(body)}
        onCancel={() => {
          if (!rerun.isPending) {
            setRerunOpen(false);
            rerun.reset();
          }
        }}
      />

      <ConfirmDialog
        open={confirmCancel}
        title="Cancel this group?"
        description={
          <>
            <p>
              <strong className="text-foreground">{data.name}</strong>
            </p>
            <p>
              {data.running + data.queued} queued or running job
              {data.running + data.queued === 1 ? "" : "s"} will be canceled. Completed files are
              kept, and partial output from stopped jobs remains downloadable.
            </p>
            <p className="text-danger">Completed searches are not affected.</p>
          </>
        }
        confirmLabel="Cancel group"
        pending={cancel.isPending}
        error={cancel.isError ? (cancel.error as Error).message : null}
        onConfirm={() => cancel.mutate()}
        onCancel={() => {
          if (!cancel.isPending) {
            setConfirmCancel(false);
            cancel.reset();
          }
        }}
      />
    </div>
  );
}
