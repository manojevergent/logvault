"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Bookmark, ChevronDown, Code2, Loader2, Save, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { FieldGroup, Input, Label, fieldClass } from "@/components/ui/input";
import { exactPhraseRegex } from "@/lib/aggregation";
import {
  Comparison,
  ComparisonInput,
  ComparisonValueMode,
  Last9FilterSpec,
  createComparison,
  listCredentials,
  listIndexes,
  listNewRelicCredentials,
  listTemplates,
  updateComparison,
} from "@/lib/api";

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function splitIds(value: string): string[] {
  return value
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

const ESC = (value: string) => value.replace(/([.^$*+?()[\]{}|\\])/g, "\\$1");

/** Mirrors the API/worker phrase builder, so the preview is the real pipeline. */
function buildPipeline(spec: Last9FilterSpec): Record<string, unknown>[] | null {
  const clauses: unknown[] = [...spec.phrases, ...spec.message_types].map((phrase) => ({
    $contains: ["Body", phrase],
  }));
  for (const phrase of spec.exact_phrases ?? []) {
    clauses.push({ $regex: ["Body", exactPhraseRegex(phrase)] });
  }
  if (spec.ids.length) {
    clauses.push({ $regex: ["Body", spec.ids.map(ESC).join("|")] });
  }
  if (clauses.length === 0) return null;
  return [{ query: { $and: clauses }, type: "filter" }];
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-border first:border-t-0">
      <div className="grid gap-4 py-5 sm:grid-cols-[168px_minmax(0,1fr)]">
        <div className="space-y-1">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {title}
          </h3>
          {description && (
            <p className="text-xs leading-relaxed text-muted-foreground/80">{description}</p>
          )}
        </div>
        <div className="space-y-4">{children}</div>
      </div>
    </section>
  );
}

const VALUE_MODES: { value: ComparisonValueMode; label: string; hint: string }[] = [
  {
    value: "sum",
    label: "Counts — sum every bucket",
    hint: "Best for count(*): totals and parity are exact.",
  },
  {
    value: "avg",
    label: "Gauge — average buckets",
    hint: "For average(duration) and similar gauges.",
  },
  { value: "max", label: "Gauge — maximum bucket", hint: "For peaks such as max(duration)." },
  { value: "min", label: "Gauge — minimum bucket", hint: "For troughs such as min(throughput)." },
  { value: "last", label: "Gauge — latest bucket", hint: "For the most recent value of a gauge." },
];

