"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bookmark,
  Calendar,
  Check,
  Loader2,
  Pencil,
  Play,
  PlayCircle,
  Trash2,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FieldGroup, Input, Label, fieldClass } from "@/components/ui/input";
import {
  FilterTemplate,
  Job,
  createBatchJobs,
  deleteTemplate,
  listCredentials,
  listIndexes,
  listLogFormats,
  listS3Profiles,
  listTemplates,
  updateTemplate,
} from "@/lib/api";
import {
  OutputColumnsEditor,
  orderBySeq,
  suggestUniformLayout,
} from "@/components/output-columns-editor";
import { extractGroupNames } from "@/lib/aggregation";
import { PRESETS, Tz, epochToLocal, formatEpoch, localToEpoch } from "@/lib/time";

function splitCsv(s: string): string[] {
  return s
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);
}

function Field({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <FieldGroup>
      <div className={`space-y-1.5 ${className ?? ""}`}>
        <Label>{label}</Label>
        {children}
      </div>
    </FieldGroup>
  );
}

export default function TemplatesPage() {
  const qc = useQueryClient();
  const { data: templates, isLoading } = useQuery({
    queryKey: ["templates"],
    queryFn: listTemplates,
  });
  // Batch runs: tick several searches, run them all over one shared window.
  const [selection, setSelection] = React.useState<Set<number>>(new Set());
  const [batchOpen, setBatchOpen] = React.useState(false);

  const refresh = () => qc.invalidateQueries({ queryKey: ["templates"] });

  function toggleSelect(id: number) {
    setSelection((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="mx-auto max-w-5xl animate-fade-in px-6 py-8">
      <div className="space-y-1.5 pb-6">
        <h1 className="text-xl font-semibold tracking-tight">Saved searches</h1>
        <p className="text-sm text-muted-foreground">
          Reusable filters and parse patterns, saved from the New Extraction wizard or a schedule.
          Each search stores the source it runs against — index, region and credential — along with
          its customer, so loading one is enough to run it.
        </p>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {templates && templates.length === 0 && (
        <div className="flex flex-col items-center gap-3 border border-dashed border-border py-16 text-center">
          <div className="flex h-11 w-11 items-center justify-center bg-muted">
            <Bookmark className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium">No saved searches yet</p>
          <p className="max-w-sm text-xs text-muted-foreground">
            Build a filter in the New Extraction wizard, then click &ldquo;Save as search&rdquo; to
            reuse it later.
          </p>
        </div>
      )}

      {selection.size > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 border border-border bg-muted/40 px-3 py-2">
          <span className="text-sm font-medium">{selection.size} selected</span>
          <div className="flex-1" />
          <Button size="sm" variant="ghost" onClick={() => setSelection(new Set())}>
            Clear
          </Button>
          <Button size="sm" onClick={() => setBatchOpen(true)}>
            Run {selection.size} over one window…
          </Button>
        </div>
      )}

      <div className="space-y-3">
        {templates?.map((t) => (
          <TemplateCard
            key={t.id}
            tpl={t}
            onChange={refresh}
            selected={selection.has(t.id)}
            onToggle={() => toggleSelect(t.id)}
          />
        ))}
      </div>

      {batchOpen && (
        <BatchDialog
          templates={(templates ?? []).filter((t) => selection.has(t.id))}
          onClose={() => setBatchOpen(false)}
          onDone={() => {
            setBatchOpen(false);
            setSelection(new Set());
          }}
        />
      )}
    </div>
  );
}

function getYesterdayUtcWindow(): { start: number; end: number } {
  const now = new Date();
  const yStart = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - 1, 0, 0, 0)
  );
  const yEnd = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 0, 0, 0)
  );
  return {
    start: Math.floor(yStart.getTime() / 1000),
    end: Math.floor(yEnd.getTime() / 1000),
  };
}

function getLast24hWindow(): { start: number; end: number } {
  const now = Math.floor(Date.now() / 1000);
  return { start: now - 86400, end: now };
}

