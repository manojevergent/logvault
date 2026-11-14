"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Layers, Loader2, Plus } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { GroupStatus, listGroups } from "@/lib/api";
import { formatEpoch } from "@/lib/time";

const STATUS: Record<
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

const num = (n: number) => n.toLocaleString("en-US");

export default function GroupsPage() {
  const groups = useQuery({
    queryKey: ["groups"],
    queryFn: () => listGroups(100),
    refetchInterval: 5_000,
  });

  return (
    <div className="mx-auto max-w-6xl animate-fade-in px-4 py-5">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Extract</p>
          <h1 className="text-xl font-semibold tracking-tight">Group extractions</h1>
          <p className="text-xs text-muted-foreground">
            One shared time window, one job per saved search. Each search keeps its own index,
            filter and file; the group tracks them together.
          </p>
        </div>
        <Link href="/groups/new">
          <Button>
            <Plus className="h-4 w-4" />
            New group
          </Button>
        </Link>
      </div>

      {groups.isLoading && !groups.data ? (
        <Card>
          <CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading groups…
          </CardContent>
        </Card>
      ) : groups.isError ? (
        <Card>
          <CardContent className="p-6 text-sm text-danger">
            {(groups.error as Error).message}
          </CardContent>
        </Card>
      ) : !groups.data?.length ? (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            <Layers className="mx-auto mb-2 h-6 w-6" />
            No groups yet. Select several saved searches and run them over one window.
            <div className="mt-3">
              <Link href="/groups/new">
                <Button size="sm">Create the first group</Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {groups.data.map((group) => {
            const done = group.completed + group.failed + group.canceled;
            const pct = group.total_jobs ? Math.round((done / group.total_jobs) * 100) : 0;
            const meta = STATUS[group.status];
            return (
              <Link key={group.id} href={`/groups/${group.id}`} className="block">
                <Card className="transition-shadow hover:shadow-card-hover">
                  <CardContent className="p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{group.name}</span>
                          <Badge tone={meta.tone}>{meta.label}</Badge>
                          {group.is_preview && <Badge tone="neutral">preview</Badge>}
                          {group.parent_group_id != null && <Badge tone="neutral">retry</Badge>}
                        </div>
                        <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                          {group.total_jobs} search{group.total_jobs === 1 ? "" : "es"} ·{" "}
                          {formatEpoch(group.start_epoch)} → {formatEpoch(group.end_epoch)} UTC
                          {group.created_by ? ` · ${group.created_by}` : ""}
                        </p>
                      </div>
                      <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
                    </div>

                    <div className="mt-3 flex items-center gap-2">
                      <div className="h-2 w-full overflow-hidden bg-muted">
                        <div
                          className={`h-full transition-all duration-300 ${
                            group.status === "failed"
                              ? "bg-danger"
                              : group.status === "partial"
                                ? "bg-warning"
                                : "bg-success"
                          }`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="w-9 shrink-0 text-right font-mono text-[11px] text-muted-foreground">
                        {pct}%
                      </span>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span>
                        <strong className="text-success">{group.completed}</strong> completed
                      </span>
                      <span>
                        <strong className={group.failed ? "text-danger" : "text-foreground"}>
                          {group.failed}
                        </strong>{" "}
                        failed
                      </span>
                      <span>
                        <strong className="text-foreground">{group.running}</strong> running ·{" "}
                        {group.queued} queued
                      </span>
                      {group.canceled > 0 && <span>{group.canceled} canceled</span>}
                      <span className="ml-auto font-mono">{num(group.rows_written)} rows</span>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
