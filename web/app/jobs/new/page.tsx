"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, Check, Loader2, Upload, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldGroup, Input, Label, fieldClass } from "@/components/ui/input";
import { OutputColumnsEditor, orderBySeq, suggestUniformLayout } from "@/components/output-columns-editor";
import { TemplatePicker } from "@/components/template-picker";
import { extractGroupNames } from "@/lib/aggregation";
import {
  FilterTemplate,
  createJob,
  createTemplate,
  getJob,
  listCredentials,
  listIndexes,
  listLogFormats,
  listRegions,
  listTemplates,
  updateTemplate,
} from "@/lib/api";
import { PRESETS, Tz, epochToLocal, formatEpoch, localToEpoch } from "@/lib/time";
import { SavedRange, getRecentRanges, saveRange } from "@/lib/timestamps";

// Each word is matched independently (like Last9's "contains all words"), not
// as one literal substring — applied both to freshly-typed input and to
// phrases carried over from an older job via Clone.
function splitWords(s: string): string[] {
  return s.trim().split(/\s+/).filter(Boolean);
}

function splitFieldNames(s: string): string[] {
  return s
    .split(",")
    .map((f) => f.trim())
    .filter(Boolean);
}


// The one use case this shipped for: unique SPID (and tracker ID) counts per
// API + BU. Prefilled by "Load example" as a starting point — fully editable.
// spid is \S+, NOT \d+: SPAccountId appears as a plain number, a hex string and
// a UUID. \d+ matched only the numeric form and silently dropped ~46% of rows —
// the counts still looked reasonable, just 42% low.
const EXAMPLE_REGEX =
  "^\\s*(?<trackerid>AHA-\\d-[a-f0-9-]+)\\s+-\\s+ClassName\\s+(?<api>\\w+)\\s+SPAccountId\\s+(?<spid>\\S+)\\s+in\\s+BU\\s+(?<BU>.*?)\\s+API User.*$";
const EXAMPLE_SAMPLE_LINE =
  "AHA-1-6a907c43-522740b7206c8b03224bd10d - ClassName  CGetEntitlementsCommand SPAccountId  220815144118207 in BU  AHA INDIA API User ahaapiuser";

function saveLastUsed(credentialId: number, region: string) {
  try {
    localStorage.setItem("logvault:last_source", JSON.stringify({ credentialId, region }));
  } catch {}
}
function getLastUsed(): { credentialId: number; region: string } | null {
  try {
    const s = localStorage.getItem("logvault:last_source");
    return s ? JSON.parse(s) : null;
  } catch {
    return null;
  }
}
function fmtEstimate(chunks: number): string {
  const lo = Math.max(1, Math.ceil(chunks * 0.5));
  const hi = Math.ceil(chunks * 1.5);
  return hi >= 120 ? `${Math.ceil(lo / 60)}–${Math.ceil(hi / 60)} hr` : `${lo}–${hi} min`;
}

// Mirrors the backend pipeline builder for the preview panel (§2.4–2.7).
// Always wraps in $and — bare operators at query root return 0 rows silently.
const esc = (s: string) => s.replace(/([.^$*+?()[\]{}|\\])/g, "\\$1");
function buildPipeline(phrases: string[], ids: string[], messageTypes: string[]) {
  const allPhrases = [...phrases, ...messageTypes];
  const clauses: unknown[] = allPhrases.map((p) => ({ $contains: ["Body", p] }));
  if (ids.length) clauses.push({ $regex: ["Body", ids.map(esc).join("|")] });
  if (clauses.length === 0) return null;
  return [{ query: { $and: clauses }, type: "filter" }];
}

