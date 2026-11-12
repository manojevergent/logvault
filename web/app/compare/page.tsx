"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  GitCompareArrows,
  Loader2,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { ComparisonForm } from "@/components/comparison-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ComparisonSummary, deleteComparison, listComparisons } from "@/lib/api";

const PAGE_SIZE = 20;

function fmt(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

function timeAgo(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

const STATUS_TONE: Record<string, "success" | "warning" | "danger"> = {
  ok: "success",
  partial: "warning",
  failed: "danger",
};

export default function ComparePage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [creating, setCreating] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [debouncedQuery, setDebouncedQuery] = React.useState("");
  const [page, setPage] = React.useState(0);
  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: ["comparisons", debouncedQuery, page],
    queryFn: () =>
      listComparisons({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        q: debouncedQuery || undefined,
      }),
    staleTime: 10_000,
  });

  const comparisons = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
      setPage(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  // Deleting the only row on the last page leaves an empty page; step back.
  React.useEffect(() => {
    if (data && data.items.length === 0 && page > 0) {
      setPage((current) => Math.max(0, current - 1));
    }
  }, [data, page]);

  const refresh = () => qc.invalidateQueries({ queryKey: ["comparisons"] });

  return (
    <div className="mx-auto max-w-6xl animate-fade-in px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3 pb-6">
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">Compare</h1>
          <p className="text-sm text-muted-foreground">
            Run a Last9 log query and a New Relic NRQL query over the same window — totals,
            per-bucket trend, and raw results side by side.
          </p>
        </div>
        <Button
          onClick={() => setCreating((value) => !value)}
          variant={creating ? "outline" : "primary"}
        >
          <Plus className="h-4 w-4" />
          {creating ? "Cancel" : "New comparison"}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-3 pb-4">
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search saved comparisons…"
            aria-label="Search saved comparisons"
            className="pl-9"
          />
        </div>
        {data && (
          <span className="text-xs text-muted-foreground">
            {total} saved comparison{total === 1 ? "" : "s"}
          </span>
        )}
        {isFetching && !isLoading && (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
        )}
      </div>

      {creating && (
        <div className="mb-5">
          <ComparisonForm
            onCancel={() => setCreating(false)}
            onSaved={(comparison) => {
              qc.invalidateQueries({ queryKey: ["comparisons"] });
              router.push(`/compare/${comparison.id}`);
            }}
          />
        </div>
      )}

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && (
        <p className="text-sm text-danger">{(error as Error)?.message ?? "Failed to load"}</p>
      )}

      {!isLoading && !isError && total === 0 && !creating && (
        <div className="flex flex-col items-center gap-3 border border-dashed border-border py-16 text-center">
          <div className="flex h-11 w-11 items-center justify-center bg-muted">
            {debouncedQuery ? (
              <Search className="h-5 w-5 text-muted-foreground" />
            ) : (
              <GitCompareArrows className="h-5 w-5 text-muted-foreground" />
            )}
          </div>
          <p className="text-sm font-medium">
            {debouncedQuery ? "No comparisons match that search" : "No saved comparisons yet"}
          </p>
          <p className="max-w-md text-xs text-muted-foreground">
            {debouncedQuery
              ? `Nothing matched “${debouncedQuery}”. Try a shorter name or clear the search.`
              : "Save a Last9 filter and a New Relic NRQL query, then run them over the same time range whenever you need to check ingestion parity."}
          </p>
          {debouncedQuery ? (
            <Button variant="outline" size="sm" onClick={() => setQuery("")}>
              Clear search
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
              Create the first one
            </Button>
          )}
        </div>
      )}

      <div className="grid gap-3">
        {comparisons.map((comparison) => (
          <ComparisonCard key={comparison.id} comparison={comparison} onDeleted={refresh} />
        ))}
      </div>

      {pageCount > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-3 pt-4 text-xs text-muted-foreground">
          <span>
            Page {page + 1} of {pageCount} · {total} saved comparison
            {total === 1 ? "" : "s"}
          </span>
          <div className="flex items-center gap-1.5">
            <Button
              size="sm"
              variant="outline"
              disabled={page === 0}
              onClick={() => setPage((current) => Math.max(0, current - 1))}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={page + 1 >= pageCount}
              onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}
            >
              Next
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}

      <div className="mt-6 flex items-center gap-2 border border-border bg-muted/40 px-4 py-3 text-xs text-muted-foreground">
        <ArrowLeftRight className="h-4 w-4 shrink-0" />
        <span>
          New Relic keys and account ids live under{" "}
          <Link href="/new-relic" className="font-medium text-primary hover:underline">
            New Relic connections
          </Link>
          .
        </span>
      </div>
    </div>
  );
}

