"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Search, ShieldCheck, Trash2 } from "lucide-react";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label, fieldClass } from "@/components/ui/input";
import {
  AuditEntry,
  AuthUser,
  createUser,
  deleteUser,
  useRole,
  listAudit,
  listUsers,
  getNotificationConfig,
  updateNotificationConfig,
} from "@/lib/api";
import { formatEpoch } from "@/lib/time";

export default function AdminPage() {
  const isAdmin = useRole() === "admin";
  return (
    <div className="mx-auto max-w-5xl animate-fade-in space-y-10 px-6 py-8">
      {isAdmin && <UserManagement />}
      {isAdmin && <NotificationSettings />}
      <AuditLog />
    </div>
  );
}

function UserManagement() {
  const qc = useQueryClient();
  const [adding, setAdding] = React.useState(false);
  const { data: users, isLoading } = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const del = useMutation({
    mutationFn: (id: number) => deleteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <div>
      <div className="flex items-end justify-between pb-4">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight">Users</h2>
          <p className="text-sm text-muted-foreground">Manage access to LogVault.</p>
        </div>
        <Button onClick={() => setAdding((v) => !v)} variant={adding ? "outline" : "primary"}>
          <Plus className="h-4 w-4" />
          {adding ? "Cancel" : "Add user"}
        </Button>
      </div>

      {adding && (
        <AddUserForm
          onDone={() => {
            setAdding(false);
            qc.invalidateQueries({ queryKey: ["users"] });
          }}
        />
      )}

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {users && users.length > 0 && (
        <div className="overflow-hidden border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Email</th>
                <th className="px-4 py-2 text-left font-medium">Name</th>
                <th className="px-4 py-2 text-left font-medium">Role</th>
                <th className="px-4 py-2 text-left font-medium">Joined</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users.map((u: AuthUser) => (
                <tr key={u.id} className="hover:bg-accent/40">
                  <td className="px-4 py-2 font-mono text-xs">{u.email}</td>
                  <td className="px-4 py-2 text-xs">{u.name}</td>
                  <td className="px-4 py-2">
                    <Badge tone={u.role === "admin" ? "warning" : "neutral"}>{u.role}</Badge>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                    {formatEpoch(Math.floor(Date.parse(u.created_at) / 1000))}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label="Delete user"
                      onClick={() => del.mutate(u.id)}
                      disabled={del.isPending}
                    >
                      <Trash2 className="h-4 w-4 text-danger" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function AddUserForm({ onDone }: { onDone: () => void }) {
  const [f, setF] = React.useState({ email: "", name: "", password: "", role: "member" });
  const mut = useMutation({ mutationFn: () => createUser(f), onSuccess: onDone });
  const valid = f.email && f.name && f.password.length >= 8;
  return (
    <Card className="mb-6">
      <CardContent className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label>Email</Label>
          <Input
            type="email"
            value={f.email}
            onChange={(e) => setF({ ...f, email: e.target.value })}
          />
        </div>
        <div className="space-y-1.5">
          <Label>Name</Label>
          <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label>Password (min 8 chars)</Label>
          <Input
            type="password"
            value={f.password}
            onChange={(e) => setF({ ...f, password: e.target.value })}
          />
        </div>
        <div className="space-y-1.5">
          <Label>Role</Label>
          <select
            className={fieldClass}
            value={f.role}
            onChange={(e) => setF({ ...f, role: e.target.value })}
          >
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div className="sm:col-span-2">
          <Button disabled={!valid || mut.isPending} onClick={() => mut.mutate()}>
            {mut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Create user
          </Button>
          {mut.isError && (
            <span className="ml-3 text-xs text-danger">{(mut.error as Error).message}</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function AuditLog() {
  const { data: audit, isLoading } = useQuery({ queryKey: ["audit"], queryFn: listAudit });
  const [search, setSearch] = React.useState("");

  const filtered = React.useMemo(() => {
    if (!audit || !search.trim()) return audit;
    const q = search.toLowerCase();
    return audit.filter(
      (a: AuditEntry) =>
        a.action.toLowerCase().includes(q) ||
        a.entity.toLowerCase().includes(q) ||
        (a.user_id ?? "").toLowerCase().includes(q)
    );
  }, [audit, search]);

  return (
    <div>
      <div className="flex items-end justify-between pb-4">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight">Audit log</h2>
          <p className="text-sm text-muted-foreground">Who did what.</p>
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            placeholder="Filter by action, entity, user…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 w-56 border border-border bg-background pl-8 pr-3 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {audit?.length === 0 && (
        <div className="flex flex-col items-center gap-3 border border-dashed border-border py-16 text-center">
          <div className="flex h-11 w-11 items-center justify-center bg-muted">
            <ShieldCheck className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium">No activity recorded yet</p>
        </div>
      )}

      {filtered?.length === 0 && (audit?.length ?? 0) > 0 && (
        <p className="py-8 text-center text-sm text-muted-foreground">
          No entries match &ldquo;{search}&rdquo;.
        </p>
      )}

      {(filtered?.length ?? 0) > 0 && (
        <div className="overflow-hidden border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-2.5 text-left font-medium">When (UTC)</th>
                <th className="px-4 py-2.5 text-left font-medium">User</th>
                <th className="px-4 py-2.5 text-left font-medium">Action</th>
                <th className="px-4 py-2.5 text-left font-medium">Entity</th>
                <th className="px-4 py-2.5 text-left font-medium">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered!.map((a: AuditEntry) => (
                <tr key={a.id} className="hover:bg-accent/40">
                  <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                    {formatEpoch(Math.floor(Date.parse(a.ts) / 1000))}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                    {a.user_id ?? <span className="opacity-40">—</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tone="info">{a.action}</Badge>
                  </td>
                  <td className="px-4 py-2.5">
                    {a.entity}
                    {a.entity_id != null && (
                      <span className="text-muted-foreground"> #{a.entity_id}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                    {a.metadata ? JSON.stringify(a.metadata) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function NotificationSettings() {
  const qc = useQueryClient();
  const [cfg, setCfg] = React.useState({
    slack_webhook_url: "",
    smtp_host: "",
    smtp_port: 587,
    smtp_user: "",
    smtp_password: "",
    smtp_from: "",
  });

  // Load what is stored so the form isn't blank every time. The password is
  // never returned — an empty field means "keep the stored one".
  const { data: saved, isLoading } = useQuery({
    queryKey: ["notification-config"],
    queryFn: getNotificationConfig,
  });

  React.useEffect(() => {
    if (!saved) return;
    setCfg({
      slack_webhook_url: saved.slack_webhook_url,
      smtp_host: saved.smtp_host,
      smtp_port: saved.smtp_port,
      smtp_user: saved.smtp_user,
      smtp_password: "",
      smtp_from: saved.smtp_from,
    });
  }, [saved]);

  // Went through a Next route handler that resolved NEXT_PUBLIC_API_BASE_URL
  // ("http://localhost:8000") server-side — inside the web container that is its
  // own loopback, so every save died as "TypeError: fetch failed". It also
  // forwarded no bearer token. This is a direct, authenticated call like every
  // other mutation in the app.
  const save = useMutation({
    mutationFn: () => updateNotificationConfig(cfg),
    onSuccess: () => {
      setCfg((c) => ({ ...c, smtp_password: "" }));
      qc.invalidateQueries({ queryKey: ["notification-config"] });
    },
  });

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">Notifications</h2>
          <p className="text-sm text-muted-foreground">Configure Slack and email for job failure alerts.</p>
        </div>

        <div className="space-y-3 border-t border-border pt-4">
          <h3 className="text-sm font-medium">Slack</h3>
          <div className="space-y-1.5">
            <Label>Webhook URL</Label>
            <Input
              type="text"
              value={cfg.slack_webhook_url}
              onChange={(e) => setCfg({ ...cfg, slack_webhook_url: e.target.value })}
              placeholder="https://hooks.slack.com/services/..."
            />
            <p className="text-xs text-muted-foreground">
              Get from Slack App → Incoming Webhooks
            </p>
          </div>
        </div>

        <div className="space-y-3 border-t border-border pt-4">
          <h3 className="text-sm font-medium">Email (SMTP)</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Host</Label>
              <Input
                value={cfg.smtp_host}
                onChange={(e) => setCfg({ ...cfg, smtp_host: e.target.value })}
                placeholder="smtp.gmail.com"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Port</Label>
              <Input
                type="number"
                value={cfg.smtp_port}
                onChange={(e) => setCfg({ ...cfg, smtp_port: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>User</Label>
              <Input
                value={cfg.smtp_user}
                onChange={(e) => setCfg({ ...cfg, smtp_user: e.target.value })}
                placeholder="your-email@gmail.com"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Password</Label>
              <Input
                type="password"
                autoComplete="new-password"
                value={cfg.smtp_password}
                onChange={(e) => setCfg({ ...cfg, smtp_password: e.target.value })}
                placeholder={saved?.smtp_password_set ? "•••••••• (unchanged)" : "app-specific password"}
              />
              {saved?.smtp_password_set && !cfg.smtp_password && (
                <p className="text-xs text-muted-foreground">
                  A password is stored. Leave blank to keep it.
                </p>
              )}
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label>From Email</Label>
              <Input
                value={cfg.smtp_from}
                onChange={(e) => setCfg({ ...cfg, smtp_from: e.target.value })}
                placeholder="alerts@example.com"
              />
            </div>
          </div>
        </div>

        <div className="space-y-2 border-t border-border pt-4">
          <p className="text-xs text-muted-foreground">
            Applies immediately — settings are read when an alert is sent, so no restart is needed.
          </p>
          <div className="flex items-center gap-2">
            <Button disabled={save.isPending || isLoading} onClick={() => save.mutate()}>
              {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save settings
            </Button>
            {save.isSuccess && <span className="text-xs text-success">✓ Saved</span>}
            {save.isError && (
              <span className="text-xs text-danger">
                {(save.error as Error).message}
              </span>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
