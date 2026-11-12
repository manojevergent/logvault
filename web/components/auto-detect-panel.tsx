"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Save, ScanSearch, Sparkles } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldGroup, Input, Label, fieldClass } from "@/components/ui/input";
import {
  DetectedCandidate,
  DetectedField,
  DetectResult,
  createLogFormat,
  detectLogFormats,
} from "@/lib/api";

export type AutoDetectApply = {
  /** null = the library matched, so no single regex is needed. */
  regex: string | null;
  useLibrary: boolean;
  groupBy: string[];
  unique: string[];
  /** First pasted line, so the sample-test box shows the match immediately. */
  sample: string;
};

function FieldChips({ fields }: { fields: DetectedField[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {fields.map((field) => (
        <span
          key={field.name}
          className="inline-flex items-center gap-1 border border-border bg-muted/50 px-1.5 py-0.5 text-[11px]"
          title={`${field.coverage} of the matched lines carry a value · ${field.distinct} distinct · e.g. ${field.sample || "(empty)"}`}
        >
          <span className="font-mono font-medium">{field.name}</span>
          <span
            className={
              field.suggested === "unique"
                ? "text-primary"
                : field.suggested === "group_by"
                  ? "text-muted-foreground"
                  : "text-muted-foreground/60"
            }
          >
            {field.suggested === "unique" ? "count" : field.suggested === "group_by" ? "group" : ""}
          </span>
          {field.sample && (
            <span className="max-w-[110px] truncate text-muted-foreground/80">{field.sample}</span>
          )}
        </span>
      ))}
    </div>
  );
}

function CandidateRow({
  candidate,
  sample,
  onApply,
}: {
  candidate: DetectedCandidate;
  sample: string;
  onApply: (apply: AutoDetectApply, label: string) => void;
}) {
  return (
    <div className="space-y-1.5 border border-border p-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <Badge tone={candidate.source === "library" ? "info" : "neutral"}>
            {candidate.source === "library" ? "Log format" : "Saved search"}
          </Badge>
          <span className="truncate text-xs font-medium">{candidate.name}</span>
          <span className="font-mono text-[11px] text-muted-foreground">
            {candidate.matched} line{candidate.matched === 1 ? "" : "s"}
          </span>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() =>
            onApply(
              {
                regex: candidate.source === "saved_search" ? candidate.regex : null,
                useLibrary: candidate.source === "library",
                groupBy: candidate.suggested_group_by,
                unique: candidate.suggested_unique,
                sample,
              },
              candidate.name
            )
          }
        >
          <Check className="h-3.5 w-3.5" />
          Use this
        </Button>
      </div>
      {candidate.fields.length > 0 ? (
        <FieldChips fields={candidate.fields} />
      ) : (
        <p className="text-[11px] text-muted-foreground">
          Matched, but the pattern defines no named groups.
        </p>
      )}
    </div>
  );
}

/**
 * Auto-detect panel for the parse stage.
 *
 * The patterns that already exist in the platform are the ones worth reusing:
 * the Log Formats library the extractor actually tries, and each saved search's
 * bundled regex. Pasting real lines identifies which one fits and prefills the
 * group-by / unique-count boxes from the fields that are actually populated.
 */