export function ComparisonForm({
  initial,
  onSaved,
  onCancel,
}: {
  initial?: Comparison;
  onSaved: (comparison: Comparison) => void;
  onCancel?: () => void;
}) {
  const { data: indexes } = useQuery({
    queryKey: ["indexes", ""],
    queryFn: () => listIndexes(),
  });
  const { data: credentials } = useQuery({
    queryKey: ["credentials"],
    queryFn: listCredentials,
  });
  const { data: nrCredentials } = useQuery({
    queryKey: ["newrelic-credentials"],
    queryFn: listNewRelicCredentials,
  });
  const { data: templates } = useQuery({
    queryKey: ["templates"],
    queryFn: listTemplates,
  });

  const spec = initial?.last9_filter_spec;
  const initialGenerated = spec ? buildPipeline(spec) : null;
  // Builder mode is only safe when the saved pipeline is exactly what the
  // builder would regenerate. A hand-edited pipeline (extra parse/aggregate
  // stages) opens in JSON mode so saving the form cannot silently drop it.
  const initialPipelineMode =
    Boolean(initial) &&
    (!initialGenerated || !samePipeline(initial?.last9_pipeline ?? [], initialGenerated));
  const [name, setName] = React.useState(initial?.name ?? "");
  const [description, setDescription] = React.useState(initial?.description ?? "");
  const [indexId, setIndexId] = React.useState<number | "">(initial?.last9_index_target_id ?? "");
  const [credentialId, setCredentialId] = React.useState<number | "">(
    initial?.last9_credential_id ?? ""
  );
  const [phrasesText, setPhrasesText] = React.useState((spec?.phrases ?? []).join("\n"));
  const [exactText, setExactText] = React.useState((spec?.exact_phrases ?? []).join("\n"));
  const [idsText, setIdsText] = React.useState((spec?.ids ?? []).join("\n"));
  const [messageTypesText, setMessageTypesText] = React.useState(
    (spec?.message_types ?? []).join("\n")
  );
  const [pipelineMode, setPipelineMode] = React.useState(initialPipelineMode);
  const [pipelineText, setPipelineText] = React.useState(
    initial?.last9_pipeline ? JSON.stringify(initial.last9_pipeline, null, 2) : ""
  );
  const [nrCredentialId, setNrCredentialId] = React.useState<number | "">(
    initial?.nr_credential_id ?? ""
  );
  const [nrql, setNrql] = React.useState(
    initial?.nrql ?? "SELECT count(*) FROM Log\nWHERE service.name = 'my-service'"
  );
  const [valueMode, setValueMode] = React.useState<ComparisonValueMode>(
    initial?.nr_value_mode ?? "sum"
  );
  const [valueField, setValueField] = React.useState(initial?.nr_value_field ?? "");
  const [bucketSeconds, setBucketSeconds] = React.useState(
    initial?.bucket_seconds ? String(initial.bucket_seconds) : ""
  );
  const [templateId, setTemplateId] = React.useState<number | "">("");
  const [error, setError] = React.useState<string | null>(null);

  const selectedIndex = indexes?.find((idx) => idx.id === indexId);
  const effectiveCredentialId: number | "" = selectedIndex?.credential_id ?? credentialId;

  const filterSpec: Last9FilterSpec = React.useMemo(
    () => ({
      phrases: splitLines(phrasesText),
      ids: splitIds(idsText),
      exact_phrases: splitLines(exactText),
      message_types: splitLines(messageTypesText),
    }),
    [phrasesText, idsText, exactText, messageTypesText]
  );

  const generatedPipeline = React.useMemo(() => buildPipeline(filterSpec), [filterSpec]);
  const previewPipeline = pipelineMode ? safeParsePipeline(pipelineText) : generatedPipeline;

  function applyTemplate(id: number) {
    const template = templates?.find((item) => item.id === id);
    if (!template) return;
    setPhrasesText(template.phrases.join("\n"));
    setExactText((template.exact_phrases ?? []).join("\n"));
    setIdsText(template.ids.join("\n"));
    setMessageTypesText(template.message_types.join("\n"));
    if (!name.trim()) setName(template.name);
    setPipelineMode(false);
    setTemplateId(id);
  }

  const save = useMutation({
    mutationFn: () => {
      let pipeline: Record<string, unknown>[] | null;
      if (pipelineMode) {
        pipeline = safeParsePipeline(pipelineText);
        if (!pipeline || pipeline.length === 0) {
          throw new Error("Pipeline JSON must be a non-empty array of stage objects");
        }
      } else {
        pipeline = generatedPipeline;
        if (!pipeline) {
          throw new Error("Add at least one phrase, exact phrase or ID");
        }
      }
      if (!name.trim()) throw new Error("Name is required");
      if (indexId === "") throw new Error("Pick a Last9 index");
      if (effectiveCredentialId === "") throw new Error("Pick a Last9 credential");
      if (nrCredentialId === "") throw new Error("Pick a New Relic connection");
      if (!nrql.trim()) throw new Error("NRQL query is required");
      if (!nrql.toLowerCase().includes("from")) {
        throw new Error("NRQL must include a FROM clause");
      }

      const body: ComparisonInput = {
        name: name.trim(),
        description: description.trim(),
        last9_index_target_id: Number(indexId),
        last9_credential_id: Number(effectiveCredentialId),
        last9_filter_spec: pipelineMode ? null : filterSpec,
        last9_pipeline: pipeline,
        nr_credential_id: Number(nrCredentialId),
        nrql: nrql.trim(),
        nr_value_mode: valueMode,
        nr_value_field: valueField.trim() || null,
        bucket_seconds: bucketSeconds.trim() ? Number(bucketSeconds) : null,
      };
      return initial ? updateComparison(initial.id, body) : createComparison(body);
    },
    onSuccess: onSaved,
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="border border-border bg-card">
      <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold">
            {initial ? "Edit comparison" : "New comparison"}
          </h2>
          <p className="text-xs text-muted-foreground">
            Save the Last9 source, its filter, and the New Relic NRQL query once. Run it any time
            over a chosen window.
          </p>
        </div>
        {onCancel && (
          <Button variant="ghost" size="icon" onClick={onCancel} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      <div className="px-5">
        <Section title="Identity" description="How this comparison appears in the list.">
          <div className="grid gap-4 sm:grid-cols-2">
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>
                  Name <span className="text-danger">*</span>
                </Label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Checkout errors — NR vs Last9"
                />
              </div>
            </FieldGroup>
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>Description</Label>
                <Input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What this comparison validates"
                />
              </div>
            </FieldGroup>
          </div>
        </Section>

        <Section
          title="Last9 side"
          description="Pick a source profile, then describe the logs to count. The query runs against the index's region and credential."
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>
                  Source / index <span className="text-danger">*</span>
                </Label>
                <select
                  className={fieldClass}
                  value={indexId}
                  onChange={(e) => {
                    const picked = indexes?.find((idx) => idx.id === Number(e.target.value));
                    setIndexId(e.target.value === "" ? "" : Number(e.target.value));
                    if (picked?.credential_id) setCredentialId(picked.credential_id);
                  }}
                >
                  <option value="">Select an index…</option>
                  {indexes?.map((idx) => (
                    <option key={idx.id} value={idx.id}>
                      {idx.name} · {idx.region_code}
                      {idx.credential_label ? ` · ${idx.credential_label}` : ""}
                    </option>
                  ))}
                </select>
                {selectedIndex && (
                  <p className="text-[11px] text-muted-foreground">
                    {selectedIndex.region_code} · index{" "}
                    <span className="font-mono">
                      {selectedIndex.physical_index || selectedIndex.full_index_string || "Default"}
                    </span>
                  </p>
                )}
              </div>
            </FieldGroup>
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>Credential</Label>
                <select
                  className={fieldClass}
                  value={effectiveCredentialId}
                  onChange={(e) =>
                    setCredentialId(e.target.value === "" ? "" : Number(e.target.value))
                  }
                  disabled={Boolean(selectedIndex?.credential_id)}
                >
                  <option value="">Select a credential…</option>
                  {credentials?.map((cred) => (
                    <option key={cred.id} value={cred.id}>
                      {cred.label} · {cred.org_slug}
                    </option>
                  ))}
                </select>
                {selectedIndex?.credential_id && (
                  <p className="text-[11px] text-muted-foreground">
                    Inherited from the source profile.
                  </p>
                )}
              </div>
            </FieldGroup>
          </div>

          <div className="flex flex-wrap items-end gap-3 border border-border bg-muted/30 px-3 py-2.5">
            <div className="min-w-[220px] flex-1 space-y-1.5">
              <Label>Load a saved search</Label>
              <select
                className={fieldClass}
                value={templateId}
                onChange={(e) =>
                  e.target.value === "" ? setTemplateId("") : applyTemplate(Number(e.target.value))
                }
              >
                <option value="">Start from scratch</option>
                {templates?.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name}
                  </option>
                ))}
              </select>
            </div>
            <p className="flex items-center gap-1.5 pb-1 text-xs text-muted-foreground">
              <Bookmark className="h-3.5 w-3.5" />
              Copies the phrases and IDs into this comparison.
            </p>
          </div>

          {!pipelineMode ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <FieldGroup>
                <div className="space-y-1.5">
                  <Label>Phrases (one per line)</Label>
                  <textarea
                    className={`${fieldClass} h-24 py-2`}
                    value={phrasesText}
                    onChange={(e) => setPhrasesText(e.target.value)}
                    placeholder={"getStatusCode\nAPI : 502"}
                  />
                  <p className="text-[11px] text-muted-foreground">
                    Matched with Last9&rsquo;s word-based{" "}
                    <span className="font-mono">$contains</span>.
                  </p>
                </div>
              </FieldGroup>
              <FieldGroup>
                <div className="space-y-1.5">
                  <Label>Exact phrases (adjacent words)</Label>
                  <textarea
                    className={`${fieldClass} h-24 py-2`}
                    value={exactText}
                    onChange={(e) => setExactText(e.target.value)}
                    placeholder={"API : 502"}
                  />
                  <p className="text-[11px] text-muted-foreground">
                    Sent as a regex, so the tokens must appear together.
                  </p>
                </div>
              </FieldGroup>
              <FieldGroup>
                <div className="space-y-1.5">
                  <Label>IDs (one per line or comma-separated)</Label>
                  <textarea
                    className={`${fieldClass} h-24 py-2`}
                    value={idsText}
                    onChange={(e) => setIdsText(e.target.value)}
                    placeholder={"220815144118207\n230702032635917346"}
                  />
                </div>
              </FieldGroup>
              <FieldGroup>
                <div className="space-y-1.5">
                  <Label>Message types / extra phrases</Label>
                  <textarea
                    className={`${fieldClass} h-24 py-2`}
                    value={messageTypesText}
                    onChange={(e) => setMessageTypesText(e.target.value)}
                    placeholder={"INVOICE\nTRACK"}
                  />
                </div>
              </FieldGroup>
            </div>
          ) : (
            <div className="space-y-1.5">
              <Label>Last9 pipeline JSON</Label>
              <textarea
                className={`${fieldClass} h-48 py-2 font-mono text-xs`}
                value={pipelineText}
                onChange={(e) => setPipelineText(e.target.value)}
                placeholder='[{"type":"filter","query":{"$and":[{"$contains":["Body","error"]}]}}]'
                spellCheck={false}
              />
              <p className="text-[11px] text-muted-foreground">
                Full LogJSON pipeline. Use filter, parse, aggregate, or window_aggregate stages.
              </p>
            </div>
          )}

          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              className="flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
              onClick={() => {
                if (!pipelineMode) {
                  setPipelineText(JSON.stringify(generatedPipeline ?? [], null, 2));
                  setPipelineMode(true);
                } else {
                  setPipelineMode(false);
                }
              }}
            >
              <Code2 className="h-3.5 w-3.5" />
              {pipelineMode ? "Back to filter builder" : "Edit pipeline JSON"}
            </button>
            <details className="group">
              <summary className="flex cursor-pointer list-none items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
                Effective pipeline
              </summary>
              <pre className="mt-2 max-h-56 overflow-auto border border-border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed">
                {previewPipeline
                  ? JSON.stringify(previewPipeline, null, 2)
                  : pipelineMode
                    ? "Invalid pipeline JSON — fix it before saving."
                    : "Add at least one phrase, exact phrase or ID."}
              </pre>
            </details>
          </div>
        </Section>

        <Section
          title="New Relic side"
          description="The saved NRQL is pinned to the selected window on every run. A TIMESERIES in the query sets the default bucket; otherwise a bucket is chosen automatically."
        >
          <FieldGroup>
            <div className="space-y-1.5">
              <Label>
                New Relic connection <span className="text-danger">*</span>
              </Label>
              <select
                className={fieldClass}
                value={nrCredentialId}
                onChange={(e) =>
                  setNrCredentialId(e.target.value === "" ? "" : Number(e.target.value))
                }
              >
                <option value="">Select a connection…</option>
                {nrCredentials?.map((cred) => (
                  <option key={cred.id} value={cred.id}>
                    {cred.label} · account {cred.account_id} · {cred.region.toUpperCase()}
                  </option>
                ))}
              </select>
              {nrCredentials && nrCredentials.length === 0 && (
                <p className="text-xs text-warning">
                  No New Relic connections yet.{" "}
                  <Link href="/new-relic" className="text-primary hover:underline">
                    Add one first
                  </Link>
                  .
                </p>
              )}
            </div>
          </FieldGroup>

          <FieldGroup>
            <div className="space-y-1.5">
              <Label>
                NRQL query <span className="text-danger">*</span>
              </Label>
              <textarea
                className={`${fieldClass} h-36 py-2 font-mono text-xs`}
                value={nrql}
                onChange={(e) => setNrql(e.target.value)}
                spellCheck={false}
              />
              <p className="text-[11px] text-muted-foreground">
                Example:{" "}
                <span className="font-mono">
                  SELECT count(*) FROM Log WHERE service.name = &apos;checkout&apos;
                </span>
                . The comparison supplies <span className="font-mono">SINCE</span>,{" "}
                <span className="font-mono">UNTIL</span> and{" "}
                <span className="font-mono">TIMESERIES</span> automatically.
              </p>
            </div>
          </FieldGroup>

          <div className="grid gap-4 sm:grid-cols-3">
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>Numeric value</Label>
                <select
                  className={fieldClass}
                  value={valueMode}
                  onChange={(e) => setValueMode(e.target.value as ComparisonValueMode)}
                >
                  {VALUE_MODES.map((mode) => (
                    <option key={mode.value} value={mode.value}>
                      {mode.label}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-muted-foreground">
                  {VALUE_MODES.find((mode) => mode.value === valueMode)?.hint}
                </p>
              </div>
            </FieldGroup>
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>Numeric column (optional)</Label>
                <Input
                  value={valueField}
                  onChange={(e) => setValueField(e.target.value)}
                  placeholder="auto — e.g. count"
                />
                <p className="text-[11px] text-muted-foreground">
                  Set this when the query returns more than one numeric column.
                </p>
              </div>
            </FieldGroup>
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>Default bucket seconds (optional)</Label>
                <Input
                  value={bucketSeconds}
                  onChange={(e) => setBucketSeconds(e.target.value.replace(/[^0-9]/g, ""))}
                  placeholder="auto"
                  inputMode="numeric"
                />
                <p className="text-[11px] text-muted-foreground">
                  Blank uses the NRQL TIMESERIES, or ~60 buckets for the window.
                </p>
              </div>
            </FieldGroup>
          </div>
        </Section>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-4">
        <div>
          {error && <p className="text-xs text-danger">{error}</p>}
          {!error && (
            <p className="text-xs text-muted-foreground">
              Both providers run over the same half-open window when you press Run.
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {onCancel && (
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          )}
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            {initial ? "Save changes" : "Save comparison"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function safeParsePipeline(text: string): Record<string, unknown>[] | null {
  if (!text.trim()) return null;
  try {
    const parsed = JSON.parse(text);
    if (!Array.isArray(parsed)) return null;
    return parsed.every((item) => item && typeof item === "object") ? parsed : null;
  } catch {
    return null;
  }
}

function samePipeline(
  left: Record<string, unknown>[],
  right: Record<string, unknown>[] | null
): boolean {
  return Boolean(right) && JSON.stringify(left) === JSON.stringify(right);
}
