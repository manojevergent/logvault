"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronRight, Loader2, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, fieldClass } from "@/components/ui/input";
import { FilterTemplate, createGroup, listIndexes, listTemplates } from "@/lib/api";
import { PRESETS, Tz, epochToLocal, formatEpoch, localToEpoch } from "@/lib/time";

const MAX_GROUP = 50;

export default function NewGroupPage() {
  const router = useRouter();
  const templates = useQuery({ queryKey: ["templates"], queryFn: listTemplates });
  const indexes = useQuery({ queryKey: ["indexes", ""], queryFn: () => listIndexes() });

  const [selected, setSelected] = React.useState<Set<number>>(new Set());
  const [query, setQuery] = React.useState("");
  const [name, setName] = React.useState("");
  const [preset, setPreset] = React.useState<number | "custom">(3600);
  const [format, setFormat] = React.useState<"csv" | "jsonl">("csv");
  const nowSec = Math.floor(Date.now() / 1000);
  const [customStart, setCustomStart] = React.useState(epochToLocal(nowSec - 3600, "UTC"));
  const [customEnd, setCustomEnd] = React.useState(epochToLocal(nowSec, "UTC"));

  const sourceLabel = React.useCallback(
    (tpl: FilterTemplate) => {
      const index = indexes.data?.find((item) => item.id === tpl.index_target_id);
      if (index) return `${index.name} · ${index.region_code}`;
      if (tpl.region_code) return `index #${tpl.index_target_id} · ${tpl.region_code}`;
      return "no saved source";
    },
    [indexes.data]
  );

  const filtered = React.useMemo(() => {
    const pool = templates.data ?? [];
    const needle = query.trim().toLowerCase();
    if (!needle) return pool;
    return pool.filter((tpl) =>
      `${tpl.name} ${tpl.customer ?? ""} ${sourceLabel(tpl)}`.toLowerCase().includes(needle)
    );
  }, [templates.data, query, sourceLabel]);

  const byCustomer = React.useMemo(() => {
    const groups = new Map<string, FilterTemplate[]>();
    for (const tpl of filtered) {
      const customer = tpl.customer?.trim() || "(unassigned)";
      const bucket = groups.get(customer);
      if (bucket) bucket.push(tpl);
      else groups.set(customer, [tpl]);
    }
    return [...groups.entries()]
      .map(([customer, rows]) => ({
        customer,
        rows: rows.sort((a, b) => a.name.localeCompare(b.name)),
      }))
      .sort((a, b) => a.customer.localeCompare(b.customer));
  }, [filtered]);

  const selectedTemplates = React.useMemo(
    () => (templates.data ?? []).filter((tpl) => selected.has(tpl.id)),
    [templates.data, selected]
  );
  const missingSource = selectedTemplates.some((tpl) => tpl.index_target_id == null);

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < MAX_GROUP) next.add(id);
      return next;
    });
  }

  function selectCustomer(rows: FilterTemplate[]) {
    setSelected((prev) => {
      const next = new Set(prev);
      const allSelected = rows.every((tpl) => next.has(tpl.id));
      for (const tpl of rows) {
        if (allSelected) next.delete(tpl.id);
        else if (next.size < MAX_GROUP) next.add(tpl.id);
      }
      return next;
    });
  }

  function selectVisible() {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const tpl of filtered) {
        if (next.size >= MAX_GROUP) break;
        next.add(tpl.id);
      }
      return next;
    });
  }

  const window = React.useMemo(() => {
    if (preset !== "custom") {
      const end = Math.floor(Date.now() / 1000);
      return { start: end - preset, end };
    }
    return {
      start: localToEpoch(customStart, "UTC" as Tz),
      end: localToEpoch(customEnd, "UTC" as Tz),
    };
  }, [preset, customStart, customEnd]);
  const validWindow =
    Number.isFinite(window.start) && Number.isFinite(window.end) && window.end > window.start;

  const create = useMutation({
    mutationFn: (isPreview: boolean) =>
      createGroup({
        name,
        items: selectedTemplates.map((tpl) => ({ template_id: tpl.id })),
        start_epoch: window.start,
        end_epoch: window.end,
        output_format: format,
        is_preview: isPreview,
      }),
    onSuccess: (group) => router.push(`/groups/${group.id}`),
  });

  const canRun = selected.size > 0 && !missingSource && validWindow && !create.isPending;

  return (
    <div className="mx-auto max-w-6xl animate-fade-in px-4 py-5">
      <Link
        href="/groups"
        className="mb-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Groups
      </Link>
      <div className="mb-4">
        <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Extract</p>
        <h1 className="text-xl font-semibold tracking-tight">New group extraction</h1>
        <p className="text-xs text-muted-foreground">
          Pick saved searches and one window. Each search runs against its own saved index with its
          own filter and file; the group tracks them together.
        </p>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader className="border-b border-border/60 pb-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <CardTitle className="text-foreground">Choose saved searches</CardTitle>
                <Badge tone={selected.size ? "info" : "neutral"}>{selected.size} selected</Badge>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <button
                  type="button"
                  className="text-primary hover:underline"
                  onClick={selectVisible}
                >
                  Select visible
                </button>
                <span className="text-muted-foreground">·</span>
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground"
                  onClick={() => setSelected(new Set())}
                >
                  Clear
                </button>
              </div>
            </div>
            <div className="relative mt-2">
              <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by name, customer or source…"
                className="pl-8"
                aria-label="Search saved searches"
              />
            </div>
          </CardHeader>
          <CardContent className="max-h-[65vh] overflow-y-auto p-2">
            {templates.isLoading && !templates.data ? (
              <p className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading searches…
              </p>
            ) : templates.isError ? (
              <p className="p-4 text-sm text-danger">{(templates.error as Error).message}</p>
            ) : byCustomer.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">
                No saved searches match.{" "}
                <Link href="/templates" className="text-primary hover:underline">
                  Manage saved searches
                </Link>
                .
              </p>
            ) : (
              byCustomer.map(({ customer, rows }) => {
                const all = rows.every((tpl) => selected.has(tpl.id));
                return (
                  <div key={customer} className="mb-2 border border-border/60">
                    <div className="flex items-center justify-between gap-2 bg-muted/40 px-3 py-1.5">
                      <p className="text-xs font-semibold">{customer}</p>
                      <button
                        type="button"
                        className="text-[11px] text-primary hover:underline"
                        onClick={() => selectCustomer(rows)}
                      >
                        {all ? "Deselect all" : "Select all"}
                      </button>
                    </div>
                    <div className="divide-y divide-border/50">
                      {rows.map((tpl) => {
                        const disabled = !selected.has(tpl.id) && selected.size >= MAX_GROUP;
                        return (
                          <label
                            key={tpl.id}
                            className={`flex cursor-pointer items-start gap-2.5 px-3 py-2 text-sm transition-colors hover:bg-accent/40 ${
                              disabled ? "cursor-not-allowed opacity-50" : ""
                            }`}
                          >
                            <input
                              type="checkbox"
                              className="mt-0.5 h-4 w-4"
                              checked={selected.has(tpl.id)}
                              disabled={disabled}
                              onChange={() => toggle(tpl.id)}
                              aria-label={`Select ${tpl.name}`}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="flex flex-wrap items-center gap-1.5">
                                <span className="font-medium">{tpl.name}</span>
                                {tpl.aggregation?.enabled && <Badge tone="info">parse</Badge>}
                                {tpl.index_target_id == null && (
                                  <Badge tone="warning">no source</Badge>
                                )}
                              </span>
                              <span className="mt-0.5 block font-mono text-[11px] text-muted-foreground">
                                {sourceLabel(tpl)}
                              </span>
                            </span>
                            <ChevronRight className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                          </label>
                        );
                      })}
                    </div>
                  </div>
                );
              })
            )}
          </CardContent>
        </Card>

        <div className="lg:sticky lg:top-4">
          <Card>
            <CardHeader className="border-b border-border/60 pb-3">
              <CardTitle className="text-foreground">Run settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 p-4">
              <div className="space-y-1.5">
                <Label>Group name (optional)</Label>
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="e.g. Month-end invoice batch"
                  maxLength={160}
                />
              </div>

              <div className="space-y-1.5">
                <Label>Window (UTC)</Label>
                <div className="flex flex-wrap gap-1.5">
                  {PRESETS.map((option) => (
                    <Button
                      key={option.seconds}
                      type="button"
                      size="sm"
                      variant={preset === option.seconds ? "primary" : "outline"}
                      onClick={() => setPreset(option.seconds)}
                    >
                      {option.label.replace("Last ", "")}
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
                {preset === "custom" && (
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label className="text-[11px]">Start</Label>
                      <Input
                        type="datetime-local"
                        value={customStart}
                        onChange={(event) => setCustomStart(event.target.value)}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px]">End</Label>
                      <Input
                        type="datetime-local"
                        value={customEnd}
                        onChange={(event) => setCustomEnd(event.target.value)}
                      />
                    </div>
                  </div>
                )}
                <p
                  className={`font-mono text-[11px] ${validWindow ? "text-muted-foreground" : "text-danger"}`}
                >
                  {validWindow
                    ? `${formatEpoch(window.start)} → ${formatEpoch(window.end)} UTC`
                    : "End must be after start."}
                </p>
              </div>

              <div className="space-y-1.5">
                <Label>Output format</Label>
                <select
                  className={fieldClass}
                  value={format}
                  onChange={(event) => setFormat(event.target.value as "csv" | "jsonl")}
                >
                  <option value="csv">CSV</option>
                  <option value="jsonl">JSONL</option>
                </select>
              </div>

              <div className="border-t border-border/60 pt-3 text-xs text-muted-foreground">
                <p>
                  <strong className="text-foreground">{selected.size}</strong> search
                  {selected.size === 1 ? "" : "es"}
                  {selectedTemplates[0]?.customer
                    ? ` · ${new Set(selectedTemplates.map((t) => t.customer)).size} customer${
                        new Set(selectedTemplates.map((t) => t.customer)).size === 1 ? "" : "s"
                      }`
                    : ""}
                </p>
                <p className="mt-1">
                  Each search uses its saved index. Test samples up to 100 rows per search; run
                  processes the full window.
                </p>
                {missingSource && (
                  <p className="mt-2 text-danger">
                    Some selected searches have no saved source. Edit them under Saved searches and
                    pick an index first.
                  </p>
                )}
              </div>

              {create.isError && (
                <p className="text-xs text-danger">{(create.error as Error).message}</p>
              )}

              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={!canRun}
                  onClick={() => create.mutate(true)}
                >
                  Test group
                </Button>
                <Button type="button" disabled={!canRun} onClick={() => create.mutate(false)}>
                  {create.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Run group
                </Button>
              </div>
              {selected.size === MAX_GROUP && (
                <p className="text-[11px] text-muted-foreground">
                  Maximum {MAX_GROUP} searches per group.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