function TemplateCard({
  tpl,
  onChange,
  selected,
  onToggle,
}: {
  tpl: FilterTemplate;
  onChange: () => void;
  selected: boolean;
  onToggle: () => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [confirmDel, setConfirmDel] = React.useState(false);
  const [quickMsg, setQuickMsg] = React.useState("");
  const router = useRouter();
  const del = useMutation({ mutationFn: () => deleteTemplate(tpl.id), onSuccess: onChange });

  const quickRun = useMutation({
    mutationFn: (win: { start: number; end: number }) =>
      createBatchJobs({
        items: [{ template_id: tpl.id }],
        start_epoch: win.start,
        end_epoch: win.end,
      }),
    onSuccess: (jobs) => {
      if (jobs[0]) {
        setQuickMsg(`Job #${jobs[0].id} queued!`);
        setTimeout(() => setQuickMsg(""), 4000);
      }
    },
    onError: (err) => {
      setQuickMsg((err as Error).message);
      setTimeout(() => setQuickMsg(""), 5000);
    },
  });

  if (editing) {
    return (
      <TemplateEditForm
        tpl={tpl}
        onCancel={() => setEditing(false)}
        onSaved={() => {
          setEditing(false);
          onChange();
        }}
      />
    );
  }

  return (
    <Card>
      <CardContent className="flex flex-wrap items-start justify-between gap-4 p-4">
        <div className="flex min-w-0 items-start gap-3">
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            className="mt-1 h-4 w-4"
            aria-label={`Select ${tpl.name} for batch run`}
            title="Select for batch run"
          />
          <div className="min-w-0 space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="font-medium">{tpl.name}</span>
              {tpl.aggregation?.enabled && <Badge tone="info">parse & aggregate</Badge>}
              {tpl.s3_profile_id && (
                <Badge tone="info">S3: {tpl.s3_profile_label ?? `#${tpl.s3_profile_id}`}</Badge>
              )}
              {tpl.customer ? (
                <Badge tone="neutral">{tpl.customer}</Badge>
              ) : (
                // Saved before a customer was mandatory — it has to be filled in
                // (Edit → Customer) before this search can be saved again.
                <Badge tone="warning">no customer</Badge>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {[...tpl.phrases, ...tpl.message_types].map((p, i) => (
                <Badge key={`p${i}`} tone="info">
                  {p}
                </Badge>
              ))}
              {(tpl.exact_phrases ?? []).map((p, i) => (
                <Badge key={`e${i}`} tone="info">
                  <span className="font-mono">&quot;{p}&quot;</span>
                </Badge>
              ))}
              {(tpl.exclude_phrases ?? []).map((p, i) => (
                <Badge key={`x${i}`} tone="danger">
                  NOT {p}
                </Badge>
              ))}
              {(tpl.exclude_exact_phrases ?? []).map((p, i) => (
                <Badge key={`xe${i}`} tone="danger">
                  <span className="font-mono">NOT &quot;{p}&quot;</span>
                </Badge>
              ))}
              {tpl.ids.length > 0 && (
                <Badge tone="neutral">
                  {tpl.ids.length} ID{tpl.ids.length === 1 ? "" : "s"}
                </Badge>
              )}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {quickMsg ? (
            <span className="text-xs font-medium text-success">{quickMsg}</span>
          ) : (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => quickRun.mutate(getLast24hWindow())}
                disabled={quickRun.isPending}
                title="Run extraction for this search over the last 24 hours"
              >
                {quickRun.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5 text-primary" />
                )}
                Last 24h
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => quickRun.mutate(getYesterdayUtcWindow())}
                disabled={quickRun.isPending}
                title="Run extraction for this search over yesterday (00:00 - 23:59 UTC)"
              >
                <Calendar className="h-3.5 w-3.5 text-primary" />
                Yesterday
              </Button>
            </>
          )}
          <Button
            size="icon"
            variant="ghost"
            aria-label={`Edit ${tpl.name}`}
            onClick={() => setEditing(true)}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          {confirmDel ? (
            <span className="flex items-center gap-1 border border-danger/60 bg-muted px-1.5 py-0.5">
              <span className="text-[11px] font-medium text-danger">Delete?</span>
              <Button
                size="sm"
                variant="ghost"
                className="h-5 px-1.5 text-xs text-danger hover:bg-danger/20"
                onClick={() => del.mutate()}
                disabled={del.isPending}
              >
                {del.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Yes"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-5 px-1.5 text-xs text-muted-foreground"
                onClick={() => setConfirmDel(false)}
              >
                No
              </Button>
            </span>
          ) : (
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Delete ${tpl.name}`}
              title="Delete this saved search"
              onClick={() => setConfirmDel(true)}
            >
              <Trash2 className="h-4 w-4 text-danger" />
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// Edits every field the New Extraction wizard's "Save as search" can set,
// including the parse/aggregate output config — not just the filter.
// raw_column_defaults and timestamp_column have no control here (the wizard
// doesn't expose them either); the API preserves whatever a template already
// has for those on every save from this form.
function TemplateEditForm({
  tpl,
  onCancel,
  onSaved,
}: {
  tpl: FilterTemplate;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const agg = tpl.aggregation;
  const [name, setName] = React.useState(tpl.name);
  const [customer, setCustomer] = React.useState(tpl.customer ?? "");
  const [phrasesText, setPhrasesText] = React.useState(tpl.phrases.join(", "));
  const [idsText, setIdsText] = React.useState(tpl.ids.join(", "));
  const [exactText, setExactText] = React.useState((tpl.exact_phrases ?? []).join(", "));
  const [excludeText, setExcludeText] = React.useState((tpl.exclude_phrases ?? []).join(", "));
  const [excludeExactText, setExcludeExactText] = React.useState(
    (tpl.exclude_exact_phrases ?? []).join(", ")
  );
  const [messageTypesText, setMessageTypesText] = React.useState(tpl.message_types.join(", "));

  const [aggEnabled, setAggEnabled] = React.useState(agg?.enabled ?? false);
  const [useLibrary, setUseLibrary] = React.useState(agg?.use_library ?? false);
  const [regex, setRegex] = React.useState(agg?.regex ?? "");
  const [groupByText, setGroupByText] = React.useState((agg?.group_by ?? []).join(", "));
  const [uniqueFieldsText, setUniqueFieldsText] = React.useState(
    (agg?.unique_fields ?? []).join(", ")
  );
  const [skipRawOutput, setSkipRawOutput] = React.useState(agg?.skip_raw_output ?? false);
  const [sampleLine, setSampleLine] = React.useState("");
  // Which parsed fields land in the output file, independent of group_by/
  // unique_fields. Seeded from whatever this template already has saved, so
  // reopening Edit shows the choice it was last saved with rather than
  // "nothing excluded" while a different set sits in the database.
  const [includedFieldsOverride, setIncludedFieldsOverride] = React.useState<Set<string> | null>(
    agg?.raw_columns && agg.raw_columns.length > 0 ? new Set(agg.raw_columns) : null
  );
  const [colSeq, setColSeq] = React.useState<Record<string, number>>(() => {
    const seq: Record<string, number> = {};
    (agg?.raw_columns ?? []).forEach((f, i) => {
      seq[f] = i + 1;
    });
    return seq;
  });
  const [colLabels, setColLabels] = React.useState<Record<string, string>>({
    ...(agg?.column_labels ?? {}),
  });
  const [colDefaults, setColDefaults] = React.useState<Record<string, string>>({
    ...(agg?.raw_column_defaults ?? {}),
  });
  const [timestampHeader, setTimestampHeader] = React.useState(
    agg?.timestamp_column ?? "timestamp_utc"
  );
  // log_format (which pattern matched) and message (the raw line) are the two
  // columns that aren't a regex field — their own toggles, seeded from
  // whatever this template already has saved.
  const [includeLogFormat, setIncludeLogFormat] = React.useState(agg?.include_log_format ?? true);
  const [includeMessageColumn, setIncludeMessageColumn] = React.useState(
    agg?.include_message ?? true
  );
  // Remembered source: pre-fills batch runs and the wizard. Blank = no
  // default (source picked at run time, as before).
  const { data: allIndexes } = useQuery({
    queryKey: ["indexes", ""],
    queryFn: () => listIndexes(),
  });
  const { data: credentials } = useQuery({ queryKey: ["credentials"], queryFn: listCredentials });
  const { data: s3Profiles } = useQuery({ queryKey: ["s3-profiles"], queryFn: listS3Profiles });
  const [sourceIdx, setSourceIdx] = React.useState<number | "">(tpl.index_target_id ?? "");
  const [sourceCred, setSourceCred] = React.useState<number | "">(tpl.credential_id ?? "");
  const [s3ProfileId, setS3ProfileId] = React.useState<number | "">(tpl.s3_profile_id ?? "");
  const sourceTarget = allIndexes?.find((i) => i.id === sourceIdx);
  const resolvedSource = {
    credential_id:
      sourceCred === "" || sourceCred == null
        ? (sourceTarget?.credential_id ?? null)
        : Number(sourceCred),
    region_code: sourceTarget?.region_code ?? tpl.region_code ?? null,
    index_target_id: sourceIdx === "" ? null : Number(sourceIdx),
  };

  const groupBy = splitCsv(groupByText);
  const uniqueFields = splitCsv(uniqueFieldsText);
  const overlapping = groupBy.filter((f) => uniqueFields.includes(f));

  const { data: libraryFormats } = useQuery({
    queryKey: ["log-formats"],
    queryFn: listLogFormats,
    enabled: aggEnabled && useLibrary,
  });
  const libraryFields = React.useMemo(() => {
    const out: string[] = [];
    for (const f of libraryFormats ?? []) {
      if (f.enabled === false) continue;
      for (const g of extractGroupNames(f.regex)) {
        if (!out.includes(g)) out.push(g);
      }
    }
    return out;
  }, [libraryFormats]);
  const regexFields = useLibrary ? libraryFields : extractGroupNames(regex);
  const defaultIncludedFields = new Set([...groupBy, ...uniqueFields]);
  const includedFields = includedFieldsOverride ?? defaultIncludedFields;
  const orderedIncludedFields = orderBySeq(regexFields, colSeq).filter((f) =>
    includedFields.has(f)
  );
  // ORDER-sensitive: a set comparison silently discards a numbering that
  // reorders the default fields (e.g. api=1, SPAccountId=2, bu_name=3) by
  // sending raw_columns: [], and the file comes out in group_by order.
  const defaultOrder = [...defaultIncludedFields];
  const rawColumnsSameAsDefault =
    orderedIncludedFields.length === defaultOrder.length &&
    orderedIncludedFields.every((f, i) => f === defaultOrder[i]);
  const rawColumns = rawColumnsSameAsDefault ? [] : orderedIncludedFields;
  const columnLabels = React.useMemo(() => {
    const out: Record<string, string> = {};
    for (const f of orderedIncludedFields) {
      const label = (colLabels[f] ?? "").trim();
      if (label && label !== f) out[f] = label;
    }
    return out;
  }, [orderedIncludedFields, colLabels]);
  const columnDefaults = React.useMemo(() => {
    const out: Record<string, string> = {};
    for (const f of orderedIncludedFields) {
      if ((colDefaults[f] ?? "") !== "") out[f] = colDefaults[f];
    }
    return out;
  }, [orderedIncludedFields, colDefaults]);

  function applyUniformLayout() {
    const layout = suggestUniformLayout(regexFields);
    const seq: Record<string, number> = {};
    layout.rawColumns.forEach((f, i) => {
      seq[f] = i + 1;
    });
    setColSeq(seq);
    setColLabels(layout.columnLabels);
    setTimestampHeader(layout.timestampColumn);
    setIncludedFieldsOverride(new Set(layout.rawColumns));
    setIncludeLogFormat(false);
    setIncludeMessageColumn(false);
  }

  function toggleIncludedField(field: string) {
    if (!includedFields.has(field) && colSeq[field] == null) {
      const next = Math.max(0, ...Object.values(colSeq)) + 1;
      setColSeq((prev) => (prev[field] != null ? prev : { ...prev, [field]: next }));
    }
    setIncludedFieldsOverride((prev) => {
      const next = new Set(prev ?? defaultIncludedFields);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  }

  const sampleTest = React.useMemo(() => {
    if (useLibrary || !regex.trim() || !sampleLine.trim()) {
      return { error: null as string | null, groups: null as Record<string, string> | null };
    }
    try {
      const m = new RegExp(regex).exec(sampleLine);
      return { error: null, groups: (m?.groups as Record<string, string> | undefined) ?? null };
    } catch (e) {
      return { error: (e as Error).message, groups: null };
    }
  }, [regex, sampleLine, useLibrary]);

  const save = useMutation({
    mutationFn: () =>
      updateTemplate(tpl.id, {
        name: name.trim(),
        phrases: splitCsv(phrasesText),
        ids: splitCsv(idsText),
        exact_phrases: splitCsv(exactText),
        exclude_phrases: splitCsv(excludeText),
        exclude_exact_phrases: splitCsv(excludeExactText),
        message_types: splitCsv(messageTypesText),
        customer: customer.trim(),
        credential_id: resolvedSource.credential_id,
        region_code: resolvedSource.region_code,
        index_target_id: resolvedSource.index_target_id,
        s3_profile_id: s3ProfileId === "" ? null : Number(s3ProfileId),
        aggregation: aggEnabled
          ? {
              enabled: true,
              regex: useLibrary ? "" : regex,
              group_by: groupBy,
              unique_fields: uniqueFields,
              skip_raw_output: skipRawOutput,
              use_library: useLibrary,
              raw_columns: rawColumns,
              include_log_format: includeLogFormat,
              include_message: includeMessageColumn,
              column_labels: columnLabels,
              raw_column_defaults: columnDefaults,
              timestamp_column: timestampHeader.trim() || "timestamp_utc",
            }
          : null,
      }),
    onSuccess: onSaved,
  });

  const canSave =
    name.trim() !== "" &&
    // A saved search is filed under a customer; it names the export folder and
    // is what the jobs list shows, so it is not optional.
    customer.trim() !== "" &&
    // ...and it stores the index it runs against, so loading it never queries
    // the wrong source (which silently returns zero rows).
    resolvedSource.index_target_id != null &&
    (splitCsv(phrasesText).length > 0 ||
      splitCsv(idsText).length > 0 ||
      splitCsv(messageTypesText).length > 0 ||
      aggEnabled);

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Customer (required)">
            <Input
              value={customer}
              onChange={(e) => setCustomer(e.target.value)}
              placeholder="ABSCBN"
              required
            />
            {!customer.trim() && (
              <p className="text-xs text-danger">Required to save this search.</p>
            )}
          </Field>
          <Field label="Source (saved with the search)">
            <select
              className={fieldClass}
              value={sourceIdx}
              onChange={(e) => setSourceIdx(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">No source — required to save.</option>
              {allIndexes?.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name} · {i.region_code}
                  {i.credential_label ? ` · ${i.credential_label}` : ""}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              The index is stored with the search; loading it selects this source automatically.
            </p>
            {resolvedSource.index_target_id == null && (
              <p className="text-xs text-danger">
                Pick the source this search runs against — without it a load can query the wrong
                index and return nothing.
              </p>
            )}
          </Field>
          {sourceTarget && !sourceTarget.credential_id && (
            <Field label="Credential (source has none)">
              <select
                className={fieldClass}
                value={sourceCred}
                onChange={(e) => setSourceCred(e.target.value ? Number(e.target.value) : "")}
              >
                <option value="">Pick at run time…</option>
                {credentials?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label} ({c.org_slug})
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Default S3 destination (optional)">
            <select
              className={fieldClass}
              value={s3ProfileId}
              onChange={(e) => setS3ProfileId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">No S3 upload — local download only</option>
              {s3Profiles?.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name} · {profile.bucket}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              Used by jobs and schedules created from this search. Existing jobs keep their
              snapshotted destination.
            </p>
          </Field>
          <Field label="Phrases (comma-separated)" className="sm:col-span-2">
            <Input value={phrasesText} onChange={(e) => setPhrasesText(e.target.value)} />
          </Field>
          <Field label="Exact phrases (comma-separated)" className="sm:col-span-2">
            <Input
              value={exactText}
              onChange={(e) => setExactText(e.target.value)}
              placeholder="API : 502"
            />
            <p className="text-xs text-muted-foreground">
              These tokens must appear <strong>adjacent</strong> (matched as a regex). Use this
              instead of loose words when a number also occurs elsewhere in the line, e.g. in a
              timestamp.
            </p>
          </Field>
          <Field label="Excluded phrases (comma-separated)" className="sm:col-span-2">
            <Input
              value={excludeText}
              onChange={(e) => setExcludeText(e.target.value)}
              placeholder="healthcheck"
            />
            <p className="text-xs text-muted-foreground">
              A log containing any of these is excluded (Last9{" "}
              <span className="font-mono">$notcontains</span>).
            </p>
          </Field>
          <Field label="Excluded exact phrases (comma-separated)" className="sm:col-span-2">
            <Input
              value={excludeExactText}
              onChange={(e) => setExcludeExactText(e.target.value)}
              placeholder="API : 502"
            />
            <p className="text-xs text-muted-foreground">
              Excluded only when these tokens are <strong>adjacent</strong> (
              <span className="font-mono">$notregex</span>).
            </p>
          </Field>
          <Field label="IDs (comma-separated)" className="sm:col-span-2">
            <Input value={idsText} onChange={(e) => setIdsText(e.target.value)} />
          </Field>
          <Field label="Message types (comma-separated)" className="sm:col-span-2">
            <Input value={messageTypesText} onChange={(e) => setMessageTypesText(e.target.value)} />
          </Field>
        </div>

        <div className="border-t border-border pt-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={aggEnabled}
              onChange={(e) => setAggEnabled(e.target.checked)}
              className="h-4 w-4"
            />
            Parse & aggregate output
          </label>
          {!aggEnabled && (
            <p className="mt-1 text-xs text-muted-foreground">
              Left off: the raw export is exactly <span className="font-mono">timestamp_utc</span> +{" "}
              <span className="font-mono">message</span> — no parsing, nothing else added.
            </p>
          )}

          {aggEnabled && (
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="flex items-center gap-2 text-sm sm:col-span-2">
                <input
                  type="checkbox"
                  checked={useLibrary}
                  onChange={(e) => setUseLibrary(e.target.checked)}
                  className="h-4 w-4"
                />
                Use the Log Formats library instead of one regex
              </label>

              {!useLibrary && (
                <Field label="Regex with named groups" className="sm:col-span-2">
                  <textarea
                    className={`${fieldClass} h-20 py-2 font-mono text-xs`}
                    value={regex}
                    onChange={(e) => setRegex(e.target.value)}
                  />
                </Field>
              )}
              <Field label="Group by (comma-separated)">
                <Input value={groupByText} onChange={(e) => setGroupByText(e.target.value)} />
              </Field>
              <Field label="Count unique values of (comma-separated)">
                <Input
                  value={uniqueFieldsText}
                  onChange={(e) => setUniqueFieldsText(e.target.value)}
                />
              </Field>
              {overlapping.length > 0 && (
                <p className="text-xs text-danger sm:col-span-2">
                  <strong>{overlapping.join(", ")}</strong> is in both boxes — every count would
                  come out as 1. Remove it from &ldquo;Group by&rdquo;.
                </p>
              )}
              <label className="flex items-center gap-2 text-sm sm:col-span-2">
                <input
                  type="checkbox"
                  checked={skipRawOutput}
                  onChange={(e) => setSkipRawOutput(e.target.checked)}
                  className="h-4 w-4"
                />
                Summary only — skip writing the raw matched rows to a file
              </label>

              <div className="flex flex-wrap items-center gap-4 sm:col-span-2">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={includeLogFormat}
                    onChange={(e) => setIncludeLogFormat(e.target.checked)}
                    className="h-4 w-4"
                  />
                  Include <span className="font-mono text-xs">log_format</span> column
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={includeMessageColumn}
                    onChange={(e) => setIncludeMessageColumn(e.target.checked)}
                    className="h-4 w-4"
                  />
                  Include <span className="font-mono text-xs">message</span> (the raw log line)
                </label>
              </div>

              {!useLibrary && (
                <Field label="Test against a sample log line (optional)" className="sm:col-span-2">
                  <textarea
                    className={`${fieldClass} h-16 py-2 font-mono text-xs`}
                    value={sampleLine}
                    onChange={(e) => setSampleLine(e.target.value)}
                    placeholder="Paste one real log line to check the regex extracts what you expect"
                  />
                </Field>
              )}
              {sampleTest.error && (
                <p className="text-xs text-danger sm:col-span-2">{sampleTest.error}</p>
              )}
              {sampleLine.trim() && !sampleTest.error && !sampleTest.groups && (
                <p className="text-xs text-danger sm:col-span-2">
                  No match — check the regex against this line.
                </p>
              )}

              {/* Validate the output before saving: every field the regex
                  parses, with a box to drop whichever ones the output file
                  doesn't need (group_by/unique_fields keep driving the
                  aggregation either way), and a preview of the exact row
                  that choice produces. */}
              {regexFields.length > 0 && (
                <div className="space-y-3 border-t border-border pt-3 sm:col-span-2">
                  <OutputColumnsEditor
                    fields={regexFields}
                    included={includedFields}
                    seq={colSeq}
                    labels={colLabels}
                    defaults={colDefaults}
                    timestampColumn={timestampHeader}
                    sampleValues={sampleTest.groups}
                    onToggle={toggleIncludedField}
                    onSeq={(f, v) =>
                      setColSeq((prev) => {
                        if (v === null) {
                          const next = { ...prev };
                          delete next[f];
                          return next;
                        }
                        return { ...prev, [f]: v };
                      })
                    }
                    onLabel={(f, v) =>
                      setColLabels((prev) => {
                        const next = { ...prev };
                        if (v.trim() === "") delete next[f];
                        else next[f] = v;
                        return next;
                      })
                    }
                    onDefault={(f, v) =>
                      setColDefaults((prev) => {
                        const next = { ...prev };
                        if (v === "") delete next[f];
                        else next[f] = v;
                        return next;
                      })
                    }
                    onTimestampColumn={setTimestampHeader}
                    onApplyUniform={applyUniformLayout}
                  />

                  <div className="space-y-1.5">
                    <Label>Output row preview</Label>
                    {sampleTest.groups || useLibrary ? (
                      <div className="overflow-auto border border-border">
                        <table className="w-full text-left text-xs">
                          <thead className="bg-muted text-muted-foreground">
                            <tr>
                              <th className="px-2 py-1 font-medium">
                                {timestampHeader.trim() || "timestamp"}
                              </th>
                              {includeLogFormat && (
                                <th className="px-2 py-1 font-medium">log_format</th>
                              )}
                              {orderedIncludedFields.map((f) => (
                                <th key={f} className="px-2 py-1 font-mono font-medium">
                                  {(colLabels[f] ?? "").trim() || f}
                                </th>
                              ))}
                              {includeMessageColumn && (
                                <th className="px-2 py-1 font-medium">message</th>
                              )}
                            </tr>
                          </thead>
                          <tbody>
                            <tr className="border-t border-border">
                              <td className="px-2 py-1 text-muted-foreground">(submitted time)</td>
                              {includeLogFormat && (
                                <td className="px-2 py-1 text-muted-foreground">(this pattern)</td>
                              )}
                              {orderedIncludedFields.map((f) => (
                                <td key={f} className="px-2 py-1 font-mono">
                                  {sampleTest.groups?.[f] ?? colDefaults[f] ?? ""}
                                </td>
                              ))}
                              {includeMessageColumn && (
                                <td className="px-2 py-1 font-mono">{sampleLine}</td>
                              )}
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        Paste a sample log line above to preview the output row.
                      </p>
                    )}
                  </div>

                  {uniqueFields.length === 0 && (
                    <p className="text-xs text-danger">
                      Pick at least one field to count unique values of, above.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {save.isError && <p className="text-xs text-danger">{(save.error as Error).message}</p>}

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => save.mutate()}
            disabled={save.isPending || !canSave}
            title={
              resolvedSource.index_target_id == null
                ? "Pick the source this search runs against"
                : undefined
            }
          >
            {save.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Check className="h-3.5 w-3.5" />
            )}
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel}>
            <X className="h-3.5 w-3.5" /> Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ── batch runs ──────────────────────────────────────────────────────────────
// Tick several searches, run them all over one shared window — one job each,
// each file named <search>_<job id>_<window>. Every row needs its own source
// because searches are deliberately not tied to a region; "set all" covers the
// common same-region case.

function BatchDialog({
  templates,
  onClose,
  onDone,
}: {
  templates: FilterTemplate[];
  onClose: () => void;
  onDone: () => void;
}) {
  const nowSec = Math.floor(Date.now() / 1000);
  const [tz, setTz] = React.useState<Tz>("UTC");
  const [preset, setPreset] = React.useState<number | "custom">(86400);
  const [customStart, setCustomStart] = React.useState(epochToLocal(nowSec - 86400, "UTC"));
  const [customEnd, setCustomEnd] = React.useState(epochToLocal(nowSec, "UTC"));
  const [preview, setPreview] = React.useState(false);
  // Pre-filled from each search's remembered source — the whole point of
  // saving one. Rows without a remembered source still ask, as before.
  const [indexByTpl, setIndexByTpl] = React.useState<Record<number, number | "">>(() =>
    Object.fromEntries(
      templates
        .filter((t) => t.index_target_id != null)
        .map((t) => [t.id, t.index_target_id as number])
    )
  );
  const [credByTpl, setCredByTpl] = React.useState<Record<number, number | "">>(() =>
    Object.fromEntries(
      templates.filter((t) => t.credential_id != null).map((t) => [t.id, t.credential_id as number])
    )
  );
  const [bulkIndex, setBulkIndex] = React.useState<number | "">("");
  const [created, setCreated] = React.useState<Job[] | null>(null);

  const { data: allIndexes } = useQuery({
    queryKey: ["indexes", ""],
    queryFn: () => listIndexes(),
  });
  const { data: credentials } = useQuery({ queryKey: ["credentials"], queryFn: listCredentials });

  const { start, end } =
    preset === "custom"
      ? { start: localToEpoch(customStart, tz), end: localToEpoch(customEnd, tz) }
      : { start: nowSec - preset, end: nowSec };
  const validRange = end > start;

  function sourceFor(t: FilterTemplate) {
    // A cleared row falls back to the search's remembered source — same rule
    // the API applies, so the dialog never blocks on a search that has one.
    const pickedIdx = indexByTpl[t.id];
    const idx = allIndexes?.find(
      (i) => i.id === (pickedIdx === "" || pickedIdx == null ? t.index_target_id : pickedIdx)
    );
    const pickedCred = credByTpl[t.id];
    const credId =
      pickedCred === "" || pickedCred == null
        ? (t.credential_id ?? idx?.credential_id)
        : Number(pickedCred);
    return { idx, credId: credId ?? null };
  }

  const rowsReady = templates.every((t) => {
    const { idx, credId } = sourceFor(t);
    return idx && credId;
  });

  const run = useMutation({
    mutationFn: () =>
      createBatchJobs({
        items: templates.map((t) => {
          const { idx, credId } = sourceFor(t);
          return {
            template_id: t.id,
            credential_id: Number(credId),
            index_target_id: Number(idx!.id),
            region_code: idx!.region_code,
          };
        }),
        start_epoch: start,
        end_epoch: end,
        is_preview: preview,
      }),
    onSuccess: (jobs) => setCreated(jobs),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-auto bg-background/80 p-4 backdrop-blur-sm">
      <Card className="my-8 w-full max-w-3xl">
        <CardContent className="space-y-5 p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold tracking-tight">
              Run {templates.length} search{templates.length === 1 ? "" : "es"} over one window
            </h2>
            <Button size="icon" variant="ghost" aria-label="Close" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>

          {created ? (
            <div className="space-y-2">
              <p className="text-sm text-success">
                {created.length} job{created.length === 1 ? "" : "s"} queued — files will be named{" "}
                <span className="font-mono">&lt;search&gt;_&lt;job id&gt;_&lt;window&gt;</span>.
              </p>
              <div className="space-y-1">
                {created.map((j) => (
                  <a
                    key={j.id}
                    href={`/jobs/${j.id}`}
                    className="block border border-border px-3 py-1.5 text-sm hover:border-primary"
                  >
                    <span className="font-medium">{j.filter_spec.label}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      · job #{j.id} · {j.status}
                    </span>
                  </a>
                ))}
              </div>
              <div className="flex justify-end gap-2 pt-1">
                <Button size="sm" variant="outline" onClick={onClose}>
                  Stay here
                </Button>
                <Button size="sm" onClick={onDone}>
                  Done
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label>Shared time window ({tz})</Label>
                <div className="flex flex-wrap items-center gap-2">
                  {PRESETS.map((p) => (
                    <Button
                      key={p.label}
                      type="button"
                      size="sm"
                      variant={preset === p.seconds ? "primary" : "outline"}
                      onClick={() => setPreset(p.seconds)}
                    >
                      {p.label}
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
                  {(["UTC", "IST"] as Tz[]).map((z) => (
                    <button
                      key={z}
                      type="button"
                      onClick={() => setTz(z)}
                      className={`border px-3 py-1 text-xs font-semibold ${
                        tz === z
                          ? "border-transparent bg-primary text-primary-foreground"
                          : "border-border text-muted-foreground"
                      }`}
                    >
                      {z}
                    </button>
                  ))}
                </div>
                {preset === "custom" ? (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label>Start ({tz})</Label>
                      <Input
                        type="datetime-local"
                        value={customStart}
                        onChange={(e) => setCustomStart(e.target.value)}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label>End ({tz})</Label>
                      <Input
                        type="datetime-local"
                        value={customEnd}
                        onChange={(e) => setCustomEnd(e.target.value)}
                      />
                    </div>
                  </div>
                ) : null}
                <p className="font-mono text-xs text-muted-foreground">
                  {validRange ? (
                    <>
                      Resolved: {formatEpoch(start)} → {formatEpoch(end)} UTC
                    </>
                  ) : (
                    <span className="text-danger">End must be after start.</span>
                  )}
                </p>
              </div>

              <div className="space-y-2">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="min-w-[220px] flex-1 space-y-1.5">
                    <Label>Set all sources to</Label>
                    <select
                      className={fieldClass}
                      value={bulkIndex}
                      onChange={(e) => {
                        const v = e.target.value ? Number(e.target.value) : "";
                        setBulkIndex(v);
                        if (v !== "") {
                          const next: Record<number, number> = {};
                          for (const t of templates) next[t.id] = v;
                          setIndexByTpl(next);
                        }
                      }}
                    >
                      <option value="">Choose once for every row…</option>
                      {allIndexes?.map((i) => (
                        <option key={i.id} value={i.id}>
                          {i.name} · {i.region_code}
                          {i.credential_label ? ` · ${i.credential_label}` : " · no credential"}
                        </option>
                      ))}
                    </select>
                  </div>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={preview}
                      onChange={(e) => setPreview(e.target.checked)}
                      className="h-4 w-4"
                    />
                    Preview only (newest chunks, 100 rows each)
                  </label>
                </div>

                <div className="space-y-1.5">
                  {templates.map((t) => {
                    const { idx, credId } = sourceFor(t);
                    const needsCred = idx && !idx.credential_id && !credId;
                    return (
                      <div
                        key={t.id}
                        className="grid grid-cols-1 gap-2 border border-border p-2 sm:grid-cols-[1fr_1fr_auto]"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{t.name}</p>
                          <p className="font-mono text-xs text-muted-foreground">
                            {idx ? `${idx.region_code} · ${idx.name}` : "no source picked"}
                          </p>
                        </div>
                        <select
                          className={fieldClass}
                          value={indexByTpl[t.id] ?? t.index_target_id ?? ""}
                          onChange={(e) =>
                            setIndexByTpl((prev) => ({
                              ...prev,
                              [t.id]: e.target.value ? Number(e.target.value) : "",
                            }))
                          }
                          aria-label={`Source for ${t.name}`}
                        >
                          <option value="">Pick a source…</option>
                          {allIndexes?.map((i) => (
                            <option key={i.id} value={i.id}>
                              {i.name} · {i.region_code}
                            </option>
                          ))}
                        </select>
                        {needsCred ? (
                          <select
                            className={fieldClass}
                            value={credByTpl[t.id] ?? t.credential_id ?? ""}
                            onChange={(e) =>
                              setCredByTpl((prev) => ({
                                ...prev,
                                [t.id]: e.target.value ? Number(e.target.value) : "",
                              }))
                            }
                            aria-label={`Credential for ${t.name}`}
                          >
                            <option value="">Credential…</option>
                            {credentials?.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.label} ({c.org_slug})
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="self-center font-mono text-xs text-muted-foreground">
                            {idx?.credential_label ?? ""}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {run.isError && <p className="text-xs text-danger">{(run.error as Error).message}</p>}
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  disabled={!validRange || !rowsReady || run.isPending}
                  onClick={() => run.mutate()}
                  title={
                    rowsReady
                      ? `Queue ${templates.length} jobs`
                      : "Every row needs a source with a credential"
                  }
                >
                  {run.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Run {templates.length} job{templates.length === 1 ? "" : "s"}
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
