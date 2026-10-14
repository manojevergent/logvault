"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, Check, Loader2, Pencil, Trash2, X } from "lucide-react";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FieldGroup, Input, Label, fieldClass } from "@/components/ui/input";
import { FilterTemplate, deleteTemplate, listLogFormats, listTemplates, updateTemplate } from "@/lib/api";
import { OutputColumnsEditor, orderBySeq, suggestUniformLayout } from "@/components/output-columns-editor";
import { extractGroupNames } from "@/lib/aggregation";

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

  const refresh = () => qc.invalidateQueries({ queryKey: ["templates"] });

  return (
    <div className="mx-auto max-w-5xl animate-fade-in px-6 py-8">
      <div className="space-y-1.5 pb-6">
        <h1 className="text-xl font-semibold tracking-tight">Saved searches</h1>
        <p className="text-sm text-muted-foreground">
          Reusable phrase/ID/message-type filters, saved from the New Extraction wizard or a
          schedule. Not tied to any credential, region, or index — load one into any job.
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
            Build a filter in the New Extraction wizard, then click &ldquo;Save as search&rdquo;
            to reuse it later.
          </p>
        </div>
      )}

      <div className="space-y-3">
        {templates?.map((t) => (
          <TemplateCard key={t.id} tpl={t} onChange={refresh} />
        ))}
      </div>
    </div>
  );
}

function TemplateCard({ tpl, onChange }: { tpl: FilterTemplate; onChange: () => void }) {
  const [editing, setEditing] = React.useState(false);
  const del = useMutation({ mutationFn: () => deleteTemplate(tpl.id), onSuccess: onChange });

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
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="font-medium">{tpl.name}</span>
            {tpl.aggregation?.enabled && <Badge tone="info">parse & aggregate</Badge>}
            {tpl.customer && <Badge tone="neutral">{tpl.customer}</Badge>}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {[...tpl.phrases, ...tpl.message_types].map((p, i) => (
              <Badge key={`p${i}`} tone="info">
                {p}
              </Badge>
            ))}
            {tpl.ids.length > 0 && (
              <Badge tone="neutral">
                {tpl.ids.length} ID{tpl.ids.length === 1 ? "" : "s"}
              </Badge>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            aria-label={`Edit ${tpl.name}`}
            onClick={() => setEditing(true)}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label={`Delete ${tpl.name}`}
            onClick={() => del.mutate()}
            disabled={del.isPending}
          >
            <Trash2 className="h-4 w-4 text-danger" />
          </Button>
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
  const [includedFieldsOverride, setIncludedFieldsOverride] = React.useState<Set<
    string
  > | null>(agg?.raw_columns && agg.raw_columns.length > 0 ? new Set(agg.raw_columns) : null);
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
        message_types: splitCsv(messageTypesText),
        customer: customer.trim(),
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
          <Field label="Customer folder (optional)">
            <Input value={customer} onChange={(e) => setCustomer(e.target.value)} />
          </Field>
          <Field label="Phrases (comma-separated)" className="sm:col-span-2">
            <Input value={phrasesText} onChange={(e) => setPhrasesText(e.target.value)} />
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
              Left off: the raw export is exactly <span className="font-mono">timestamp_utc</span>{" "}
              + <span className="font-mono">message</span> — no parsing, nothing else added.
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
          <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending || !canSave}>
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