export function AutoDetectPanel({
  onApply,
}: {
  onApply: (apply: AutoDetectApply, label: string) => void;
}) {
  const [linesText, setLinesText] = React.useState("");
  const [result, setResult] = React.useState<DetectResult | null>(null);
  const [applied, setApplied] = React.useState<string | null>(null);
  const [formatName, setFormatName] = React.useState("");
  const [savedName, setSavedName] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState(false);
  const qc = useQueryClient();

  // One line per entry, trimmed of trailing whitespace but keeping leading
  // spaces: some patterns anchor on them.
  const lines = React.useMemo(
    () =>
      linesText
        .split(/\r?\n/)
        .map((line) => line.trimEnd())
        .filter((line) => line.trim()),
    [linesText]
  );

  const saveInferred = useMutation({
    mutationFn: () => {
      const inferred = result?.inferred;
      if (!inferred) throw new Error("nothing to save");
      return createLogFormat({
        name: formatName.trim(),
        regex: inferred.regex,
        sample_line: lines[0] ?? "",
        priority: 100,
      });
    },
    onSuccess: (format) => {
      // Later jobs read this list to offer the format, so it must not stay stale.
      qc.invalidateQueries({ queryKey: ["log-formats"] });
      const inferred = result?.inferred;
      if (!inferred) return;
      onApply(
        {
          regex: format.regex,
          useLibrary: false,
          groupBy: inferred.suggested_group_by,
          unique: inferred.suggested_unique,
          sample: lines[0] ?? "",
        },
        format.name
      );
      setApplied(format.name);
      setSavedName(format.name);
    },
  });

  const detect = useMutation({
    mutationFn: () => detectLogFormats(lines),
    onSuccess: (data) => {
      setResult(data);
      setApplied(null);
      setFormatName("");
      setSavedName(null);
      saveInferred.reset();
    },
  });

  function useInferredOnce() {
    const inferred = result?.inferred;
    if (!inferred) return;
    onApply(
      {
        regex: inferred.regex,
        useLibrary: false,
        groupBy: inferred.suggested_group_by,
        unique: inferred.suggested_unique,
        sample: lines[0] ?? "",
      },
      "the pasted lines"
    );
    setApplied("the inferred pattern");
  }

  if (!open) {
    return (
      <div className="sm:col-span-2">
        <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
          <Sparkles className="h-3.5 w-3.5" />
          Auto-detect from pasted lines
        </Button>
        <span className="ml-2 text-[11px] text-muted-foreground">
          Uses the patterns already saved in Log formats and Saved searches.
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-2 border border-border bg-muted/20 p-3 sm:col-span-2">
      <div className="flex items-center justify-between gap-2">
        <Label>Auto-detect from real log lines</Label>
        <button
          type="button"
          className="text-[11px] text-muted-foreground hover:text-foreground"
          onClick={() => setOpen(false)}
        >
          Hide
        </button>
      </div>
      <FieldGroup>
        <textarea
          className={`${fieldClass} h-28 py-2 font-mono text-xs`}
          value={linesText}
          onChange={(e) => setLinesText(e.target.value)}
          placeholder={
            "Paste a handful of real lines (one per line), then Detect.\nEvery saved pattern is tried against them."
          }
        />
      </FieldGroup>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          disabled={detect.isPending || linesText.trim() === ""}
          onClick={() => detect.mutate()}
        >
          {detect.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <ScanSearch className="h-3.5 w-3.5" />
          )}
          Detect
        </Button>
        <span className="text-[11px] text-muted-foreground">{lines.length} line(s)</span>
        {detect.isError && (
          <span className="text-xs text-danger">{(detect.error as Error).message}</span>
        )}
      </div>

      {result && (
        <div className="space-y-2 border-t border-border pt-2">
          <p className="text-[11px] text-muted-foreground">
            {result.matched} of {result.lines_analyzed} line(s) matched a saved pattern.
            {result.message ? ` ${result.message}` : ""}
          </p>

          {result.inferred && (
            <div className="space-y-2 border border-primary/40 bg-primary/5 p-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="info">New shape</Badge>
                <span className="text-xs font-medium">
                  Built from {result.inferred.lines_used} pasted line
                  {result.inferred.lines_used === 1 ? "" : "s"}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  Save it once and every future extraction can reuse it.
                </span>
              </div>
              <pre className="max-h-24 overflow-auto whitespace-pre-wrap break-all border border-border bg-surface p-2 font-mono text-[11px]">
                {result.inferred.regex}
              </pre>
              <FieldChips fields={result.inferred.fields} />
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  value={formatName}
                  onChange={(e) => setFormatName(e.target.value)}
                  placeholder="Name this format, e.g. checkout-gateway"
                  className="h-8 max-w-[280px]"
                />
                <Button
                  type="button"
                  size="sm"
                  disabled={
                    saveInferred.isPending || formatName.trim() === "" || savedName !== null
                  }
                  onClick={() => saveInferred.mutate()}
                >
                  {saveInferred.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  Save to Log formats
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={useInferredOnce}>
                  Use once
                </Button>
              </div>
              {saveInferred.isError && (
                <p className="text-xs text-danger">{(saveInferred.error as Error).message}</p>
              )}
              {savedName && (
                <p className="text-xs text-success">
                  Saved <strong>{savedName}</strong> to Log formats. It is applied to this job and
                  can be reused by future jobs.
                </p>
              )}
            </div>
          )}

          {result.candidates.map((candidate) => (
            <CandidateRow
              key={`${candidate.source}-${candidate.id}`}
              candidate={candidate}
              sample={lines[0] ?? ""}
              onApply={(apply, label) => {
                onApply(apply, label);
                setApplied(label);
              }}
            />
          ))}

          {result.candidates.length === 0 && result.json_fields.length > 0 && (
            <div className="space-y-1.5 border border-border p-2.5">
              <p className="text-xs font-medium">JSON keys found</p>
              <FieldChips fields={result.json_fields} />
              <p className="text-[11px] text-muted-foreground">
                No saved pattern parses these lines yet. Save one under{" "}
                <Link href="/log-formats" className="underline">
                  Log formats
                </Link>{" "}
                and it will be reusable here and by every extraction.
              </p>
            </div>
          )}

          {applied && (
            <p className="text-xs text-success">
              Applied <strong>{applied}</strong> — the regex and field boxes below are filled in.
              Adjust them if needed.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
