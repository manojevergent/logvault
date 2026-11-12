"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeftRight,
  CheckCircle2,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  XCircle,
  Zap,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FieldGroup, Input, Label, fieldClass } from "@/components/ui/input";
import {
  NewRelicCredential,
  createNewRelicCredential,
  deleteNewRelicCredential,
  listNewRelicCredentials,
  testNewRelicCredential,
  updateNewRelicCredential,
} from "@/lib/api";

export default function NewRelicPage() {
  const qc = useQueryClient();
  const [adding, setAdding] = React.useState(false);
  const {
    data: creds,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["newrelic-credentials"],
    queryFn: listNewRelicCredentials,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["newrelic-credentials"] });

  return (
    <div className="mx-auto max-w-5xl animate-fade-in px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3 pb-6">
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">New Relic</h1>
          <p className="text-sm text-muted-foreground">
            Account connections used by{" "}
            <Link href="/compare" className="text-primary hover:underline">
              comparisons
            </Link>
            . The user API key is encrypted at rest and never shown again after save.
          </p>
        </div>
        <Button onClick={() => setAdding((v) => !v)} variant={adding ? "outline" : "primary"}>
          <Plus className="h-4 w-4" />
          {adding ? "Cancel" : "Add connection"}
        </Button>
      </div>

      {adding && (
        <AddConnectionForm
          onDone={() => {
            setAdding(false);
            invalidate();
          }}
        />
      )}

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && (
        <p className="text-sm text-danger">{(error as Error)?.message ?? "Failed to load"}</p>
      )}
      {creds && creds.length === 0 && !adding && (
        <div className="flex flex-col items-center gap-3 border border-dashed border-border py-16 text-center">
          <div className="flex h-11 w-11 items-center justify-center bg-muted">
            <Activity className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium">No New Relic connections yet</p>
          <p className="max-w-sm text-xs text-muted-foreground">
            Add an account id and user API key to compare New Relic NRQL results against Last9 over
            the same time window.
          </p>
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
            Add connection
          </Button>
        </div>
      )}

      <div className="space-y-3">
        {creds?.map((cred) => (
          <ConnectionRow key={cred.id} cred={cred} onChange={invalidate} />
        ))}
      </div>

      <div className="mt-6 flex items-center gap-2 border border-border bg-muted/40 px-4 py-3 text-xs text-muted-foreground">
        <ArrowLeftRight className="h-4 w-4 shrink-0" />
        <span>
          Looking for results?{" "}
          <Link href="/compare" className="font-medium text-primary hover:underline">
            Open comparisons
          </Link>{" "}
          to run a saved NRQL query side by side with Last9.
        </span>
      </div>
    </div>
  );
}

