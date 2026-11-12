"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, Check, Loader2, Upload, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldGroup, Input, Label, fieldClass } from "@/components/ui/input";
import {
  OutputColumnsEditor,
  orderBySeq,
  suggestUniformLayout,
} from "@/components/output-columns-editor";
import { AutoDetectPanel, type AutoDetectApply } from "@/components/auto-detect-panel";
import { TemplatePicker } from "@/components/template-picker";
import { exactPhraseRegex, extractGroupNames, parsePhraseInput } from "@/lib/aggregation";
import {
  FilterTemplate,
  FilterTemplateInput,
  createJob,
  createTemplate,
  getJob,
  listCredentials,
  listIndexes,
  listLogFormats,
  listRegions,
  listS3Profiles,
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

type TemplateSaveConflict = {
  mode: "create" | "update";
  name: string;
  existingId: number | null;
  existingName: string;
};

function isDuplicateNameError(error: unknown): boolean {
  return error instanceof Error && /already exists/i.test(error.message);
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
function buildPipeline(
  phrases: string[],
  ids: string[],
  messageTypes: string[],
  exactPhrases: string[] = [],
  excludePhrases: string[] = [],
  excludeExactPhrases: string[] = []
) {
  const allPhrases = [...phrases, ...messageTypes];
  const clauses: unknown[] = allPhrases.map((p) => ({ $contains: ["Body", p] }));
  // Quoted phrases: adjacent tokens, so "API : 502" cannot be satisfied by a
  // stray 502 elsewhere in the line.
  for (const phrase of exactPhrases) {
    clauses.push({ $regex: ["Body", exactPhraseRegex(phrase)] });
  }
  if (ids.length) clauses.push({ $regex: ["Body", ids.map(esc).join("|")] });
  // NOT combination: a row must contain none of these. (NOT A AND NOT B.)
  for (const phrase of excludePhrases) {
    clauses.push({ $notcontains: ["Body", phrase] });
  }
  for (const phrase of excludeExactPhrases) {
    clauses.push({ $notregex: ["Body", exactPhraseRegex(phrase)] });
  }
  // A filter still needs something positive; exclusions alone would scan and
  // then discard everything.
  if (allPhrases.length === 0 && exactPhrases.length === 0 && ids.length === 0) return null;
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
  const { data: allIndexes } = useQuery({
    queryKey: ["indexes", ""],
    queryFn: () => listIndexes(),
  });
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
  // Quoted phrases ("API : 502"): adjacent tokens, matched as a regex. Without
  // this, "$contains 502" also matches the 502 inside a millisecond timestamp.
  const [exactPhrases, setExactPhrases] = React.useState<string[]>([]);
  const [excludePhrases, setExcludePhrases] = React.useState<string[]>([]);
  const [excludeExactPhrases, setExcludeExactPhrases] = React.useState<string[]>([]);
  const [excludeInput, setExcludeInput] = React.useState("");
  const [phraseInput, setPhraseInput] = React.useState("");
  const [idsText, setIdsText] = React.useState("");
  const [messageTypesText, setMessageTypesText] = React.useState("");

  // Typed-but-not-yet-Entered words used to be dropped on the floor: the job ran
  // without them, against a far larger set, and nobody found out until hours
  // later. Anything in the box counts — it's committed on blur, and folded in
  // here so a click straight from the box to "Run extraction" can't lose it.
  const pending = React.useMemo(() => parsePhraseInput(phraseInput), [phraseInput]);
  const pendingWords = pending.words;
  const effectivePhrases = React.useMemo(
    () => [...phrases, ...pendingWords],
    [phrases, pendingWords]
  );
  const effectiveExact = React.useMemo(
    () => [...exactPhrases, ...pending.exact],
    [exactPhrases, pending.exact]
  );
  // The NOT box uses the same parser: unquoted = exclude the word, quoted =
  // exclude the adjacent phrase.
  const pendingExclude = React.useMemo(() => parsePhraseInput(excludeInput), [excludeInput]);
  const effectiveExclude = React.useMemo(
    () => [...excludePhrases, ...pendingExclude.words],
    [excludePhrases, pendingExclude.words]
  );
  const effectiveExcludeExact = React.useMemo(
    () => [...excludeExactPhrases, ...pendingExclude.exact],
    [excludeExactPhrases, pendingExclude.exact]
  );
  function commitPhraseInput() {
    if (pendingWords.length === 0 && pending.exact.length === 0) return;
    if (pendingWords.length > 0) setPhrases((prev) => [...prev, ...pendingWords]);
    if (pending.exact.length > 0) setExactPhrases((prev) => [...prev, ...pending.exact]);
    setPhraseInput("");
  }
  function commitExcludeInput() {
    if (pendingExclude.words.length === 0 && pendingExclude.exact.length === 0) return;
    if (pendingExclude.words.length > 0)
      setExcludePhrases((prev) => [...prev, ...pendingExclude.words]);
    if (pendingExclude.exact.length > 0)
      setExcludeExactPhrases((prev) => [...prev, ...pendingExclude.exact]);
    setExcludeInput("");
  }

  // "Save the search": named phrase/ID/message-type sets, reusable across jobs
  // and schedules.
  const qc = useQueryClient();
  const { data: templates } = useQuery({ queryKey: ["templates"], queryFn: listTemplates });
  const { data: s3Profiles } = useQuery({ queryKey: ["s3-profiles"], queryFn: listS3Profiles });
  const [templateId, setTemplateId] = React.useState<number | "">("");
  const [s3ProfileId, setS3ProfileId] = React.useState<number | "">("");
  const [savingTemplate, setSavingTemplate] = React.useState(false);
  const [templateName, setTemplateName] = React.useState("");
  const [saveConflict, setSaveConflict] = React.useState<TemplateSaveConflict | null>(null);
  const searchNameRef = React.useRef<HTMLInputElement>(null);
  const templateNameRef = React.useRef<HTMLInputElement>(null);
  const conflictRef = React.useRef<HTMLDivElement>(null);
  // Mandatory search name / extraction label: every extraction requires a name
  // so extracted files are always identifiable on disk and downloads.
  const [searchLabel, setSearchLabel] = React.useState("");
  // Groups this job's output files under exports/<customer>/. Comes from the
  // saved search when one is loaded, and is editable for a one-off run.
  const [customer, setCustomer] = React.useState("");

  function applyTemplate(tpl: FilterTemplate) {
    setSearchLabel(tpl.name);
    setPhrases(tpl.phrases);
    setExactPhrases(tpl.exact_phrases ?? []);
    setExcludePhrases(tpl.exclude_phrases ?? []);
    setExcludeExactPhrases(tpl.exclude_exact_phrases ?? []);
    setExcludeInput("");
    setIdsText(tpl.ids.join("\n"));
    setMessageTypesText(tpl.message_types.join("\n"));
    setS3ProfileId(tpl.s3_profile_id ?? "");
    // The regex is the laborious part of a search, so a saved one comes back
    // with it. A template without a parse config just switches the section off
    // rather than wiping whatever is typed there.
    const agg = tpl.aggregation;
    setAggEnabled(Boolean(agg?.enabled));
    if (agg?.enabled) {
      setAggregateEnabled(agg.aggregate !== false);
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

  function buildTemplatePayload(name: string): FilterTemplateInput {
    return {
      name,
      phrases: effectivePhrases,
      ids,
      exact_phrases: effectiveExact,
      exclude_phrases: effectiveExclude,
      exclude_exact_phrases: effectiveExcludeExact,
      message_types: messageTypes,
      customer,
      // Remember where this search was built, so batch runs and future
      // loads come pre-filled with its source.
      credential_id: effectiveCredentialId === "" ? null : Number(effectiveCredentialId),
      region_code: region || null,
      index_target_id: indexId === "" ? null : Number(indexId),
      s3_profile_id: s3ProfileId === "" ? null : Number(s3ProfileId),
      aggregation: aggEnabled
        ? {
            enabled: true,
            aggregate: aggregateEnabled,
            regex: useLibrary ? "" : aggRegex,
            use_library: useLibrary,
            group_by: aggregateEnabled ? groupBy : [],
            unique_fields: aggregateEnabled ? uniqueFields : [],
            skip_raw_output: aggregateEnabled ? skipRawOutput : false,
            raw_columns: rawColumns,
            include_log_format: includeLogFormat,
            include_message: includeMessageColumn,
            column_labels: columnLabels,
            raw_column_defaults: columnDefaults,
            timestamp_column: timestampHeader.trim() || "timestamp_utc",
          }
        : null,
    };
  }

  function findTemplateByName(name: string): FilterTemplate | undefined {
    const needle = name.trim().toLowerCase();
    return templates?.find((t) => t.name.trim().toLowerCase() === needle);
  }

  const saveTemplate = useMutation({
    mutationFn: (name: string) => createTemplate(buildTemplatePayload(name)),
    onSuccess: (tpl) => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      setTemplateId(tpl.id);
      setSearchLabel(tpl.name);
      setSavingTemplate(false);
      setTemplateName("");
      setSaveConflict(null);
    },
    onError: (error: Error, name: string) => {
      // The list is normally fresh enough for the preflight check. If another
      // tab created the name between render and save, turn the 409 into the
      // same update/rename choice instead of a dead-end error.
      if (isDuplicateNameError(error)) {
        const existing = findTemplateByName(name);
        setSaveConflict({
          mode: "create",
          name,
          existingId: existing?.id ?? null,
          existingName: existing?.name ?? name,
        });
        qc.invalidateQueries({ queryKey: ["templates"] });
      }
    },
  });

  // Saves straight back onto the search that's loaded — the point of
  // validating the output here is not having to come back to Filter and
  // re-save under the same name after every tweak.
  const updateExistingTemplate = useMutation({
    mutationFn: (name: string) => updateTemplate(Number(templateId), buildTemplatePayload(name)),
    onSuccess: (tpl) => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      setSearchLabel(tpl.name);
      setSaveConflict(null);
    },
    onError: (error: Error, name: string) => {
      if (isDuplicateNameError(error)) {
        const existing = findTemplateByName(name);
        setSaveConflict({
          mode: "update",
          name,
          existingId: existing?.id ?? null,
          existingName: existing?.name ?? name,
        });
        qc.invalidateQueries({ queryKey: ["templates"] });
      }
    },
  });

  // Called only after the person explicitly chooses "Update existing" in the
  // conflict panel. It may target a different saved search than the one loaded.
  const resolveTemplateConflict = useMutation({
    mutationFn: (conflict: TemplateSaveConflict) => {
      if (conflict.existingId == null) {
        throw new Error("Refresh the saved searches and try again");
      }
      return updateTemplate(conflict.existingId, buildTemplatePayload(conflict.name));
    },
    onSuccess: (tpl) => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      setTemplateId(tpl.id);
      setSearchLabel(tpl.name);
      setSavingTemplate(false);
      setTemplateName("");
      setSaveConflict(null);
    },
  });

  function startSaveAsSearch() {
    const name = templateName.trim();
    if (!name) return;
    saveTemplate.reset();
    const existing = findTemplateByName(name);
    if (existing) {
      resolveTemplateConflict.reset();
      setSaveConflict({
        mode: "create",
        name,
        existingId: existing.id,
        existingName: existing.name,
      });
      return;
    }
    setSaveConflict(null);
    saveTemplate.mutate(name);
  }

  function startSaveExistingChanges() {
    const name = searchLabel.trim();
    if (!name) return;
    updateExistingTemplate.reset();
    const existing = findTemplateByName(name);
    if (existing && existing.id !== Number(templateId)) {
      resolveTemplateConflict.reset();
      setSaveConflict({
        mode: "update",
        name,
        existingId: existing.id,
        existingName: existing.name,
      });
      return;
    }
    setSaveConflict(null);
    updateExistingTemplate.mutate(name);
  }

  function handleRenameConflict() {
    const conflict = saveConflict;
    setSaveConflict(null);
    if (!conflict) return;
    if (conflict.mode === "create") {
      setSavingTemplate(true);
      setTemplateName(conflict.name);
      requestAnimationFrame(() => {
        templateNameRef.current?.focus();
        templateNameRef.current?.select();
      });
    } else {
      requestAnimationFrame(() => {
        searchNameRef.current?.focus();
        searchNameRef.current?.select();
      });
    }
  }

  /**
   * Apply a detected pattern: fill the regex (or switch to the library) and the
   * two field boxes from the fields that actually carried values in the pasted
   * sample. Column overrides are cleared so the output checklist follows the
   * newly detected fields instead of a previous search's selection.
   */
  function applyAutoDetect(apply: AutoDetectApply, label: string) {
    setAggEnabled(true);
    setAggregateEnabled(true);
    setUseLibrary(apply.useLibrary);
    if (!apply.useLibrary) setAggRegex(apply.regex ?? "");
    setGroupByText(apply.groupBy.join(", "));
    setUniqueFieldsText(apply.unique.join(", "));
    // Show the pasted line in the sample-test box so the extracted fields are
    // visible right away instead of only after someone pastes it again.
    setSampleLine(apply.sample);
    setIncludedFieldsOverride(null);
    setColSeq({});
    setColLabels({});
    setColDefaults({});
    setDetectedFrom(label);
  }

  // A conflict is resolved in the Filter card, but the Save changes button that
  // raises an update conflict lives lower in the page. Bring the choice into view.
  React.useEffect(() => {
    if (!saveConflict) return;
    requestAnimationFrame(() => {
      conflictRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }, [saveConflict]);

  // If a 409 arrived before the templates query refreshed, fill in the id once
  // the refetched list contains the conflicting name, so Update existing works.
  React.useEffect(() => {
    if (!saveConflict || saveConflict.existingId != null) return;
    const existing = findTemplateByName(saveConflict.name);
    if (existing) {
      setSaveConflict((current) =>
        current
          ? {
              ...current,
              existingId: existing.id,
              existingName: existing.name,
            }
          : current
      );
    }
    // findTemplateByName reads the latest templates list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templates, saveConflict]);

  const [chunkHours, setChunkHours] = React.useState(1);
  const [batchSize, setBatchSize] = React.useState(100);
  const [format, setFormat] = React.useState<"csv" | "jsonl" | "bigquery">("csv");

  // Parse & aggregate: extract named fields from each matched line and count
  // DISTINCT values of one or more of them, grouped by the others.
  const [aggEnabled, setAggEnabled] = React.useState(false);
  // Parse and aggregate are separate: parse extracts fields into the CSV,
  // aggregate adds group-by + distinct counts. Both on = the old behaviour.
  const [aggregateEnabled, setAggregateEnabled] = React.useState(true);
  const [aggRegex, setAggRegex] = React.useState("");
  const [groupByText, setGroupByText] = React.useState("");
  const [uniqueFieldsText, setUniqueFieldsText] = React.useState("");
  const [skipRawOutput, setSkipRawOutput] = React.useState(false);
  // Use every enabled pattern in the Log Formats library instead of one regex
  // typed here — the only workable option once there are many log shapes.
  const [useLibrary, setUseLibrary] = React.useState(false);
  const [sampleLine, setSampleLine] = React.useState("");
  // Name of the saved pattern the Auto-detect panel applied, shown next to the
  // fields so it is clear where the prefilled values came from.
  const [detectedFrom, setDetectedFrom] = React.useState<string | null>(null);
  // Which parsed fields land in the output file, independent of group_by/
  // unique_fields (those still drive the grouping either way). null = no
  // manual choice yet, so the checklist falls back to the implicit default
  // (group_by ∪ unique_fields) — exactly today's behavior, unchanged.
  const [includedFieldsOverride, setIncludedFieldsOverride] = React.useState<Set<string> | null>(
    null
  );
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
    // Aggregating: the deliverable is the grouped/counted fields. Parse-only:
    // every extracted field is a column unless the user unchecks one.
    () => new Set(aggregateEnabled ? [...groupBy, ...uniqueFields] : regexFields),
    [aggregateEnabled, groupBy, uniqueFields, regexFields]
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
    setAggregateEnabled(true);
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
      (!aggregateEnabled || (uniqueFields.length > 0 && overlappingFields.length === 0)));

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
    setS3ProfileId(cloneJob.s3_profile_id ?? "");
    setPhrases((cloneJob.filter_spec.phrases ?? []).flatMap(splitWords));
    setExactPhrases(cloneJob.filter_spec.exact_phrases ?? []);
    setExcludePhrases(cloneJob.filter_spec.exclude_phrases ?? []);
    setExcludeExactPhrases(cloneJob.filter_spec.exclude_exact_phrases ?? []);
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
      setAggregateEnabled(agg.aggregate !== false);
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
  const pipeline = buildPipeline(
    effectivePhrases,
    ids,
    messageTypes,
    effectiveExact,
    effectiveExclude,
    effectiveExcludeExact
  );

  // Spelled out next to the button so it's obvious the regex travels with the
  // search — it lives in a section far below this one.
  const savedParts = [
    effectivePhrases.length > 0 &&
      `${effectivePhrases.length} word${effectivePhrases.length === 1 ? "" : "s"}`,
    effectiveExact.length > 0 &&
      `${effectiveExact.length} exact phrase${effectiveExact.length === 1 ? "" : "s"}`,
    effectiveExclude.length + effectiveExcludeExact.length > 0 &&
      `${effectiveExclude.length + effectiveExcludeExact.length} exclusion${
        effectiveExclude.length + effectiveExcludeExact.length === 1 ? "" : "s"
      }`,
    ids.length > 0 && `${ids.length} ID${ids.length === 1 ? "" : "s"}`,
    messageTypes.length > 0 &&
      `${messageTypes.length} message type${messageTypes.length === 1 ? "" : "s"}`,
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
        exact_phrases: effectiveExact,
        exclude_phrases: effectiveExclude,
        exclude_exact_phrases: effectiveExcludeExact,
        message_types: messageTypes,
        output_format: format,
        is_preview: preview,
        // Mandatory extraction label: names output files <search_name>_<job_id>_<timeframe>.csv.zip
        label: searchLabel.trim(),
        customer,
        s3_profile_id: s3ProfileId === "" ? null : Number(s3ProfileId),
        aggregation: aggEnabled
          ? {
              enabled: true,
              aggregate: aggregateEnabled,
              regex: useLibrary ? "" : aggRegex,
              use_library: useLibrary,
              group_by: aggregateEnabled ? groupBy : [],
              unique_fields: aggregateEnabled ? uniqueFields : [],
              skip_raw_output: aggregateEnabled ? skipRawOutput : false,
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
              ref={searchNameRef}
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
                    ref={templateNameRef}
                    autoFocus
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                    placeholder="India Entitlements SPID"
                  />
                </div>
                <Button
                  size="sm"
                  disabled={!templateName.trim() || saveTemplate.isPending}
                  onClick={startSaveAsSearch}
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
                <p className="text-xs text-danger">Required to save this search.</p>
              )}
            </div>
            {hasSomethingToSave && !savingTemplate && (
              <p className="text-xs text-muted-foreground">Saves {savedParts.join(" + ")}.</p>
            )}
            {saveTemplate.isError && !saveConflict && !isDuplicateNameError(saveTemplate.error) && (
              <p className="text-xs text-danger">{(saveTemplate.error as Error).message}</p>
            )}
          </div>

          {saveConflict && (
            <div
              ref={conflictRef}
              className="sm:col-span-2 border border-warning/40 bg-warning/10 p-3"
            >
              <p className="text-sm font-medium">Saved search name already exists</p>
              <p className="mt-1 text-xs text-muted-foreground">
                <strong>{saveConflict.existingName}</strong> is already saved.
                {saveConflict.mode === "update"
                  ? " You renamed this search to a name that another saved search already uses."
                  : ""}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Updating replaces that saved search&apos;s filter and parse pattern with the
                settings currently on this screen.
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {saveConflict.existingId != null && (
                  <Button
                    size="sm"
                    onClick={() => resolveTemplateConflict.mutate(saveConflict)}
                    disabled={resolveTemplateConflict.isPending}
                  >
                    {resolveTemplateConflict.isPending && (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    )}
                    Update existing
                  </Button>
                )}
                <Button size="sm" variant="outline" onClick={handleRenameConflict}>
                  Rename
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSaveConflict(null)}>
                  Cancel
                </Button>
              </div>
              {saveConflict.existingId == null && (
                <p className="mt-2 text-[11px] text-muted-foreground">
                  The saved searches list is stale. Refresh the page to update the existing search,
                  or choose Rename.
                </p>
              )}
              {resolveTemplateConflict.isError && (
                <p className="mt-2 text-xs text-danger">
                  {(resolveTemplateConflict.error as Error).message}
                </p>
              )}
            </div>
          )}

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
              placeholder={
                'e.g. ClassName CGetEntitlementsCommand  ·  "API : 502" for an exact phrase'
              }
            />
            <p className="text-xs text-muted-foreground">
              Quote a phrase to require those tokens <strong>adjacent</strong> —{" "}
              <span className="font-mono">&quot;API : 502&quot;</span>. Left unquoted, each word may
              appear anywhere, so <span className="font-mono">502</span> would also match a
              timestamp.
            </p>
            {(pendingWords.length > 0 || pending.exact.length > 0) && (
              <p className="text-xs text-muted-foreground">
                {[...pendingWords, ...pending.exact.map((p) => `"${p}"`)].join(" + ")} will be
                included in this run.
              </p>
            )}
            <div className="flex flex-wrap gap-1.5">
              {phrases.map((p, i) => (
                <span
                  key={`w${i}`}
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
              {exactPhrases.map((p, i) => (
                <span
                  key={`e${i}`}
                  className="inline-flex items-center gap-1 border border-primary/40 bg-primary/10 px-2.5 py-0.5 font-mono text-xs text-primary"
                  title="Exact phrase — these tokens must be adjacent"
                >
                  &quot;{p}&quot;
                  <button
                    type="button"
                    onClick={() => setExactPhrases(exactPhrases.filter((_, j) => j !== i))}
                    aria-label={`Remove exact phrase ${p}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          </div>

          <div className="space-y-2 sm:col-span-2">
            <Label>Must NOT contain (all must be absent, in any order)</Label>
            <Input
              value={excludeInput}
              onChange={(e) => setExcludeInput(e.target.value)}
              onBlur={commitExcludeInput}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commitExcludeInput();
                }
              }}
              placeholder={'e.g. healthcheck  ·  "API : 502" for an exact phrase'}
            />
            <p className="text-xs text-muted-foreground">
              A log is excluded if any of these appears. Quote a phrase to exclude those tokens only
              when <strong>adjacent</strong>.
            </p>
            {(pendingExclude.words.length > 0 || pendingExclude.exact.length > 0) && (
              <p className="text-xs text-muted-foreground">
                {[...pendingExclude.words, ...pendingExclude.exact.map((p) => `"${p}"`)].join(
                  " + "
                )}{" "}
                will be excluded from this run.
              </p>
            )}
            <div className="flex flex-wrap gap-1.5">
              {excludePhrases.map((p, i) => (
                <span
                  key={`x${i}`}
                  className="inline-flex items-center gap-1 border border-danger/40 bg-danger/10 px-2.5 py-0.5 text-xs text-danger"
                >
                  NOT {p}
                  <button
                    type="button"
                    onClick={() => setExcludePhrases(excludePhrases.filter((_, j) => j !== i))}
                    aria-label={`Remove excluded word ${p}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
              {excludeExactPhrases.map((p, i) => (
                <span
                  key={`xe${i}`}
                  className="inline-flex items-center gap-1 border border-danger/40 bg-danger/10 px-2.5 py-0.5 font-mono text-xs text-danger"
                  title="Exclude only when these tokens are adjacent"
                >
                  NOT &quot;{p}&quot;
                  <button
                    type="button"
                    onClick={() =>
                      setExcludeExactPhrases(excludeExactPhrases.filter((_, j) => j !== i))
                    }
                    aria-label={`Remove excluded exact phrase ${p}`}
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
              Extract fields from each matched line
            </label>
            <Button type="button" size="sm" variant="outline" onClick={loadAggExample}>
              Load example
            </Button>
          </div>
          {!aggEnabled && (
            <p className="text-xs text-muted-foreground sm:col-span-2">
              Left off: the raw export is exactly <span className="font-mono">timestamp_utc</span> +{" "}
              <span className="font-mono">message</span> — no parsing, nothing else added.
            </p>
          )}

          {aggEnabled && (
            <>
              <AutoDetectPanel onApply={applyAutoDetect} />

              {detectedFrom && (
                <p className="text-[11px] text-muted-foreground sm:col-span-2">
                  Pattern detected from <strong>{detectedFrom}</strong>. Edit the regex or the field
                  boxes if the sample was not representative.
                </p>
              )}

              <label className="flex items-start gap-2 text-sm sm:col-span-2">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4"
                  checked={aggregateEnabled}
                  onChange={(e) => setAggregateEnabled(e.target.checked)}
                />
                <span>
                  Also aggregate: group and count distinct values
                  <span className="block text-xs text-muted-foreground">
                    On: counts unique values of the fields below. Off: parse only — every matched
                    row&rsquo;s fields go to the CSV, but no counts are computed.
                  </span>
                </span>
              </label>

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
              {aggregateEnabled ? (
                <>
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
                      <strong>{overlappingFields.join(", ")}</strong> is in both boxes. Grouping by
                      the field you&apos;re counting puts every value in its own group, so every
                      count comes out as 1. Remove it from &ldquo;Group by&rdquo;.
                    </p>
                  )}
                </>
              ) : (
                <p className="text-xs text-muted-foreground sm:col-span-2">
                  Parse only — no group-by or counts. The fields you keep in the output editor below
                  are written for every matched row.
                </p>
              )}
              <div className="flex items-center gap-2 sm:col-span-2">
                <input
                  type="checkbox"
                  id="skip-raw-output"
                  checked={skipRawOutput}
                  disabled={!aggregateEnabled}
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
                  comes back whenever you load that search — including on a schedule. It is also
                  added to <strong>Log formats</strong> automatically so other searches can reuse
                  it.
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
                  <p className="text-xs text-danger">
                    No match — check the regex against this line.
                  </p>
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

                  {aggregateEnabled && uniqueFields.length === 0 && (
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
                        disabled={
                          !aggValid ||
                          !customer.trim() ||
                          !searchLabel.trim() ||
                          updateExistingTemplate.isPending
                        }
                        onClick={startSaveExistingChanges}
                        title={customer.trim() ? undefined : "Enter a customer name first"}
                      >
                        {updateExistingTemplate.isPending ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Check className="h-3.5 w-3.5" />
                        )}
                        Save changes to &ldquo;
                        {searchLabel.trim() || templates?.find((t) => t.id === templateId)?.name}
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
                    {updateExistingTemplate.isError &&
                      !saveConflict &&
                      !isDuplicateNameError(updateExistingTemplate.error) && (
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
          <Field label="S3 destination (optional)">
            <select
              className={fieldClass}
              value={s3ProfileId}
              onChange={(e) => setS3ProfileId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">No S3 upload — local download only</option>
              {s3Profiles?.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name} · {profile.bucket}
                  {profile.prefix ? `/${profile.prefix}` : ""}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              Uploads raw, summary, and counts artifacts when the run completes. Saved searches keep
              this choice for scheduled runs.
            </p>
            {s3Profiles && s3Profiles.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No S3 profiles yet.{" "}
                <Link href="/s3-profiles" className="text-primary hover:underline">
                  Add one
                </Link>
                .
              </p>
            )}
          </Field>
        </Section>
      </div>

      {/* 6. Review & run — pinned to the viewport bottom so it is always at
          hand on a form that now spans columns. */}
      <div className="sticky bottom-0 z-10 -mx-4 mt-3 flex items-center justify-end gap-3 border-t border-border bg-background/95 px-4 py-2 backdrop-blur">
        {create.isError && <p className="text-xs text-danger">{(create.error as Error).message}</p>}
        <Button
          variant="outline"
          disabled={!canRun || create.isPending}
          onClick={() => create.mutate(true)}
          title="Sample the newest part of the window, capped at 100 rows - to validate the filter"
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