export default function NewJobPage() {
  const router = useRouter();
  const { data: credentials } = useQuery({ queryKey: ["credentials"], queryFn: listCredentials });
  const { data: regions } = useQuery({ queryKey: ["regions"], queryFn: listRegions });

  const [credentialId, setCredentialId] = React.useState<number | "">("");
  const [region, setRegion] = React.useState("");
  const [indexId, setIndexId] = React.useState<number | "">("");

  // Unfiltered: the source picker is the one control, so it lists every
  // profile and the region comes from whichever is chosen.
  const { data: allIndexes } = useQuery({ queryKey: ["indexes", ""], queryFn: () => listIndexes() });
  const selectedIndex = allIndexes?.find((i) => i.id === indexId);
  // The source profile owns the credential — derive it rather than trust the
  // stored one. A clone (or the last-used prefill) otherwise carries a
  // credential id that was valid when the job ran and has since been deleted,
  // which the worker only discovers an hour in as "missing credential/index".
  const effectiveCredentialId = selectedIndex?.credential_id ?? credentialId;

  // UTC by default: the application timestamps its logs in UTC, so a range
  // typed in UTC is the one that lines up with what's actually in the index.
  const [tz, setTz] = React.useState<Tz>("UTC");
  const [preset, setPreset] = React.useState<number | "custom">(3600);
  const nowSec = Math.floor(Date.now() / 1000);
  const [customStart, setCustomStart] = React.useState(epochToLocal(nowSec - 3600, "UTC"));
  const [customEnd, setCustomEnd] = React.useState(epochToLocal(nowSec, "UTC"));

  const [phrases, setPhrases] = React.useState<string[]>([]);
  const [phraseInput, setPhraseInput] = React.useState("");
  const [idsText, setIdsText] = React.useState("");
  const [messageTypesText, setMessageTypesText] = React.useState("");

  // Typed-but-not-yet-Entered words used to be dropped on the floor: the job ran
  // without them, against a far larger set, and nobody found out until hours
  // later. Anything in the box counts — it's committed on blur, and folded in
  // here so a click straight from the box to "Run extraction" can't lose it.
  const pendingWords = React.useMemo(() => splitWords(phraseInput), [phraseInput]);
  const effectivePhrases = React.useMemo(
    () => [...phrases, ...pendingWords],
    [phrases, pendingWords]
  );
  function commitPhraseInput() {
    if (pendingWords.length === 0) return;
    setPhrases((prev) => [...prev, ...pendingWords]);
    setPhraseInput("");
  }

  // "Save the search": named phrase/ID/message-type sets, reusable across jobs
  // and schedules.
  const qc = useQueryClient();
  const { data: templates } = useQuery({ queryKey: ["templates"], queryFn: listTemplates });
  const [templateId, setTemplateId] = React.useState<number | "">("");
  const [savingTemplate, setSavingTemplate] = React.useState(false);
  const [templateName, setTemplateName] = React.useState("");
  // Mandatory search name / extraction label: every extraction requires a name
  // so extracted files are always identifiable on disk and downloads.
  const [searchLabel, setSearchLabel] = React.useState("");
  // Groups this job's output files under exports/<customer>/. Comes from the
  // saved search when one is loaded, and is editable for a one-off run.
  const [customer, setCustomer] = React.useState("");

  function applyTemplate(tpl: FilterTemplate) {
    setSearchLabel(tpl.name);
    setPhrases(tpl.phrases);
    setIdsText(tpl.ids.join("\n"));
    setMessageTypesText(tpl.message_types.join("\n"));
    // The regex is the laborious part of a search, so a saved one comes back
    // with it. A template without a parse config just switches the section off
    // rather than wiping whatever is typed there.
    const agg = tpl.aggregation;
    setAggEnabled(Boolean(agg?.enabled));
    if (agg?.enabled) {
      setAggRegex(agg.regex);
      setUseLibrary(Boolean(agg.use_library));
      setGroupByText(agg.group_by.join(", "));
      setUniqueFieldsText(agg.unique_fields.join(", "));
      setSkipRawOutput(Boolean(agg.skip_raw_output));
      // An explicit column list this search already saved overrides the
      // default (group by + unique fields); otherwise let the checklist fall
      // back to that default, same as a search that's never touched it.
      setIncludedFieldsOverride(
        agg.raw_columns && agg.raw_columns.length > 0 ? new Set(agg.raw_columns) : null
      );
      // Sequence = saved column order; labels/defaults/timestamp ride along.
      const seq: Record<string, number> = {};
      (agg.raw_columns ?? []).forEach((f, i) => {
        seq[f] = i + 1;
      });
      setColSeq(seq);
      setColLabels({ ...(agg.column_labels ?? {}) });
      setColDefaults({ ...(agg.raw_column_defaults ?? {}) });
      setTimestampHeader(agg.timestamp_column ?? "timestamp_utc");
      setIncludeLogFormat(agg.include_log_format ?? true);
      setIncludeMessageColumn(agg.include_message ?? true);
    } else {
      setIncludedFieldsOverride(null);
      setColSeq({});
      setColLabels({});
      setColDefaults({});
      setTimestampHeader("timestamp_utc");
      setIncludeLogFormat(true);
      setIncludeMessageColumn(true);
    }
  }

  const saveTemplate = useMutation({
    mutationFn: (name: string) =>
      createTemplate({
        name,
        phrases: effectivePhrases,
        ids,
        message_types: messageTypes,
        customer,
        // Remember where this search was built, so batch runs and future
        // loads come pre-filled with its source.
        credential_id: effectiveCredentialId === "" ? null : Number(effectiveCredentialId),
        region_code: region || null,
        index_target_id: indexId === "" ? null : Number(indexId),
        aggregation: aggEnabled
          ? {
              enabled: true,
              regex: useLibrary ? "" : aggRegex,
              use_library: useLibrary,
              group_by: groupBy,
              unique_fields: uniqueFields,
              skip_raw_output: skipRawOutput,
              raw_columns: rawColumns,
              include_log_format: includeLogFormat,
              include_message: includeMessageColumn,
              column_labels: columnLabels,
              raw_column_defaults: columnDefaults,
              timestamp_column: timestampHeader.trim() || "timestamp_utc",
            }
          : null,
      }),
    onSuccess: (tpl) => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      setTemplateId(tpl.id);
      setSavingTemplate(false);
      setTemplateName("");
    },
  });

  // Saves straight back onto the search that's loaded — the point of
  // validating the output here is not having to come back to Filter and
  // re-save under the same name after every tweak.
  const updateExistingTemplate = useMutation({
    mutationFn: () =>
      updateTemplate(Number(templateId), {
        name: templates?.find((t) => t.id === templateId)?.name ?? "",
        phrases: effectivePhrases,
        ids,
        message_types: messageTypes,
        customer,
        credential_id: effectiveCredentialId === "" ? null : Number(effectiveCredentialId),
        region_code: region || null,
        index_target_id: indexId === "" ? null : Number(indexId),
        aggregation: aggEnabled
          ? {
              enabled: true,
              regex: useLibrary ? "" : aggRegex,
              use_library: useLibrary,
              group_by: groupBy,
              unique_fields: uniqueFields,
              skip_raw_output: skipRawOutput,
              raw_columns: rawColumns,
              include_log_format: includeLogFormat,
              include_message: includeMessageColumn,
              column_labels: columnLabels,
              raw_column_defaults: columnDefaults,
              timestamp_column: timestampHeader.trim() || "timestamp_utc",
            }
          : null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["templates"] }),
  });

  const [chunkHours, setChunkHours] = React.useState(1);
  const [batchSize, setBatchSize] = React.useState(100);
  const [format, setFormat] = React.useState<"csv" | "jsonl" | "bigquery">("csv");

  // Parse & aggregate: extract named fields from each matched line and count
  // DISTINCT values of one or more of them, grouped by the others.
  const [aggEnabled, setAggEnabled] = React.useState(false);
  const [aggRegex, setAggRegex] = React.useState("");
  const [groupByText, setGroupByText] = React.useState("");
  const [uniqueFieldsText, setUniqueFieldsText] = React.useState("");
  const [skipRawOutput, setSkipRawOutput] = React.useState(false);
  // Use every enabled pattern in the Log Formats library instead of one regex
  // typed here — the only workable option once there are many log shapes.
  const [useLibrary, setUseLibrary] = React.useState(false);
  const [sampleLine, setSampleLine] = React.useState("");
  // Which parsed fields land in the output file, independent of group_by/
  // unique_fields (those still drive the grouping either way). null = no
  // manual choice yet, so the checklist falls back to the implicit default
  // (group_by ∪ unique_fields) — exactly today's behavior, unchanged.
  const [includedFieldsOverride, setIncludedFieldsOverride] = React.useState<Set<
    string
  > | null>(null);
  // Per-field output sequence (1-based), uniform CSV header, and empty-value
  // default — the "number the columns" control for uniform extracts.
  const [colSeq, setColSeq] = React.useState<Record<string, number>>({});
  const [colLabels, setColLabels] = React.useState<Record<string, string>>({});
  const [colDefaults, setColDefaults] = React.useState<Record<string, string>>({});
  const [timestampHeader, setTimestampHeader] = React.useState("timestamp_utc");
  // log_format (which pattern matched) and message (the raw line) are the two
  // columns that AREN'T a regex field — kept as their own toggles rather than
  // folded into the checklist above, since nothing to check them against
  // exists until a regex is typed.
  const [includeLogFormat, setIncludeLogFormat] = React.useState(true);
  const [includeMessageColumn, setIncludeMessageColumn] = React.useState(true);

  const groupBy = React.useMemo(() => splitFieldNames(groupByText), [groupByText]);
  const uniqueFields = React.useMemo(() => splitFieldNames(uniqueFieldsText), [uniqueFieldsText]);

  // Library mode: the fields are the union of every enabled format's named
  // groups, so the sequence editor works there too.
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
  const regexFields = React.useMemo(
    () => (useLibrary ? libraryFields : extractGroupNames(aggRegex)),
    [aggRegex, useLibrary, libraryFields]
  );
  const defaultIncludedFields = React.useMemo(
    () => new Set([...groupBy, ...uniqueFields]),
    [groupBy, uniqueFields]
  );
  const includedFields = includedFieldsOverride ?? defaultIncludedFields;
  // Sequence-number order, not click order, so the output column order is
  // exactly what the user numbered — falling back to definition order for
  // fields with no number yet.
  const orderedIncludedFields = React.useMemo(
    () => orderBySeq(regexFields, colSeq).filter((f) => includedFields.has(f)),
    [regexFields, colSeq, includedFields]
  );
  // Uniform header per included field (only when renamed), and non-blank
  // empty-value defaults.
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
    // A uniform extract is parsed fields only — drop the synthetic columns.
    setIncludeLogFormat(false);
    setIncludeMessageColumn(false);
  }
  // Sent as an explicit list whenever the sequenced order diverges from the
  // implicit default — compared ORDER-sensitively, not as a set. A set
  // comparison silently discarded a numbering like api=1, SPAccountId=2,
  // bu_name=3 (same fields as the default, different order) by sending
  // raw_columns: [], and the file came out in group_by order instead.
  // [...a Set] keeps insertion order (group_by, then unique_fields), which is
  // exactly the worker's implicit column order.
  const rawColumns = React.useMemo(() => {
    const defaultOrder = [...defaultIncludedFields];
    const sameOrder =
      orderedIncludedFields.length === defaultOrder.length &&
      orderedIncludedFields.every((f, i) => f === defaultOrder[i]);
    return sameOrder ? [] : orderedIncludedFields;
  }, [orderedIncludedFields, defaultIncludedFields]);

  function toggleIncludedField(field: string) {
    // Newly ticked fields get the next sequence number immediately, so the
    // Seq column is never mysteriously blank and the order always saves.
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

  function loadAggExample() {
    setAggEnabled(true);
    setUseLibrary(false);
    setAggRegex(EXAMPLE_REGEX);
    setGroupByText("api, BU");
    setUniqueFieldsText("spid");
    setSampleLine(EXAMPLE_SAMPLE_LINE);
    setIncludedFieldsOverride(null);
    setColSeq({});
    setColLabels({});
    setColDefaults({});
    setTimestampHeader("timestamp_utc");
    setIncludeLogFormat(true);
    setIncludeMessageColumn(true);
  }

  const sampleTest = React.useMemo(() => {
    if (!aggRegex.trim() || !sampleLine.trim()) {
      return { error: null as string | null, groups: null as Record<string, string> | null };
    }
    try {
      const m = new RegExp(aggRegex).exec(sampleLine);
      return { error: null, groups: (m?.groups as Record<string, string> | undefined) ?? null };
    } catch (e) {
      return { error: (e as Error).message, groups: null };
    }
  }, [aggRegex, sampleLine]);

  // Grouping by the field being counted gives every group exactly one value, so
  // every count is 1 — a report that looks fine and means nothing. Blocked here
  // as well as server-side, so it's caught before a long extraction runs.
  const overlappingFields = React.useMemo(
    () => groupBy.filter((f) => uniqueFields.includes(f)),
    [groupBy, uniqueFields]
  );

  const aggValid =
    !aggEnabled ||
    ((useLibrary || aggRegex.trim() !== "") &&
      uniqueFields.length > 0 &&
      overlappingFields.length === 0);


  const [recentRanges, setRecentRanges] = React.useState<SavedRange[]>([]);
  React.useEffect(() => {
    setRecentRanges(getRecentRanges());
  }, []);

  // Clone (F2): /jobs/new?from=<id> prefills from an existing job.
  const [fromId, setFromId] = React.useState<string | null>(null);
  React.useEffect(() => {
    setFromId(new URLSearchParams(window.location.search).get("from"));
  }, []);
  const { data: cloneJob } = useQuery({
    queryKey: ["clone", fromId],
    queryFn: () => getJob(Number(fromId)),
    enabled: !!fromId,
  });
  // Pre-select last-used credential + region on a fresh form (not a clone).
  React.useEffect(() => {
    const fromParam = new URLSearchParams(window.location.search).get("from");
    if (fromParam) return;
    const last = getLastUsed();
    if (last) {
      setCredentialId(last.credentialId);
      setRegion(last.region);
    }
  }, []);

  React.useEffect(() => {
    if (!cloneJob) return;
    setSearchLabel(cloneJob.filter_spec.label ?? "");
    setCustomer(cloneJob.filter_spec.customer ?? "");
    setCredentialId(cloneJob.credential_id);
    setRegion(cloneJob.region_code);
    setIndexId(cloneJob.index_target_id);
    setPhrases((cloneJob.filter_spec.phrases ?? []).flatMap(splitWords));
    setIdsText((cloneJob.filter_spec.ids ?? []).join("\n"));
    setMessageTypesText((cloneJob.filter_spec.message_types ?? []).join("\n"));
    setChunkHours(cloneJob.chunk_hours);
    setBatchSize(cloneJob.id_batch_size);
    setFormat(
      cloneJob.output_format === "jsonl"
        ? "jsonl"
        : cloneJob.output_format === "bigquery"
        ? "bigquery"
        : "csv"
    );
    setPreset("custom");
    // Must use the zone the fields are read back in (`tz`), not a fixed one —
    // otherwise cloning while the toggle is on the other zone shifts the range.
    setCustomStart(epochToLocal(cloneJob.start_epoch, tz));
    setCustomEnd(epochToLocal(cloneJob.end_epoch, tz));
    const agg = cloneJob.filter_spec.aggregation;
    setAggEnabled(Boolean(agg?.enabled));
    if (agg?.enabled) {
      setAggRegex(agg.regex ?? "");
      setUseLibrary(Boolean(agg.use_library));
      setGroupByText((agg.group_by ?? []).join(", "));
      setUniqueFieldsText((agg.unique_fields ?? []).join(", "));
      setSkipRawOutput(Boolean(agg.skip_raw_output));
      setIncludedFieldsOverride(
        agg.raw_columns && agg.raw_columns.length > 0 ? new Set(agg.raw_columns) : null
      );
      const seq: Record<string, number> = {};
      (agg.raw_columns ?? []).forEach((f: string, i: number) => {
        seq[f] = i + 1;
      });
      setColSeq(seq);
      setColLabels({ ...(agg.column_labels ?? {}) });
      setColDefaults({ ...(agg.raw_column_defaults ?? {}) });
      setTimestampHeader(agg.timestamp_column ?? "timestamp_utc");
      setIncludeLogFormat(agg.include_log_format ?? true);
      setIncludeMessageColumn(agg.include_message ?? true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cloneJob]);

  // Resolve the time range to UTC epochs.
  const { start, end } =
    preset === "custom"
      ? { start: localToEpoch(customStart, tz), end: localToEpoch(customEnd, tz) }
      : { start: nowSec - preset, end: nowSec };

  const ids = React.useMemo(
    () =>
      Array.from(
        new Set(
          idsText
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean)
        )
      ),
    [idsText]
  );
  const messageTypes = React.useMemo(
    () =>
      messageTypesText
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
    [messageTypesText]
  );
  const validRange = end > start;
  const totalChunks = validRange ? Math.ceil((end - start) / (chunkHours * 3600)) : 0;
  const batches = Math.ceil(ids.length / batchSize) || 0;
  const pipeline = buildPipeline(effectivePhrases, ids, messageTypes);

  // Spelled out next to the button so it's obvious the regex travels with the
  // search — it lives in a section far below this one.
  const savedParts = [
    effectivePhrases.length > 0 &&
      `${effectivePhrases.length} word${effectivePhrases.length === 1 ? "" : "s"}`,
    ids.length > 0 && `${ids.length} ID${ids.length === 1 ? "" : "s"}`,
    messageTypes.length > 0 && `${messageTypes.length} message type${messageTypes.length === 1 ? "" : "s"}`,
    aggEnabled && aggRegex.trim() !== "" && "the parse pattern",
  ].filter(Boolean) as string[];
  const hasSomethingToSave = savedParts.length > 0;

  const canRun =
    effectiveCredentialId !== "" &&
    indexId !== "" &&
    validRange &&
    pipeline !== null &&
    aggValid &&
    searchLabel.trim() !== "";

  const create = useMutation({
    mutationFn: (preview: boolean) =>
      createJob({
        credential_id: Number(effectiveCredentialId),
        index_target_id: Number(indexId),
        region_code: region,
        start_epoch: start,
        end_epoch: end,
        chunk_hours: chunkHours,
        id_batch_size: batchSize,
        phrases: effectivePhrases,
        ids,
        message_types: messageTypes,
        output_format: format,
        is_preview: preview,
        // Mandatory extraction label: names output files <search_name>_<job_id>_<timeframe>.csv.zip
        label: searchLabel.trim(),
        customer,
        aggregation: aggEnabled
          ? {
              enabled: true,
              regex: useLibrary ? "" : aggRegex,
              use_library: useLibrary,
              group_by: groupBy,
              unique_fields: uniqueFields,
              skip_raw_output: skipRawOutput,
              raw_columns: rawColumns,
              include_log_format: includeLogFormat,
              include_message: includeMessageColumn,
              column_labels: columnLabels,
              raw_column_defaults: columnDefaults,
              timestamp_column: timestampHeader.trim() || "timestamp_utc",
            }
          : null,
      }),
    onSuccess: (job) => {
      if (effectiveCredentialId !== "") saveLastUsed(Number(effectiveCredentialId), region);
      saveRange(start, end, tz);
      setRecentRanges(getRecentRanges());
      router.push(`/jobs/${job.id}`);
    },
  });

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    setIdsText((prev) => (prev ? `${prev}\n${text}` : text));
    e.target.value = "";
  }

  return (
    <div className="mx-auto max-w-6xl animate-fade-in px-4 py-5">
      <h1 className="pb-3 text-xl font-semibold tracking-tight">New extraction</h1>

      {/* Two columns on wide screens so the whole form fits ~one viewport:
          multicol keeps DOM order (no code moves) with break-inside-avoid so
          no card ever splits across columns. Single column below xl. */}
      <div className="xl:columns-2 [&>*]:mb-3 [&>*]:break-inside-avoid">
        {/* One source profile carries region + index + credential. */}
        <Section title="Source">
          <Field label="Source" className="sm:col-span-2">
            <select
              className={fieldClass}
              value={indexId}
              onChange={(e) => {
                const id = e.target.value ? Number(e.target.value) : "";
                setIndexId(id);
                const picked = allIndexes?.find((i) => i.id === id);
                if (picked) {
                  setRegion(picked.region_code);
                  // Only when the profile names one; otherwise the picker below
                  // stays visible so an older target can still be used.
                  if (picked.credential_id) setCredentialId(picked.credential_id);
                }
              }}
            >
              <option value="">Select a source…</option>
              {allIndexes?.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name} · {i.region_code}
                  {i.credential_label ? ` · ${i.credential_label}` : ""}
                </option>
              ))}
            </select>
            {selectedIndex && (
              <p className="text-xs text-muted-foreground">
                {selectedIndex.region_code} · index{" "}
                <span className="font-mono">
                  {selectedIndex.physical_index ||
                    (selectedIndex.full_index_string
                      ? selectedIndex.name
                      : "Default (org default)")}
                </span>
                {selectedIndex.credential_label ? (
                  <> · credential {selectedIndex.credential_label}</>
                ) : null}
              </p>
            )}
          </Field>
          {/* The loaded search remembers where it was built — one click pulls
              that source in, instead of re-picking it every time. */}
          {(() => {
            const loaded = templates?.find((t) => t.id === templateId);
            const savedIdx = allIndexes?.find((i) => i.id === loaded?.index_target_id);
            if (!loaded?.index_target_id || !savedIdx || savedIdx.id === indexId) return null;
            return (
              <p className="text-xs text-muted-foreground sm:col-span-2">
                Saved with this search:{" "}
                <span className="font-medium text-foreground">
                  {savedIdx.name} · {savedIdx.region_code}
                </span>{" "}
                <button
                  type="button"
                  className="text-primary underline"
                  onClick={() => {
                    setIndexId(savedIdx.id);
                    setRegion(savedIdx.region_code);
                    if (savedIdx.credential_id) setCredentialId(savedIdx.credential_id);
                  }}
                >
                  Use saved source
                </button>
              </p>
            );
          })()}
          {/* Only asked for when the chosen source doesn't name a credential —
              targets created before profiles existed. */}
          {(!selectedIndex || !selectedIndex.credential_id) && (
            <Field label="Credential" className="sm:col-span-2">
              <select
                className={fieldClass}
                value={credentialId}
                onChange={(e) => setCredentialId(e.target.value ? Number(e.target.value) : "")}
              >
                <option value="">Select a credential…</option>
                {credentials?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label} ({c.org_slug})
                  </option>
                ))}
              </select>
              {selectedIndex && (
                <p className="text-xs text-muted-foreground">
                  This source has no credential set — add one on the{" "}
                  <Link href="/indexes" className="underline">
                    Indexes
                  </Link>{" "}
                  page and it won&rsquo;t be asked for again.
                </p>
              )}
            </Field>
          )}
        </Section>

        {/* 3. Time range */}
        <Section title="Time range">
          <div className="space-y-1.5 sm:col-span-2">
            <Label>Timezone</Label>
            <div className="flex items-center gap-2">
              {(["UTC", "IST"] as Tz[]).map((z) => (
                <button
                  key={z}
                  type="button"
                  onClick={() => setTz(z)}
                  style={
                    tz === z
                      ? { backgroundColor: "#39c463", color: "#000", borderColor: "#39c463" }
                      : {}
                  }
                  className={`border px-6 py-2 text-sm font-semibold transition-colors ${
                    tz === z
                      ? "border-transparent"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {z}
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
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
          </div>
          {preset === "custom" && (
            <>
              <Field label={`Start (${tz})`}>
                <Input
                  type="datetime-local"
                  value={customStart}
                  onChange={(e) => setCustomStart(e.target.value)}
                />
              </Field>
              <Field label={`End (${tz})`}>
                <Input
                  type="datetime-local"
                  value={customEnd}
                  onChange={(e) => setCustomEnd(e.target.value)}
                />
              </Field>
            </>
          )}
          {recentRanges.length > 0 && (
            <div className="sm:col-span-2">
              <p className="mb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
                Recent
              </p>
              <div className="flex flex-col gap-0.5">
                {recentRanges.map((r, i) => (
                  <button
                    key={i}
                    type="button"
                    className="w-full border border-transparent px-2 py-1 text-left font-mono text-xs text-muted-foreground hover:border-border hover:text-foreground"
                    onClick={() => {
                      setPreset("custom");
                      setTz(r.tz);
                      setCustomStart(epochToLocal(r.start, r.tz));
                      setCustomEnd(epochToLocal(r.end, r.tz));
                    }}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          <p className="font-mono text-xs text-muted-foreground sm:col-span-2">
            {validRange ? (
              <>
                Resolved: {formatEpoch(start)} → {formatEpoch(end)} UTC · ~{totalChunks} chunk
                {totalChunks === 1 ? "" : "s"}
                {totalChunks > 0 && <> · est. {fmtEstimate(totalChunks)}</>}
              </>
            ) : (
              <span className="text-danger">End must be after start.</span>
            )}
          </p>
        </Section>

        {/* 4. Filter builder */}
        <Section title="Filter">
          <div className="space-y-1.5 sm:col-span-2">
            <Label>
              Extraction Label / Search Name <span className="text-danger">*</span>
            </Label>
            <Input
              value={searchLabel}
              onChange={(e) => setSearchLabel(e.target.value)}
              placeholder="e.g. INVOICE_ABSCBN_NV"
              required
            />
            {!searchLabel.trim() && (
              <p className="text-xs text-danger">
                Mandatory: every extraction requires a search name to name its output files.
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-end gap-3 sm:col-span-2">
            <div className="min-w-[220px] flex-1 space-y-1.5">
              <Label>Load a saved search</Label>
              <TemplatePicker
                templates={templates ?? []}
                value={templateId}
                onPick={(v) => {
                  setTemplateId(v);
                  const tpl = templates?.find((t) => t.id === v);
                  if (tpl) applyTemplate(tpl);
                }}
              />
            </div>
            {savingTemplate ? (
              <>
                <div className="min-w-[180px] space-y-1.5">
                  <Label>Search name</Label>
                  <Input
                    autoFocus
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                    placeholder="India Entitlements SPID"
                  />
                </div>
                <Button
                  size="sm"
                  disabled={!templateName.trim() || saveTemplate.isPending}
                  onClick={() => saveTemplate.mutate(templateName.trim())}
                >
                  {saveTemplate.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Save
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSavingTemplate(false)}>
                  Cancel
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="outline"
                // A parse pattern alone is worth saving — it is the laborious
                // part, and it stands on its own without any filter.
                // A customer is mandatory: it files the search's extracts.
                disabled={!hasSomethingToSave || !customer.trim()}
                onClick={() => {
                  setTemplateName(searchLabel);
                  setSavingTemplate(true);
                }}
                title={
                  customer.trim()
                    ? "Save the current filters and parse pattern as a reusable search"
                    : "Enter a customer name first — saved searches are filed per customer"
                }
              >
                <Bookmark className="h-3.5 w-3.5" />
                Save as search
              </Button>
            )}
            <div className="min-w-[180px] space-y-1.5">
              <Label>
                Customer <span className="text-danger">*</span>
              </Label>
              <Input
                value={customer}
                onChange={(e) => setCustomer(e.target.value)}
                placeholder="ABSCBN"
                required
              />
              {!customer.trim() && hasSomethingToSave && (
                <p className="text-xs text-danger">
                  Required to save this search.
                </p>
              )}
            </div>
            {hasSomethingToSave && !savingTemplate && (
              <p className="text-xs text-muted-foreground">
                Saves {savedParts.join(" + ")}.
              </p>
            )}
            {saveTemplate.isError && (
              <p className="text-xs text-danger">{(saveTemplate.error as Error).message}</p>
            )}
          </div>

          <div className="space-y-2 sm:col-span-2">
            <Label>Required words (all must appear, in any order)</Label>
            <Input
              value={phraseInput}
              onChange={(e) => setPhraseInput(e.target.value)}
              onBlur={commitPhraseInput}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commitPhraseInput();
                }
              }}
              placeholder="e.g. ClassName CGetEntitlementsCommand — press Enter"
            />
            {pendingWords.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {pendingWords.join(" + ")} will be included in this run.
              </p>
            )}
            <div className="flex flex-wrap gap-1.5">
              {phrases.map((p, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 bg-muted px-2.5 py-0.5 text-xs"
                >
                  {p}
                  <button
                    type="button"
                    onClick={() => setPhrases(phrases.filter((_, j) => j !== i))}
                    aria-label={`Remove ${p}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          </div>

          <div className="space-y-2 sm:col-span-2">
            <div className="flex items-center justify-between">
              <Label>Match any of these IDs (one per line)</Label>
              <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-primary">
                <Upload className="h-3.5 w-3.5" /> Upload .txt/.csv
                <input type="file" accept=".txt,.csv" className="hidden" onChange={onUpload} />
              </label>
            </div>
            <textarea
              className={`${fieldClass} h-28 py-2`}
              value={idsText}
              onChange={(e) => setIdsText(e.target.value)}
              placeholder="ID-AAA&#10;ID-BBB&#10;ID-CCC"
            />
            <p className="font-mono text-xs text-muted-foreground">
              {ids.length} unique ID{ids.length === 1 ? "" : "s"} · {batches} batch
              {batches === 1 ? "" : "es"} of {batchSize}
            </p>
          </div>

          <div className="space-y-2 sm:col-span-2">
            <Label>
              Message types to extract{" "}
              <span className="font-normal text-muted-foreground">(AND, optional)</span>
            </Label>
            <textarea
              className={`${fieldClass} h-20 py-2`}
              value={messageTypesText}
              onChange={(e) => setMessageTypesText(e.target.value)}
              placeholder={"GetEntitlementsResponseMessage\ngetEntitlements"}
            />
            <p className="font-mono text-xs text-muted-foreground">
              Only logs containing these message types will be extracted. One per line.
            </p>
          </div>

          <details className="sm:col-span-2">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
              Advanced · generated pipeline JSON
            </summary>
            <pre className="mt-2 max-h-48 overflow-auto border border-border bg-background p-3 font-mono text-xs scrollbar-thin">
              {pipeline ? JSON.stringify(pipeline, null, 2) : "(add a phrase or some IDs)"}
            </pre>
          </details>
        </Section>

        {/* 4b. Parse & aggregate */}
        <Section title="Parse & aggregate (optional)">
          <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={aggEnabled}
                onChange={(e) => setAggEnabled(e.target.checked)}
                className="h-4 w-4"
              />
              Extract fields from each matched line and count unique values
            </label>
            <Button type="button" size="sm" variant="outline" onClick={loadAggExample}>
              Load example
            </Button>
          </div>
          {!aggEnabled && (
            <p className="text-xs text-muted-foreground sm:col-span-2">
              Left off: the raw export is exactly <span className="font-mono">timestamp_utc</span>{" "}
              + <span className="font-mono">message</span> — no parsing, nothing else added.
            </p>
          )}

          {aggEnabled && (
            <>
              <div className="space-y-2 sm:col-span-2">
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="radio"
                    className="mt-1"
                    checked={!useLibrary}
                    onChange={() => setUseLibrary(false)}
                  />
                  <span>
                    One pattern for this job
                    <span className="block text-xs text-muted-foreground">
                      Every row is parsed by the regex below.
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="radio"
                    className="mt-1"
                    checked={useLibrary}
                    onChange={() => setUseLibrary(true)}
                  />
                  <span>
                    Use the Log Formats library
                    <span className="block text-xs text-muted-foreground">
                      Each row is tried against every enabled format until one matches — for a
                      stream carrying several log shapes. Manage them under{" "}
                      <Link href="/log-formats" className="underline">
                        Log formats
                      </Link>
                      .
                    </span>
                  </span>
                </label>
              </div>

              {!useLibrary && (
              <div className="space-y-1.5 sm:col-span-2">
                <Label>
                  Regex with named groups{" "}
                  <span className="font-normal text-muted-foreground">
                    e.g. (?&lt;spid&gt;\d+) — pasted from Last9&rsquo;s Builder works as-is
                  </span>
                </Label>
                <textarea
                  className={`${fieldClass} h-20 py-2 font-mono text-xs`}
                  value={aggRegex}
                  onChange={(e) => setAggRegex(e.target.value)}
                  placeholder="^\s*(?<trackerid>AHA-\d-[a-f0-9-]+)\s+-\s+ClassName\s+(?<api>\w+)\s+SPAccountId\s+(?<spid>\d+)..."
                />
              </div>
              )}
              <Field label="Group by (comma-separated field names)">
                <Input
                  value={groupByText}
                  onChange={(e) => setGroupByText(e.target.value)}
                  placeholder="api, BU"
                />
              </Field>
              <Field label="Count unique values of (comma-separated)">
                <Input
                  value={uniqueFieldsText}
                  onChange={(e) => setUniqueFieldsText(e.target.value)}
                  placeholder="spid, trackerid"
                />
              </Field>
              {overlappingFields.length > 0 && (
                <p className="text-xs text-danger sm:col-span-2">
                  <strong>{overlappingFields.join(", ")}</strong> is in both boxes. Grouping by the
                  field you&apos;re counting puts every value in its own group, so every count comes
                  out as 1. Remove it from &ldquo;Group by&rdquo;.
                </p>
              )}
              <div className="flex items-center gap-2 sm:col-span-2">
                <input
                  type="checkbox"
                  id="skip-raw-output"
                  checked={skipRawOutput}
                  onChange={(e) => setSkipRawOutput(e.target.checked)}
                  className="h-4 w-4"
                />
                <label htmlFor="skip-raw-output" className="text-sm">
                  Summary only — skip writing the raw matched rows to a file
                </label>
              </div>

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

              {/* The Save button is up in Filter; say so here, or the pattern
                  looks like something you have to retype every time. */}
              {aggRegex.trim() !== "" && (
                <p className="text-xs text-muted-foreground sm:col-span-2">
                  <Bookmark className="mr-1 inline h-3 w-3" />
                  This pattern is kept by <strong>Save as search</strong> (in Filter, above), and
                  comes back whenever you load that search — including on a schedule.
                </p>
              )}

              <div className="space-y-1.5 sm:col-span-2">
                <Label>Test against a sample log line (optional)</Label>
                <textarea
                  className={`${fieldClass} h-16 py-2 font-mono text-xs`}
                  value={sampleLine}
                  onChange={(e) => setSampleLine(e.target.value)}
                  placeholder="Paste one real log line to check the regex extracts what you expect"
                />
                {sampleTest.error && <p className="text-xs text-danger">{sampleTest.error}</p>}
                {sampleLine.trim() && !sampleTest.error && !sampleTest.groups && (
                  <p className="text-xs text-danger">No match — check the regex against this line.</p>
                )}
              </div>

              {/* Validate the output before spending a real "Test filter" run:
                  every parsed field with its sequence number and uniform
                  header (independent of group_by/unique_fields — those keep
                  driving the aggregation either way), and a preview of the
                  exact row that choice produces. */}
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

                  {/* Save right here once the preview looks right — no need to
                      come back after Test filter / Run and redo this. */}
                  <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
                    {templateId !== "" ? (
                      <Button
                        type="button"
                        size="sm"
                        disabled={!aggValid || !customer.trim() || updateExistingTemplate.isPending}
                        onClick={() => updateExistingTemplate.mutate()}
                        title={
                          customer.trim() ? undefined : "Enter a customer name first"
                        }
                      >
                        {updateExistingTemplate.isPending ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Check className="h-3.5 w-3.5" />
                        )}
                        Save changes to &ldquo;{templates?.find((t) => t.id === templateId)?.name}
                        &rdquo;
                      </Button>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        Looks right? <strong>Save as search</strong> (in Filter, above) keeps this
                        exact output config — load it again any time instead of rebuilding it.
                      </p>
                    )}
                    {updateExistingTemplate.isSuccess && !updateExistingTemplate.isPending && (
                      <span className="text-xs text-success">Saved.</span>
                    )}
                    {updateExistingTemplate.isError && (
                      <p className="text-xs text-danger">
                        {(updateExistingTemplate.error as Error).message}
                      </p>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </Section>

        {/* 5. Options */}
        <Section title="Options">
          <Field label="Chunk hours">
            <Input
              type="number"
              min={1}
              value={chunkHours}
              onChange={(e) => setChunkHours(Math.max(1, Number(e.target.value)))}
            />
          </Field>
          <Field label="ID batch size">
            <Input
              type="number"
              min={1}
              value={batchSize}
              onChange={(e) => setBatchSize(Math.max(1, Number(e.target.value)))}
            />
          </Field>
          <Field label="Output format">
            <select
              className={fieldClass}
              value={format}
              onChange={(e) => setFormat(e.target.value as "csv" | "jsonl" | "bigquery")}
            >
              <option value="csv">CSV</option>
              <option value="jsonl">JSONL (one JSON object per line)</option>
              <option value="bigquery">BigQuery CSV (6-column)</option>
            </select>
          </Field>
        </Section>

      </div>

      {/* 6. Review & run — pinned to the viewport bottom so it is always at
          hand on a form that now spans columns. */}
      <div className="sticky bottom-0 z-10 -mx-4 mt-3 flex items-center justify-end gap-3 border-t border-border bg-background/95 px-4 py-2 backdrop-blur">
        {create.isError && (
          <p className="text-xs text-danger">{(create.error as Error).message}</p>
        )}
        <Button
          variant="outline"
          disabled={!canRun || create.isPending}
          onClick={() => create.mutate(true)}
          title="Run only the first chunk, capped — to validate the filter"
        >
          Test filter
        </Button>
        <Button disabled={!canRun || create.isPending} onClick={() => create.mutate(false)}>
          {create.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          Run extraction
        </Button>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">{children}</CardContent>
    </Card>
  );
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
