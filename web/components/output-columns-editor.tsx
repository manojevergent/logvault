"use client";

import * as React from "react";
import { Label } from "@/components/ui/input";

// Canonical uniform invoice layout. Every extract — whatever log shape it
// parses — emits these headers in this order, so per-customer CSVs are
// directly comparable without renaming columns in Excel.
export const UNIFORM_TIMESTAMP_HEADER = "timestamp";
export const UNIFORM_LABELS: Record<string, string> = {
  api: "api",
  account_id: "spAccountID",
  channel_partner: "channelPartnerID",
  bu_name: "bu_name",
};

// A regex group name belongs to a uniform slot when it looks like one of
// these (case-insensitive, underscores ignored). First match wins, in
// api → account → channel → bu order, so e.g. "channel_spid" still lands in
// the account slot rather than channel.
const SLOT_PATTERNS: { slot: string; seq: number; match: RegExp }[] = [
  { slot: "api", seq: 1, match: /^(api|action|apiname|operation)$/ },
  {
    slot: "account_id",
    seq: 2,
    match: /(spid|spaccount|cpcustomer|customerid|accountid|cpid|trackerid)/,
  },
  {
    slot: "channel_partner",
    seq: 3,
    match: /(channelpartner|channel_partner|channelid)/,
  },
  { slot: "bu_name", seq: 4, match: /^(bu|buid|buname|businessunit)$|^bu/ },
];

export type ColumnLayout = {
  /** Fields in output order (sequence 1..N). */
  rawColumns: string[];
  /** Regex group name -> uniform CSV header. */
  columnLabels: Record<string, string>;
  /** Regex group name -> literal fallback when a row has no value. */
  columnDefaults: Record<string, string>;
  /** Header text for the timestamp column. */
  timestampColumn: string;
};

function norm(s: string): string {
  return s.toLowerCase().replace(/_/g, "");
}

function slotFor(field: string): { slot: string; seq: number } | null {
  const n = norm(field);
  for (const { slot, seq, match } of SLOT_PATTERNS) {
    if (match.test(n)) return { slot, seq };
  }
  return null;
}

/** Suggest a uniform order + labels for whatever fields a regex defines. */
export function suggestUniformLayout(fields: string[]): ColumnLayout {
  const ranked = fields.map((f, i) => {
    const slot = slotFor(f);
    return { field: f, seq: slot?.seq ?? 10 + i, label: slot ? UNIFORM_LABELS[slot.slot] : f };
  });
  ranked.sort((a, b) => a.seq - b.seq || fields.indexOf(a.field) - fields.indexOf(b.field));
  const columnLabels: Record<string, string> = {};
  for (const r of ranked) {
    if (r.label !== r.field) columnLabels[r.field] = r.label;
  }
  return {
    rawColumns: ranked.map((r) => r.field),
    columnLabels,
    columnDefaults: {},
    timestampColumn: UNIFORM_TIMESTAMP_HEADER,
  };
}

/** Order fields by an explicit seq map (1-based numbers the user typed).
 *  Ties and missing entries fall back to the given field order, so a half-
 *  filled column of numbers still produces a stable, sensible order. */
export function orderBySeq(fields: string[], seq: Record<string, number>): string[] {
  return [...fields].sort((a, b) => {
    const sa = seq[a] ?? Number.MAX_SAFE_INTEGER;
    const sb = seq[b] ?? Number.MAX_SAFE_INTEGER;
    if (sa !== sb) return sa - sb;
    return fields.indexOf(a) - fields.indexOf(b);
  });
}

