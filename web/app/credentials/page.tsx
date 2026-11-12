"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, Loader2, Plus, Trash2, XCircle, Zap } from "lucide-react";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FieldGroup, Input, Label, fieldClass } from "@/components/ui/input";
import {
  Credential,
  TokenStatus,
  createCredential,
  deleteCredential,
  listCredentials,
  testCredential,
} from "@/lib/api";

const STATUS_TONE: Record<TokenStatus, "success" | "warning" | "danger" | "neutral"> = {
  valid: "success",
  expiring: "warning",
  expired: "danger",
  unknown: "neutral",
};

export default function CredentialsPage() {
  const qc = useQueryClient();
  const [adding, setAdding] = React.useState(false);

  const {
    data: creds,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["credentials"],
    queryFn: listCredentials,
  });

  return (
    <div className="mx-auto max-w-5xl animate-fade-in px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3 pb-6">
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">Credentials</h1>
          <p className="text-sm text-muted-foreground">
            Last9 refresh tokens, encrypted at rest. Auto-refreshed every 24h; never shown again
            after save.
          </p>
        </div>
        <Button onClick={() => setAdding((v) => !v)} variant={adding ? "outline" : "primary"}>
          <Plus className="h-4 w-4" />
          {adding ? "Cancel" : "Add credential"}
        </Button>
      </div>

      {adding && <AddCredentialForm onDone={() => setAdding(false)} />}

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && (
        <p className="text-sm text-danger">{(error as Error)?.message ?? "Failed to load"}</p>
      )}

      {creds && creds.length === 0 && !adding && <EmptyState onAdd={() => setAdding(true)} />}

      <div className="space-y-3">
        {creds?.map((c) => (
          <CredentialRow
            key={c.id}
            cred={c}
            onChange={() => qc.invalidateQueries({ queryKey: ["credentials"] })}
          />
        ))}
      </div>
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 border border-dashed border-border py-16 text-center">
      <div className="flex h-11 w-11 items-center justify-center bg-muted">
        <KeyRound className="h-5 w-5 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium">No credentials yet</p>
      <p className="max-w-xs text-xs text-muted-foreground">
        Add a Last9 refresh token to start running extractions.
      </p>
      <Button variant="outline" size="sm" onClick={onAdd}>
        Add credential
      </Button>
    </div>
  );
}

function CredentialRow({ cred, onChange }: { cred: Credential; onChange: () => void }) {
  const [flash, setFlash] = React.useState<{ ok: boolean; message: string } | null>(null);

  const test = useMutation({
    mutationFn: () => testCredential(cred.id),
    onSuccess: (r) => {
      setFlash({ ok: r.ok, message: r.message });
      onChange();
    },
    onError: (e: Error) => setFlash({ ok: false, message: e.message }),
  });

  const del = useMutation({
    mutationFn: () => deleteCredential(cred.id),
    onSuccess: onChange,
  });

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-medium">{cred.label}</span>
            <Badge tone={STATUS_TONE[cred.token_status]}>{cred.token_status}</Badge>
            <Badge tone="neutral">{cred.owner_scope}</Badge>
          </div>
          <div className="flex items-center gap-3 font-mono text-xs text-muted-foreground">
            <span>{cred.org_slug}</span>
            <span>token {cred.refresh_token_preview}</span>
          </div>
          {flash && (
            <span
              className={`flex items-center gap-1 text-xs ${flash.ok ? "" : "text-danger"}`}
              style={flash.ok ? { color: "#39c463" } : {}}
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
            size="icon"
            variant="ghost"
            aria-label="Delete credential"
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

function AddCredentialForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = React.useState({
    label: "",
    org_slug: "evergentapse1",
    refresh_token: "",
    owner_scope: "shared" as "shared" | "personal",
  });

  const create = useMutation({
    mutationFn: () => createCredential(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credentials"] });
      onDone();
    },
  });

  const valid = form.label.trim() && form.org_slug.trim() && form.refresh_token.trim();

  return (
    <Card className="mb-6">
      <CardContent className="p-5">
        <form
          className="grid grid-cols-1 gap-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) create.mutate();
          }}
        >
          <Field label="Label">
            <Input
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              placeholder="Production (Singapore)"
            />
          </Field>
          <Field label="Org slug">
            <Input
              value={form.org_slug}
              onChange={(e) => setForm({ ...form, org_slug: e.target.value })}
            />
          </Field>
          <Field label="Refresh token" className="sm:col-span-2">
            <Input
              type="password"
              value={form.refresh_token}
              onChange={(e) => setForm({ ...form, refresh_token: e.target.value })}
              placeholder="Paste the Last9 refresh token"
            />
          </Field>
          <Field label="Scope">
            <select
              className={fieldClass}
              value={form.owner_scope}
              onChange={(e) =>
                setForm({ ...form, owner_scope: e.target.value as "shared" | "personal" })
              }
            >
              <option value="shared">Shared with team</option>
              <option value="personal">Personal</option>
            </select>
          </Field>
          <div className="flex items-end gap-2">
            <Button type="submit" disabled={!valid || create.isPending}>
              {create.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save credential
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
