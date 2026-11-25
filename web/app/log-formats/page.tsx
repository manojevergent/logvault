"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCode2, FileDown, Loader2, Pencil, Plus, Power, Trash2, Upload } from "lucide-react";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label, fieldClass } from "@/components/ui/input";
import {
  LogFormat,
  LogFormatInput,
  createLogFormat,
  deleteLogFormat,
  downloadJson,
  listLogFormats,
  testLogFormat,
  updateLogFormat,
} from "@/lib/api";

export default function LogFormatsPage() {
  const qc = useQueryClient();
  const [adding, setAdding] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [importing, setImporting] = React.useState(false);
  const [importErr, setImportErr] = React.useState("");

  const { data: formats, isLoading } = useQuery({
    queryKey: ["log-formats"],
    queryFn: listLogFormats,
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["log-formats"] });

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportErr("");
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const items: LogFormatInput[] = Array.isArray(parsed) ? parsed : [parsed];
      const failed: string[] = [];
      let created = 0;
      for (const item of items) {
        if (!item?.name || !item?.regex) continue;
        try {
          await createLogFormat({
            name: item.name,
            regex: item.regex,
            hint: item.hint ?? "",
            sample_line: item.sample_line ?? "",
            priority: item.priority ?? 100,
            enabled: item.enabled ?? true,
            description: item.description ?? "",
          });
          created += 1;
        } catch (err) {
          failed.push(`${item.name}: ${(err as Error).message}`);
        }
      }
      invalidate();
      if (failed.length) {
        setImportErr(
          `${created} imported, ${failed.length} failed — ${failed.slice(0, 3).join("; ")}` +
            (failed.length > 3 ? `; and ${failed.length - 3} more` : "")
        );
      }
    } catch (err) {
      setImportErr((err as Error).message);
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <div className="mx-auto max-w-5xl animate-fade-in px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3 pb-6">
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">Log formats</h1>
          <p className="text-sm text-muted-foreground">
            Named parse patterns. A job set to use the library tries every enabled format against
            each row until one matches — so one job can span many log shapes.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {formats && formats.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                downloadJson(
                  "logvault_log_formats.json",
                  formats.map((f) => ({
                    name: f.name,
                    regex: f.regex,
                    hint: f.hint,
                    sample_line: f.sample_line,
                    priority: f.priority,
                    enabled: f.enabled,
                    description: f.description,
                  }))
                )
              }
              title="Export all log formats as JSON"
            >
              <FileDown className="h-4 w-4" /> Export
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            type="button"
            disabled={importing}
            onClick={() => fileInputRef.current?.click()}
          >
            {importing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Upload className="h-4 w-4" />
            )}
            Import
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleImport}
            disabled={importing}
          />
          <Button onClick={() => setAdding((v) => !v)} variant={adding ? "outline" : "primary"}>
            <Plus className="h-4 w-4" />
            {adding ? "Cancel" : "New format"}
          </Button>
        </div>
      </div>

      {importErr && <p className="mb-4 text-xs text-danger">{importErr}</p>}

      {adding && <FormatForm onDone={() => { setAdding(false); invalidate(); }} />}

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {formats && formats.length === 0 && !adding && (
        <div className="flex flex-col items-center gap-3 border border-dashed border-border py-16 text-center">
          <div className="flex h-11 w-11 items-center justify-center bg-muted">
            <FileCode2 className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium">No log formats yet</p>
          <p className="max-w-md text-xs text-muted-foreground">
            Add one per log shape. Give the same named group (say <code>cpid</code>) to the same
            field in every format, and one aggregation counts across all of them.
          </p>
        </div>
      )}

      <div className="space-y-3">
        {formats?.map((f) => (
          <FormatRow key={f.id} f={f} onChange={invalidate} />
        ))}
      </div>
    </div>
  );
}

function FormatRow({ f, onChange }: { f: LogFormat; onChange: () => void }) {
  const [editing, setEditing] = React.useState(false);
  const del = useMutation({ mutationFn: () => deleteLogFormat(f.id), onSuccess: onChange });
  const toggle = useMutation({
    mutationFn: () =>
      updateLogFormat(f.id, {
        name: f.name,
        regex: f.regex,
        hint: f.hint ?? "",
        sample_line: f.sample_line ?? "",
        priority: f.priority,
        enabled: !f.enabled,
        description: f.description ?? "",
      }),
    onSuccess: onChange,
  });

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <span className="font-medium">{f.name}</span>
              <Badge tone={f.enabled ? "success" : "neutral"}>{f.enabled ? "on" : "off"}</Badge>
              <Badge tone="info">priority {f.priority}</Badge>
              {f.hint && <Badge tone="neutral">hint: {f.hint}</Badge>}
            </div>
            <p className="truncate font-mono text-xs text-muted-foreground">{f.regex}</p>
            {f.description && <p className="text-xs text-muted-foreground">{f.description}</p>}
          </div>
          <div className="flex items-center gap-2">
            <Button size="icon" variant="ghost" aria-label="Edit format" onClick={() => setEditing((v) => !v)}>
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button size="sm" variant="outline" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
              <Power className="h-3.5 w-3.5" /> {f.enabled ? "Disable" : "Enable"}
            </Button>
            <Button size="icon" variant="ghost" aria-label="Delete format" onClick={() => del.mutate()} disabled={del.isPending}>
              <Trash2 className="h-4 w-4 text-danger" />
            </Button>
          </div>
        </div>
        {editing && (
          <FormatForm
            existing={f}
            onDone={() => {
              setEditing(false);
              onChange();
            }}
          />
        )}
        {del.isError && <p className="mt-2 text-xs text-danger">{(del.error as Error).message}</p>}
      </CardContent>
    </Card>
  );
}

