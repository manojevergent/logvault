"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  CloudUpload,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  XCircle,
  Zap,
} from "lucide-react";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FieldGroup, Input, Label, fieldClass } from "@/components/ui/input";
import {
  S3Profile,
  createS3Profile,
  deleteS3Profile,
  listS3Profiles,
  testS3Profile,
  updateS3Profile,
} from "@/lib/api";

export default function S3ProfilesPage() {
  const qc = useQueryClient();
  const [adding, setAdding] = React.useState(false);
  const {
    data: profiles,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["s3-profiles"],
    queryFn: listS3Profiles,
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["s3-profiles"] });

  return (
    <div className="mx-auto max-w-5xl animate-fade-in px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3 pb-6">
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">S3 destinations</h1>
          <p className="text-sm text-muted-foreground">
            Reusable bucket profiles for scheduled and one-off extracts. A saved search or schedule
            can pick one; each completed run uploads its final artifacts there.
          </p>
        </div>
        <Button onClick={() => setAdding((v) => !v)} variant={adding ? "outline" : "primary"}>
          <Plus className="h-4 w-4" />
          {adding ? "Cancel" : "New S3 profile"}
        </Button>
      </div>

      {adding && (
        <S3ProfileForm
          onCancel={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            invalidate();
          }}
        />
      )}

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && (
        <p className="text-sm text-danger">{(error as Error)?.message ?? "Failed to load"}</p>
      )}
      {profiles && profiles.length === 0 && !adding && (
        <div className="flex flex-col items-center gap-3 border border-dashed border-border py-16 text-center">
          <div className="flex h-11 w-11 items-center justify-center bg-muted">
            <CloudUpload className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium">No S3 destinations yet</p>
          <p className="max-w-md text-xs text-muted-foreground">
            Add a bucket profile, then select it on a saved search or schedule. Leave the keys blank
            to use the worker&rsquo;s IAM role.
          </p>
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
            Add the first profile
          </Button>
        </div>
      )}

      <div className="space-y-3">
        {profiles?.map((profile) => (
          <S3ProfileRow key={profile.id} profile={profile} onChange={invalidate} />
        ))}
      </div>
    </div>
  );
}