function parityOf(
  last9: number | null | undefined,
  newrelic: number | null | undefined
): { tone: "success" | "warning" | "danger"; label: string } | null {
  if (last9 == null || newrelic == null) return null;
  if (last9 === 0 && newrelic === 0) return { tone: "success", label: "matched" };
  if (newrelic === 0) return { tone: "danger", label: "mismatch" };
  const pct = ((last9 - newrelic) / newrelic) * 100;
  const signed = `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
  const abs = Math.abs(pct);
  if (abs <= 1) return { tone: "success", label: `match ${signed}` };
  if (abs <= 5) return { tone: "warning", label: `close ${signed}` };
  return { tone: "danger", label: signed };
}

function ComparisonCard({
  comparison,
  onDeleted,
}: {
  comparison: ComparisonSummary;
  onDeleted: () => void;
}) {
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const parity =
    comparison.nr_value_mode === "sum"
      ? parityOf(comparison.last_run_last9_total, comparison.last_run_newrelic_total)
      : null;
  const delta =
    comparison.last_run_last9_total != null && comparison.last_run_newrelic_total != null
      ? comparison.last_run_last9_total - comparison.last_run_newrelic_total
      : null;
  const del = useMutation({
    mutationFn: () => deleteComparison(comparison.id),
    onSuccess: onDeleted,
    onError: (error: Error) => setDeleteError(error.message),
  });

  return (
    <Card className="transition-shadow">
      <CardContent className="flex flex-wrap items-start justify-between gap-4 p-4">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/compare/${comparison.id}`}
              className="text-sm font-semibold hover:text-primary"
            >
              {comparison.name}
            </Link>
            {comparison.last_run_status && (
              <Badge tone={STATUS_TONE[comparison.last_run_status] ?? "neutral"}>
                last run {comparison.last_run_status}
              </Badge>
            )}
            {parity && <Badge tone={parity.tone}>{parity.label}</Badge>}
          </div>
          {comparison.description && (
            <p className="max-w-2xl text-xs text-muted-foreground">{comparison.description}</p>
          )}
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <Badge tone="neutral">
              Last9 · {comparison.last9_index_name ?? "index"}
              {comparison.last9_region_code ? ` · ${comparison.last9_region_code}` : ""}
            </Badge>
            <Badge tone="info">
              New Relic · {comparison.nr_credential_label ?? "connection"}
              {comparison.nr_account_id ? ` · ${comparison.nr_account_id}` : ""}
            </Badge>
            {comparison.last_run_at && (
              <span title={new Date(comparison.last_run_at).toLocaleString()}>
                ran {timeAgo(comparison.last_run_at)}
              </span>
            )}
          </div>
          {comparison.last_run_at && (
            <div className="flex flex-wrap gap-4 font-mono text-[11px] text-muted-foreground">
              <span>Last9: {fmt(comparison.last_run_last9_total)}</span>
              <span>New Relic: {fmt(comparison.last_run_newrelic_total)}</span>
              {delta != null && (
                <span className={delta === 0 ? "" : "text-foreground"}>
                  Δ {delta > 0 ? "+" : ""}
                  {fmt(delta)}
                </span>
              )}
            </div>
          )}
          {deleteError && <p className="text-xs text-danger">{deleteError}</p>}
        </div>

        <div className="flex items-center gap-2">
          <Link href={`/compare/${comparison.id}`}>
            <Button size="sm" variant="outline">
              Open
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </Link>
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
                {del.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Delete
              </Button>
            </>
          ) : (
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Delete ${comparison.name}`}
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="h-4 w-4 text-danger" />
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