function FormatForm({ existing, onDone }: { existing?: LogFormat; onDone: () => void }) {
  const [f, setF] = React.useState<LogFormatInput>({
    name: existing?.name ?? "",
    regex: existing?.regex ?? "",
    hint: existing?.hint ?? "",
    sample_line: existing?.sample_line ?? "",
    priority: existing?.priority ?? 100,
    enabled: existing?.enabled ?? true,
    description: existing?.description ?? "",
  });

  // Try the pattern before saving — building a regex blind against production
  // logs is what turns a wrong one into a job that reports 0 rows matched.
  const probe = useMutation({
    mutationFn: () =>
      testLogFormat({ regex: f.regex, sample_line: f.sample_line ?? "", hint: f.hint }),
  });

  const save = useMutation({
    mutationFn: () => (existing ? updateLogFormat(existing.id, f) : createLogFormat(f)),
    onSuccess: onDone,
  });

  const canSave = f.name.trim() !== "" && f.regex.trim() !== "";

  return (
    <div className={`grid grid-cols-1 gap-4 sm:grid-cols-2 ${existing ? "mt-4 border-t border-border pt-4" : "mb-6 border border-border p-5"}`}>
      <div className="space-y-1.5">
        <Label>Name</Label>
        <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="ABSCBN getContact" />
      </div>
      <div className="space-y-1.5">
        <Label>Priority (lower is tried first)</Label>
        <Input
          type="number"
          value={f.priority}
          onChange={(e) => setF({ ...f, priority: Number(e.target.value) })}
        />
      </div>
      <div className="space-y-1.5 sm:col-span-2">
        <Label>Pattern — named groups become the fields</Label>
        <textarea
          className={`${fieldClass} h-24 py-2 font-mono text-xs`}
          value={f.regex}
          onChange={(e) => setF({ ...f, regex: e.target.value })}
          placeholder="<cpCustomerID>(?<cpid>[^<]*)</cpCustomerID>"
        />
        <p className="text-xs text-muted-foreground">
          Use the same group name across formats for the same field — that&apos;s what lets one
          aggregation count across every log shape.
        </p>
      </div>
      <div className="space-y-1.5 sm:col-span-2">
        <Label>Match hint (optional, but makes a big library fast)</Label>
        <Input
          value={f.hint}
          onChange={(e) => setF({ ...f, hint: e.target.value })}
          placeholder="cpCustomerID"
        />
        <p className="text-xs text-muted-foreground">
          A literal every line of this format contains. Checked before the regex runs, so formats
          that can&apos;t match are ruled out cheaply.
        </p>
      </div>
      <div className="space-y-1.5 sm:col-span-2">
        <Label>Sample log line</Label>
        <textarea
          className={`${fieldClass} h-16 py-2 font-mono text-xs`}
          value={f.sample_line}
          onChange={(e) => setF({ ...f, sample_line: e.target.value })}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
        <Button
          size="sm"
          variant="outline"
          disabled={!f.regex.trim() || !f.sample_line?.trim() || probe.isPending}
          onClick={() => probe.mutate()}
        >
          {probe.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Test against sample
        </Button>
        <Button size="sm" disabled={!canSave || save.isPending} onClick={() => save.mutate()}>
          {save.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {existing ? "Save changes" : "Create format"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        {save.isError && <span className="text-xs text-danger">{(save.error as Error).message}</span>}
      </div>
      {probe.data && (
        <div className="sm:col-span-2">
          {probe.data.matched ? (
            <div className="space-y-1 border border-border p-3">
              <p className="text-xs font-medium text-success">Matched — extracted fields:</p>
              <table className="text-xs">
                <tbody>
                  {Object.entries(probe.data.fields).map(([k, v]) => (
                    <tr key={k}>
                      <td className="pr-4 font-mono text-muted-foreground">{k}</td>
                      <td className="font-mono">{v || <span className="opacity-40">(empty)</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-danger">
              {probe.data.error ?? "Did not match this line."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