function S3ProfileForm({
  profile,
  onCancel,
  onSaved,
}: {
  profile?: S3Profile;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = React.useState(profile?.name ?? "");
  const [bucket, setBucket] = React.useState(profile?.bucket ?? "");
  const [region, setRegion] = React.useState(profile?.region ?? "us-east-1");
  const [prefix, setPrefix] = React.useState(profile?.prefix ?? "");
  const [endpoint, setEndpoint] = React.useState(profile?.endpoint_url ?? "");
  const [accessKey, setAccessKey] = React.useState("");
  const [secretKey, setSecretKey] = React.useState("");
  const [sessionToken, setSessionToken] = React.useState("");
  const [forcePathStyle, setForcePathStyle] = React.useState(profile?.force_path_style ?? false);
  const [clearCredentials, setClearCredentials] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim(),
        bucket: bucket.trim(),
        region: region.trim() || "us-east-1",
        prefix: prefix.trim(),
        endpoint_url: endpoint.trim() || null,
        force_path_style: forcePathStyle,
      };
      if (profile) {
        return updateS3Profile(profile.id, {
          ...body,
          ...(accessKey.trim() || secretKey.trim()
            ? {
                access_key_id: accessKey.trim(),
                secret_access_key: secretKey.trim(),
                session_token: sessionToken.trim() || null,
              }
            : {}),
          clear_credentials: clearCredentials,
        });
      }
      return createS3Profile({
        ...body,
        access_key_id: accessKey.trim() || null,
        secret_access_key: secretKey.trim() || null,
        session_token: sessionToken.trim() || null,
      });
    },
    onSuccess: onSaved,
    onError: (error: Error) => setMessage(error.message),
  });

  const keysMissing = Boolean(accessKey.trim()) !== Boolean(secretKey.trim());
  const canSave = name.trim() && bucket.trim() && region.trim() && !keysMissing;

  return (
    <Card className="mb-4">
      <CardContent className="grid gap-4 p-4 sm:grid-cols-2">
        <FieldGroup>
          <div className="space-y-1.5">
            <Label>Profile name</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Customer A archive"
            />
          </div>
        </FieldGroup>
        <FieldGroup>
          <div className="space-y-1.5">
            <Label>Bucket</Label>
            <Input
              value={bucket}
              onChange={(e) => setBucket(e.target.value)}
              placeholder="my-log-archive"
            />
          </div>
        </FieldGroup>
        <FieldGroup>
          <div className="space-y-1.5">
            <Label>Region</Label>
            <Input
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              placeholder="us-east-1"
            />
          </div>
        </FieldGroup>
        <FieldGroup>
          <div className="space-y-1.5">
            <Label>Key prefix (optional)</Label>
            <Input
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              placeholder="logvault/exports"
            />
          </div>
        </FieldGroup>
        <FieldGroup>
          <div className="space-y-1.5">
            <Label>S3-compatible endpoint (optional)</Label>
            <Input
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="https://minio.example.com"
            />
          </div>
        </FieldGroup>
        <div className="flex items-end pb-2">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={forcePathStyle}
              onChange={(e) => setForcePathStyle(e.target.checked)}
              className="h-4 w-4"
            />
            Force path-style addressing (MinIO)
          </label>
        </div>
        <div className="sm:col-span-2 space-y-3 border-t border-border pt-3">
          <p className="text-xs text-muted-foreground">
            Leave the access keys blank to use the worker&rsquo;s IAM role / default AWS credential
            chain.
            {profile ? " Existing keys are kept unless you enter new ones." : ""}
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>Access key ID</Label>
                <Input
                  type="password"
                  value={accessKey}
                  onChange={(e) => setAccessKey(e.target.value)}
                  placeholder={profile ? "leave blank to keep" : "optional"}
                  autoComplete="off"
                />
              </div>
            </FieldGroup>
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>Secret access key</Label>
                <Input
                  type="password"
                  value={secretKey}
                  onChange={(e) => setSecretKey(e.target.value)}
                  placeholder={profile ? "leave blank to keep" : "optional"}
                  autoComplete="off"
                />
              </div>
            </FieldGroup>
            <FieldGroup>
              <div className="space-y-1.5">
                <Label>Session token (optional)</Label>
                <Input
                  type="password"
                  value={sessionToken}
                  onChange={(e) => setSessionToken(e.target.value)}
                  placeholder="for temporary credentials"
                  autoComplete="off"
                />
              </div>
            </FieldGroup>
          </div>
          {keysMissing && (
            <p className="text-xs text-danger">
              Enter both the access key ID and secret key, or leave both blank.
            </p>
          )}
          {profile && (
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={clearCredentials}
                onChange={(e) => setClearCredentials(e.target.checked)}
                className="h-3.5 w-3.5"
              />
              Clear stored keys and use the worker&rsquo;s IAM role
            </label>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 sm:col-span-2">
          <p className="text-xs text-muted-foreground">
            The test writes a tiny object under the prefix and removes it.
          </p>
          <div className="flex items-center gap-2">
            {message && <span className="text-xs text-danger">{message}</span>}
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button onClick={() => save.mutate()} disabled={!canSave || save.isPending}>
              {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {profile ? "Save changes" : "Save profile"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function S3ProfileRow({ profile, onChange }: { profile: S3Profile; onChange: () => void }) {
  const [editing, setEditing] = React.useState(false);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [flash, setFlash] = React.useState<{ ok: boolean; message: string } | null>(null);
  const test = useMutation({
    mutationFn: () => testS3Profile(profile.id),
    onSuccess: (result) => setFlash({ ok: result.ok, message: result.message }),
    onError: (e: Error) => setFlash({ ok: false, message: e.message }),
  });
  const del = useMutation({
    mutationFn: () => deleteS3Profile(profile.id),
    onSuccess: onChange,
    onError: (e: Error) => setFlash({ ok: false, message: e.message }),
  });

  if (editing) {
    return (
      <S3ProfileForm
        profile={profile}
        onCancel={() => setEditing(false)}
        onSaved={() => {
          setEditing(false);
          onChange();
        }}
      />
    );
  }

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{profile.name}</span>
            <Badge tone="info">{profile.region}</Badge>
            {profile.force_path_style && <Badge tone="neutral">path-style</Badge>}
            <Badge tone="neutral">key {profile.key_preview ?? "instance role"}</Badge>
          </div>
          <p className="font-mono text-xs text-muted-foreground">
            s3://{profile.bucket}/{profile.prefix ? `${profile.prefix}/` : ""}…
          </p>
          {profile.endpoint_url && (
            <p className="font-mono text-xs text-muted-foreground">{profile.endpoint_url}</p>
          )}
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
        <div className="flex flex-wrap items-center gap-2">
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
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
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
              aria-label={`Delete ${profile.name}`}
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
