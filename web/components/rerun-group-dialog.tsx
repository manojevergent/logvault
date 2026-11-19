"use client";

import { Loader2 } from "lucide-react";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, fieldClass } from "@/components/ui/input";
import { GroupDetail, GroupRerunInput } from "@/lib/api";
import { Tz, epochToLocal, formatEpoch, localToEpoch } from "@/lib/time";

const MAX_GROUP = 50;
const field = "space-y-1";

/**
 * Re-run a group under edited settings.
 *
 * The window and run settings are editable; the searches keep the filter each
 * job actually ran with, because the point is repeating this run, not
 * rebuilding the saved searches. The original group is never modified — the
 * server creates a new group pointing back at it.
 */
export function RerunGroupDialog({
  open,
  group,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  open: boolean;
  group: GroupDetail;
  pending: boolean;
  error: string | null;
  onSubmit: (body: GroupRerunInput) => void;
  onCancel: () => void;
}) {
  const id = React.useId();
  const nameRef = React.useRef<HTMLInputElement>(null);

  const [name, setName] = React.useState("");
  const [start, setStart] = React.useState("");
  const [end, setEnd] = React.useState("");
  const [chunkHours, setChunkHours] = React.useState(1);
  const [batchSize, setBatchSize] = React.useState(100);
  const [format, setFormat] = React.useState<"csv" | "jsonl">("csv");
  const [preview, setPreview] = React.useState(false);
  const [selected, setSelected] = React.useState<Set<number>>(new Set());

  // Re-seed from the group each time the dialog opens, so a cancelled edit
  // never leaks into the next one.
  React.useEffect(() => {
    if (!open) return;
    setName(`${group.name} (re-run)`.slice(0, 160));
    setStart(epochToLocal(group.start_epoch, "UTC" as Tz));
    setEnd(epochToLocal(group.end_epoch, "UTC" as Tz));
    setChunkHours(group.chunk_hours);
    setBatchSize(group.id_batch_size);
    setFormat(group.output_format === "jsonl" ? "jsonl" : "csv");
    setPreview(group.is_preview);
    setSelected(new Set(group.jobs.map((job) => job.id)));
  }, [open, group]);

  React.useEffect(() => {
    if (!open) return;
    nameRef.current?.focus();
    nameRef.current?.select();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !pending) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, pending, onCancel]);

  if (!open) return null;

  const startEpoch = localToEpoch(start, "UTC" as Tz);
  const endEpoch = localToEpoch(end, "UTC" as Tz);
  const validWindow =
    Number.isFinite(startEpoch) && Number.isFinite(endEpoch) && endEpoch > startEpoch;
  const validChunk = Number.isFinite(chunkHours) && chunkHours >= 1;
  const validBatch = Number.isFinite(batchSize) && batchSize >= 1;
  const validCount = selected.size > 0 && selected.size <= MAX_GROUP;
  const valid = validWindow && validChunk && validBatch && validCount && !pending;

  function toggle(jobId: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }

  function submit() {
    if (!valid) return;
    onSubmit({
      name: name.trim(),
      start_epoch: startEpoch,
      end_epoch: endEpoch,
      chunk_hours: chunkHours,
      id_batch_size: batchSize,
      output_format: format,
      is_preview: preview,
      job_ids: group.jobs.filter((job) => selected.has(job.id)).map((job) => job.id),
    });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/45 p-4 sm:items-center"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !pending) onCancel();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        className="my-auto w-full max-w-2xl border border-border bg-card shadow-card-hover"
      >
        <div className="border-b border-border p-4">
          <h2 id={`${id}-title`} className="text-base font-semibold text-foreground">
            Re-run with edits
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Creates a new group from <strong className="text-foreground">{group.name}</strong>.
            The original run, its files and job history stay intact.
          </p>
        </div>

        <div className="max-h-[65vh] space-y-4 overflow-y-auto p-4">
          <div className={field}>
            <Label htmlFor={`${id}-name`}>Group name</Label>
            <Input
              ref={nameRef}
              id={`${id}-name`}
              value={name}
              maxLength={160}
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className={field}>
              <Label htmlFor={`${id}-start`}>Start (UTC)</Label>
              <Input
                id={`${id}-start`}
                type="datetime-local"
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </div>
            <div className={field}>
              <Label htmlFor={`${id}-end`}>End (UTC)</Label>
              <Input
                id={`${id}-end`}
                type="datetime-local"
                value={end}
                onChange={(event) => setEnd(event.target.value)}
              />
            </div>
          </div>
          <p
            className={`font-mono text-[11px] ${validWindow ? "text-muted-foreground" : "text-danger"}`}
          >
            {validWindow
              ? `${formatEpoch(startEpoch)} → ${formatEpoch(endEpoch)} UTC`
              : "End must be after start."}
          </p>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className={field}>
              <Label htmlFor={`${id}-chunk`}>Chunk hours</Label>
              <Input
                id={`${id}-chunk`}
                type="number"
                min={1}
                value={chunkHours}
                onChange={(event) => setChunkHours(Number(event.target.value))}
              />
            </div>
            <div className={field}>
              <Label htmlFor={`${id}-batch`}>ID batch size</Label>
              <Input
                id={`${id}-batch`}
                type="number"
                min={1}
                value={batchSize}
                onChange={(event) => setBatchSize(Number(event.target.value))}
              />
            </div>
            <div className={field}>
              <Label htmlFor={`${id}-format`}>Output format</Label>
              <select
                id={`${id}-format`}
                className={fieldClass}
                value={format}
                onChange={(event) => setFormat(event.target.value as "csv" | "jsonl")}
              >
                <option value="csv">CSV</option>
                <option value="jsonl">JSONL</option>
              </select>
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={preview}
              onChange={(event) => setPreview(event.target.checked)}
            />
            Preview — sample up to 100 rows per search instead of the full window
          </label>

          <div>
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium">
                Searches{" "}
                <Badge tone={selected.size ? "info" : "neutral"}>{selected.size} selected</Badge>
              </p>
              <div className="flex items-center gap-2 text-xs">
                <button
                  type="button"
                  className="text-primary hover:underline"
                  onClick={() => setSelected(new Set(group.jobs.map((job) => job.id)))}
                >
                  Select all
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
            <div className="mt-2 divide-y divide-border/60 border border-border/60">
              {group.jobs.map((job) => (
                <label
                  key={job.id}
                  className="flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm hover:bg-accent/40"
                >
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={selected.has(job.id)}
                    onChange={() => toggle(job.id)}
                    aria-label={`Re-run ${job.filter_spec.label || `job ${job.id}`}`}
                  />
                  <span className="min-w-0 flex-1 truncate">
                    {job.filter_spec.label || `Job #${job.id}`}
                    {job.filter_spec.customer ? (
                      <span className="ml-1 text-xs text-muted-foreground">
                        · {job.filter_spec.customer}
                      </span>
                    ) : null}
                  </span>
                  <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                    {job.status}
                  </span>
                </label>
              ))}
            </div>
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              Each search keeps the filter it ran with here. To change a filter, edit the saved
              search and start a new group.
            </p>
          </div>

          {!validCount && (
            <p className="text-xs text-danger">Select at least one search to re-run.</p>
          )}
          {error && <p className="text-xs text-danger">{error}</p>}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border p-3">
          <Button variant="ghost" onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!valid}>
            {pending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Re-run {selected.size} search{selected.size === 1 ? "" : "es"}
          </Button>
        </div>
      </div>
    </div>
  );
}