export function OutputColumnsEditor({
  fields,
  included,
  seq,
  labels,
  defaults,
  timestampColumn,
  sampleValues,
  onToggle,
  onSeq,
  onLabel,
  onDefault,
  onTimestampColumn,
  onApplyUniform,
}: {
  /** All fields the regex (or library) defines, in definition order. */
  fields: string[];
  /** Fields currently included in the output. */
  included: Set<string>;
  /** Field -> sequence number (1-based output position). */
  seq: Record<string, number>;
  /** Field -> uniform header override. */
  labels: Record<string, string>;
  /** Field -> fallback literal for rows with no value. */
  defaults: Record<string, string>;
  timestampColumn: string;
  /** Field -> example value from the sample line, if any. */
  sampleValues?: Record<string, string> | null;
  onToggle: (field: string) => void;
  onSeq: (field: string, seq: number | null) => void;
  onLabel: (field: string, label: string) => void;
  onDefault: (field: string, value: string) => void;
  onTimestampColumn: (v: string) => void;
  onApplyUniform: () => void;
}) {
  const ordered = React.useMemo(() => orderBySeq(fields, seq), [fields, seq]);

  if (fields.length === 0) return null;

  return (
    <div className="space-y-3 border-t border-border pt-3 sm:col-span-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>Output columns — tick, number the sequence, name the header</Label>
        <button
          type="button"
          className="text-xs text-primary underline"
          onClick={onApplyUniform}
          title="Order api → account → channel → bu and rename headers to the uniform invoice layout"
        >
          Apply uniform invoice order
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        Sequence 1 is the first column after {timestampColumn || "timestamp"}. The header is what
        lands in the CSV — give the same header everywhere and every extract lines up.
      </p>
      <div className="overflow-auto border border-border">
        <table className="w-full text-left text-xs">
          <thead className="bg-muted text-muted-foreground">
            <tr>
              <th className="px-2 py-1 font-medium">Include</th>
              <th className="px-2 py-1 font-medium">Seq</th>
              <th className="px-2 py-1 font-medium">Field</th>
              <th className="px-2 py-1 font-medium">CSV header</th>
              <th className="px-2 py-1 font-medium">Empty-value default</th>
              {sampleValues && <th className="px-2 py-1 font-medium">Sample</th>}
            </tr>
          </thead>
          <tbody>
            {ordered.map((f) => (
              <tr key={f} className="border-t border-border">
                <td className="px-2 py-1">
                  <input
                    type="checkbox"
                    checked={included.has(f)}
                    onChange={() => onToggle(f)}
                    className="h-3.5 w-3.5"
                    aria-label={`Include ${f}`}
                  />
                </td>
                <td className="px-2 py-1">
                  <input
                    type="number"
                    min={1}
                    max={fields.length}
                    value={seq[f] ?? ""}
                    placeholder="—"
                    onChange={(e) => {
                      const v = e.target.value === "" ? null : Math.max(1, Number(e.target.value));
                      onSeq(f, Number.isFinite(v as number) ? (v as number) : null);
                    }}
                    className="h-7 w-14 border border-input bg-background px-1.5 text-xs"
                    aria-label={`Sequence for ${f}`}
                  />
                </td>
                <td className="px-2 py-1 font-mono">{f}</td>
                <td className="px-2 py-1">
                  <input
                    value={labels[f] ?? ""}
                    placeholder={f}
                    onChange={(e) => onLabel(f, e.target.value)}
                    className="h-7 w-36 border border-input bg-background px-1.5 font-mono text-xs"
                    aria-label={`CSV header for ${f}`}
                  />
                </td>
                <td className="px-2 py-1">
                  <input
                    value={defaults[f] ?? ""}
                    placeholder="(blank)"
                    onChange={(e) => onDefault(f, e.target.value)}
                    className="h-7 w-24 border border-input bg-background px-1.5 font-mono text-xs"
                    aria-label={`Empty default for ${f}`}
                  />
                </td>
                {sampleValues && (
                  <td className="px-2 py-1 font-mono text-muted-foreground">
                    {sampleValues[f] ?? "(no match)"}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Label>Timestamp header</Label>
        <input
          value={timestampColumn}
          onChange={(e) => onTimestampColumn(e.target.value)}
          placeholder="timestamp"
          className="h-7 w-40 border border-input bg-background px-1.5 font-mono text-xs"
        />
      </div>
    </div>
  );
}