function AddConnectionForm({ onDone }: { onDone: () => void }) {
  const [label, setLabel] = React.useState("");
  const [accountId, setAccountId] = React.useState("");
  const [region, setRegion] = React.useState<"us" | "eu">("us");
  const [apiKey, setApiKey] = React.useState("");
  const [flash, setFlash] = React.useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      createNewRelicCredential({
        label: label.trim(),
        account_id: Number(accountId),
        region,
        api_key: apiKey.trim(),
      }),
    onSuccess: onDone,
    onError: (e: Error) => setFlash(e.message),
  });

  return (
    <Card className="mb-4">
      <CardContent className="grid gap-4 p-4 sm:grid-cols-2">
        <FieldGroup>
          <div className="space-y-1.5">
            <Label>Label</Label>
            <Input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. NR production"
            />
          </div>
        </FieldGroup>
        <FieldGroup>
          <div className="space-y-1.5">
            <Label>Account ID</Label>
            <Input
              value={accountId}
              onChange={(e) => setAccountId(e.target.value.replace(/[^0-9]/g, ""))}
              placeholder="e.g. 1234567"
              inputMode="numeric"
            />
          </div>
        </FieldGroup>
        <FieldGroup>
          <div className="space-y-1.5">
            <Label>Region</Label>
            <select
              className={fieldClass}
              value={region}
              onChange={(e) => setRegion(e.target.value as "us" | "eu")}
            >
              <option value="us">US — api.newrelic.com</option>
              <option value="eu">EU — api.eu.newrelic.com</option>
            </select>
          </div>
        </FieldGroup>
        <FieldGroup>
          <div className="space-y-1.5">
            <Label>User API key</Label>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="NRAK-…"
              autoComplete="off"
            />
          </div>
        </FieldGroup>
        <div className="sm:col-span-2 flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            NerdGraph needs a <span className="font-medium">User</span> key (starts with NRAK).
            Ingest and browser keys cannot run NRQL.
          </p>
          <div className="flex items-center gap-2">
            {flash && <span className="text-xs text-danger">{flash}</span>}
            <Button
              onClick={() => save.mutate()}
              disabled={save.isPending || !label.trim() || !accountId || !apiKey.trim()}
            >
              {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save connection
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ConnectionRow({ cred, onChange }: { cred: NewRelicCredential; onChange: () => void }) {
  const [flash, setFlash] = React.useState<{ ok: boolean; message: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [editing, setEditing] = React.useState(false);

  const test = useMutation({
    mutationFn: () => testNewRelicCredential(cred.id),
    onSuccess: (result) => setFlash({ ok: result.ok, message: result.message }),
    onError: (e: Error) => setFlash({ ok: false, message: e.message }),
  });
  const del = useMutation({
    mutationFn: () => deleteNewRelicCredential(cred.id),
    onSuccess: onChange,
    onError: (e: Error) => setFlash({ ok: false, message: e.message }),
  });

  if (editing) {
    return (
      <EditConnectionForm
        cred={cred}
        onDone={() => {
          setEditing(false);
          onChange();
        }}
        onCancel={() => setEditing(false)}
      />
    );
  }

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-medium">{cred.label}</span>
            <Badge tone="neutral">{cred.region.toUpperCase()}</Badge>
            <Badge tone="info">account {cred.account_id}</Badge>
          </div>
          <div className="flex flex-wrap items-center gap-3 font-mono text-xs text-muted-foreground">
            <span>key {cred.api_key_preview}</span>
            {cred.created_by && <span>added by {cred.created_by}</span>}
          </div>
          {flash && (
            <span
              className={`flex items-center gap-1 text-xs ${flash.ok ? "text-success" : "text-danger"}`}
            >
              {flash.ok ? (
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
              ) : (
                <XCircle className="h-3.5 w-3.5 shrink-0" />
              )}
              {flash.message}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => test.mutate()}
            disabled={test.isPending}
          >
            {test.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Zap className="h-3.5 w-3.5" />
            )}
            Test
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setEditing(true)}
            disabled={confirmDelete}
          >
            <Pencil className="h-3.5 w-3.5" />
            Edit
          </Button>
          {confirmDelete ? (
            <>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="text-danger"
                onClick={() => del.mutate()}
                disabled={del.isPending}
              >
                {del.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Delete
              </Button>
            </>
          ) : (
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Delete ${cred.label}`}
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="h-4 w-4 text-danger" />
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function EditConnectionForm({
  cred,
  onDone,
  onCancel,
}: {
  cred: NewRelicCredential;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [label, setLabel] = React.useState(cred.label);
  const [accountId, setAccountId] = React.useState(String(cred.account_id));
  const [region, setRegion] = React.useState<"us" | "eu">(cred.region === "eu" ? "eu" : "us");
  const [apiKey, setApiKey] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      updateNewRelicCredential(cred.id, {
        label: label.trim(),
        account_id: Number(accountId),
        region,
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      }),
    onSuccess: onDone,
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium">Edit New Relic connection</p>
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <FieldGroup>
            <div className="space-y-1.5">
              <Label>Label</Label>
              <Input value={label} onChange={(e) => setLabel(e.target.value)} />
            </div>
          </FieldGroup>
          <FieldGroup>
            <div className="space-y-1.5">
              <Label>Account ID</Label>
              <Input
                value={accountId}
                onChange={(e) => setAccountId(e.target.value.replace(/[^0-9]/g, ""))}
                inputMode="numeric"
              />
            </div>
          </FieldGroup>
          <FieldGroup>
            <div className="space-y-1.5">
              <Label>Region</Label>
              <select
                className={fieldClass}
                value={region}
                onChange={(e) => setRegion(e.target.value as "us" | "eu")}
              >
                <option value="us">US — api.newrelic.com</option>
                <option value="eu">EU — api.eu.newrelic.com</option>
              </select>
            </div>
          </FieldGroup>
          <FieldGroup>
            <div className="space-y-1.5">
              <Label>New API key (optional)</Label>
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={`leave blank to keep ${cred.api_key_preview}`}
                autoComplete="off"
              />
            </div>
          </FieldGroup>
        </div>
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            Existing comparisons keep pointing at this connection and will use the new account/key
            on their next run.
          </p>
          <div className="flex items-center gap-2">
            {error && <span className="text-xs text-danger">{error}</span>}
            <Button
              onClick={() => save.mutate()}
              disabled={save.isPending || !label.trim() || !accountId}
            >
              {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save changes
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
