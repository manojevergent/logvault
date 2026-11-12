"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Database, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label, fieldClass } from "@/components/ui/input";
import {
  IndexTarget,
  Region,
  createIndex,
  listCredentials,
  deleteIndex,
  listIndexes,
  listRegions,
  updateIndex,
} from "@/lib/api";

export default function IndexesPage() {
  const qc = useQueryClient();
  const [adding, setAdding] = React.useState(false);
  const [filter, setFilter] = React.useState("");

  const { data: regions } = useQuery({ queryKey: ["regions"], queryFn: listRegions });
  const { data: indexes, isLoading } = useQuery({
    queryKey: ["indexes", filter],
    queryFn: () => listIndexes(filter || undefined),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["indexes"] });
  const regionLabel = (code: string) => regions?.find((r) => r.code === code)?.label ?? code;

  return (
    <div className="mx-auto max-w-5xl animate-fade-in px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3 pb-6">
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">Indexes</h1>
          <p className="text-sm text-muted-foreground">
            Named index targets scoped to a region. The full string is derived as{" "}
            <span className="font-mono">physical_index:&lt;name&gt;</span> — or leave
            the index blank to query the org&rsquo;s Default index.
          </p>
        </div>
        <Button onClick={() => setAdding((v) => !v)} variant={adding ? "outline" : "primary"}>
          <Plus className="h-4 w-4" />
          {adding ? "Cancel" : "New index"}
        </Button>
      </div>

      {adding && regions && <AddIndexForm regions={regions} onDone={() => setAdding(false)} />}

      <div className="flex items-center gap-2 pb-4">
        <Label>Region</Label>
        <select
          className={`${fieldClass} max-w-xs`}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="">All regions</option>
          {regions?.map((r) => (
            <option key={r.code} value={r.code}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {indexes && indexes.length === 0 && (
        <div className="flex flex-col items-center gap-3 border border-dashed border-border py-16 text-center">
          <div className="flex h-11 w-11 items-center justify-center bg-muted">
            <Database className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium">No indexes {filter && `in ${regionLabel(filter)}`}</p>
        </div>
      )}

      <div className="space-y-3">
        {indexes?.map((idx) => (
          <IndexRow
            key={idx.id}
            idx={idx}
            regionLabel={regionLabel(idx.region_code)}
            onChange={invalidate}
          />
        ))}
      </div>
    </div>
  );
}

function IndexRow({
  idx,
  regionLabel,
  onChange,
}: {
  idx: IndexTarget;
  regionLabel: string;
  onChange: () => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [confirmDel, setConfirmDel] = React.useState(false);
  const [name, setName] = React.useState(idx.name);
  const [physical, setPhysical] = React.useState(idx.physical_index ?? idx.name);
  const [useDefault, setUseDefault] = React.useState(!idx.full_index_string);
  const [credentialId, setCredentialId] = React.useState<number | "">(idx.credential_id ?? "");
  const [description, setDescription] = React.useState(idx.description ?? "");
  const { data: credentials } = useQuery({ queryKey: ["credentials"], queryFn: listCredentials });

  const save = useMutation({
    mutationFn: () =>
      updateIndex(idx.id, {
        name,
        // Blank selects the org's Default index; otherwise a blank falls back
        // to the label, as before.
        physical_index: useDefault ? "" : physical.trim() || name.trim(),
        credential_id: credentialId === "" ? null : Number(credentialId),
        description,
      }),
    onSuccess: () => {
      setEditing(false);
      onChange();
    },
  });
  const del = useMutation({ mutationFn: () => deleteIndex(idx.id), onSuccess: onChange });

  if (editing) {
    return (
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex-1 space-y-1.5">
            <Label>Description</Label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Last9 index</Label>
            <Input
              value={physical}
              onChange={(e) => setPhysical(e.target.value)}
              disabled={useDefault}
              placeholder={useDefault ? "Default (org default)" : undefined}
            />
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={useDefault}
                onChange={(e) => setUseDefault(e.target.checked)}
                className="h-3.5 w-3.5"
              />
              Query the org&rsquo;s Default index
            </label>
          </div>
          <div className="space-y-1.5">
            <Label>Credential</Label>
            <select
              className={fieldClass}
              value={credentialId}
              onChange={(e) => setCredentialId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Ask each time…</option>
              {credentials?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label} ({c.org_slug})
                </option>
              ))}
            </select>
          </div>
          <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
            <Check className="h-3.5 w-3.5" /> Save
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
            <X className="h-3.5 w-3.5" /> Cancel
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-medium">{idx.name}</span>
            <Badge tone="info">{regionLabel}</Badge>
          </div>
          <p className="font-mono text-xs text-muted-foreground">
            {idx.full_index_string || "(org default index — no index parameter sent)"}
          </p>
          <p className="font-mono text-xs text-muted-foreground">
            index{" "}
            {idx.physical_index || (idx.full_index_string ? idx.name : "Default (org default)")}
            {idx.credential_label ? ` · ${idx.credential_label}` : " · no credential set"}
          </p>
          {idx.description && <p className="text-xs text-muted-foreground">{idx.description}</p>}
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="icon"
            variant="ghost"
            aria-label="Edit index"
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
              aria-label="Delete index"
              title="Delete this index target"
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

function AddIndexForm({ regions, onDone }: { regions: Region[]; onDone: () => void }) {
  const qc = useQueryClient();
  const { data: credentials } = useQuery({ queryKey: ["credentials"], queryFn: listCredentials });
  const [form, setForm] = React.useState({
    name: "",
    region_code: regions[0]?.code ?? "",
    physical_index: "",
    credential_id: "" as number | "",
    description: "",
  });
  const [useDefault, setUseDefault] = React.useState(false);

  const create = useMutation({
    mutationFn: () =>
      createIndex({
        ...form,
        // Default-index targets send a blank; otherwise a blank still means
        // "same as the label", as before.
        physical_index: useDefault ? "" : form.physical_index.trim() || form.name.trim(),
        credential_id: form.credential_id === "" ? null : Number(form.credential_id),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["indexes"] });
      onDone();
    },
  });

  return (
    <Card className="mb-6">
      <CardContent className="p-5">
        <form
          className="grid grid-cols-1 gap-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (form.name.trim()) create.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="UMS_india"
            />
            <p className="text-xs text-muted-foreground">
              What you pick from when starting a job.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>Region</Label>
            <select
              className={fieldClass}
              value={form.region_code}
              onChange={(e) => setForm({ ...form, region_code: e.target.value })}
            >
              {regions.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label>Last9 index</Label>
            <Input
              value={form.physical_index}
              onChange={(e) => setForm({ ...form, physical_index: e.target.value })}
              placeholder="UMServices"
              disabled={useDefault}
            />
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={useDefault}
                onChange={(e) => setUseDefault(e.target.checked)}
                className="h-3.5 w-3.5"
              />
              Query the org&rsquo;s Default index instead
            </label>
            <p className="text-xs text-muted-foreground">
              The real index name. Defaults to the label; keep them separate so
              renaming the label can&rsquo;t repoint the source.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>Credential</Label>
            <select
              className={fieldClass}
              value={form.credential_id}
              onChange={(e) =>
                setForm({ ...form, credential_id: e.target.value ? Number(e.target.value) : "" })
              }
            >
              <option value="">Ask each time…</option>
              {credentials?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label} ({c.org_slug})
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              Set it here and a job never asks for one.
            </p>
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label>Description (optional)</Label>
            <Input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>
          <div>
            <Button type="submit" disabled={!form.name.trim() || create.isPending}>
              {create.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Create source
            </Button>
          </div>
          {create.isError && (
            <p className="text-xs text-danger sm:col-span-2">{(create.error as Error).message}</p>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
