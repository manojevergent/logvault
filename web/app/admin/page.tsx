"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Loader2, Plus, Search, ShieldCheck, Trash2 } from "lucide-react";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label, fieldClass } from "@/components/ui/input";
import { HealthMeters, useHealthMetrics } from "@/components/system-health";
import {
  AuditEntry,
  AuthUser,
  HealthAlertConfig,
  Last9EndpointTestResult,
  createUser,
  deleteUser,
  getHealthAlertConfig,
  getLast9Endpoint,
  getWorkerCapacity,
  setWorkerConcurrency,
  testHealthAlert,
  testLast9Endpoint,
  updateHealthAlertConfig,
  updateLast9Endpoint,
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
      {isAdmin && <Last9EndpointSettings />}
      {isAdmin && <NotificationSettings />}
      {isAdmin && <SystemHealthSettings />}
      {isAdmin && <WorkerCapacityCard />}
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
      <div className="flex flex-wrap items-end justify-between gap-3 pb-4">
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
      <div className="flex flex-wrap items-end justify-between gap-3 pb-4">
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

function SystemHealthSettings() {
  const qc = useQueryClient();
  const { data: saved, isLoading } = useQuery({
    queryKey: ["health-alert-config"],
    queryFn: getHealthAlertConfig,
  });
  const metricsQuery = useHealthMetrics();
  const metrics = metricsQuery.data;

  const [cfg, setCfg] = React.useState<HealthAlertConfig>({
    enabled: true,
    cpu_threshold_pct: 85,
    memory_threshold_pct: 85,
    disk_threshold_pct: 85,
    disk_path: "",
    cooldown_minutes: 30,
    slack: true,
    email: false,
    recipients: [],
    notify_on_recovery: true,
  });
  const [recipientsText, setRecipientsText] = React.useState("");

  React.useEffect(() => {
    if (!saved) return;
    setCfg({
      enabled: saved.enabled,
      cpu_threshold_pct: saved.cpu_threshold_pct,
      memory_threshold_pct: saved.memory_threshold_pct,
      disk_threshold_pct: saved.disk_threshold_pct,
      disk_path: saved.disk_path ?? "",
      cooldown_minutes: saved.cooldown_minutes,
      slack: saved.slack,
      email: saved.email,
      recipients: saved.recipients,
      notify_on_recovery: saved.notify_on_recovery,
    });
    setRecipientsText(saved.recipients.join(", "));
  }, [saved]);

  const save = useMutation({
    mutationFn: () =>
      updateHealthAlertConfig({
        ...cfg,
        recipients: recipientsText
          .split(/[,\s]+/)
          .map((r) => r.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["health-alert-config"] });
    },
  });
  const test = useMutation({ mutationFn: testHealthAlert });

  const noChannel = !cfg.slack && !cfg.email;
  const emailWithoutRecipients =
    cfg.email &&
    recipientsText
      .split(/[,\s]+/)
      .map((r) => r.trim())
      .filter(Boolean).length === 0;

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">System health alerts</h2>
          <p className="text-sm text-muted-foreground">
            Alert Slack and/or email when CPU, memory or disk crosses a threshold. Sampled by the
            worker every minute.
          </p>
        </div>

        <div className="space-y-3 border-t border-border pt-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium">Current usage</h3>
            {metrics?.available ? (
              <span className="font-mono text-[11px] text-muted-foreground">
                {metrics.ts ? new Date(metrics.ts).toLocaleTimeString() : ""}
              </span>
            ) : (
              <span className="text-[11px] text-muted-foreground">
                {metrics?.message ?? "Waiting for the worker's first sample…"}
              </span>
            )}
          </div>
          <HealthMeters metrics={metrics} />
        </div>

        <div className="space-y-3 border-t border-border pt-4">
          <h3 className="text-sm font-medium">Thresholds</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label>CPU %</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={cfg.cpu_threshold_pct}
                onChange={(e) => setCfg({ ...cfg, cpu_threshold_pct: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Memory %</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={cfg.memory_threshold_pct}
                onChange={(e) => setCfg({ ...cfg, memory_threshold_pct: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Disk %</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={cfg.disk_threshold_pct}
                onChange={(e) => setCfg({ ...cfg, disk_threshold_pct: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Re-alert cooldown (minutes)</Label>
              <Input
                type="number"
                min={1}
                max={1440}
                value={cfg.cooldown_minutes}
                onChange={(e) => setCfg({ ...cfg, cooldown_minutes: Number(e.target.value) })}
              />
              <p className="text-[11px] text-muted-foreground">
                A breach alerts once, then again only after this long.
              </p>
            </div>
            <label className="flex items-end gap-2 pb-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={cfg.notify_on_recovery}
                onChange={(e) => setCfg({ ...cfg, notify_on_recovery: e.target.checked })}
              />
              Notify when a metric recovers
            </label>
            <label className="flex items-end gap-2 pb-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={cfg.enabled}
                onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
              />
              Monitoring enabled
            </label>
          </div>
          <div className="space-y-1.5">
            <Label>Disk path</Label>
            <Input
              value={cfg.disk_path}
              onChange={(e) => setCfg({ ...cfg, disk_path: e.target.value })}
              placeholder="/data/exports"
            />
            <p className="text-[11px] text-muted-foreground">
              Leave blank to monitor the export volume. A path that does not exist in the worker
              falls back to that volume.
            </p>
          </div>
        </div>

        <div className="space-y-3 border-t border-border pt-4">
          <h3 className="text-sm font-medium">Destination</h3>
          <div className="flex flex-wrap items-center gap-5">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={cfg.slack}
                onChange={(e) => setCfg({ ...cfg, slack: e.target.checked })}
              />
              Slack (uses the webhook above)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={cfg.email}
                onChange={(e) => setCfg({ ...cfg, email: e.target.checked })}
              />
              Email (uses the SMTP config above)
            </label>
          </div>
          <div className="space-y-1.5">
            <Label>Email recipients</Label>
            <Input
              value={recipientsText}
              onChange={(e) => setRecipientsText(e.target.value)}
              placeholder="ops@example.com, alerts@example.com"
            />
          </div>
          {noChannel && (
            <p className="text-xs text-warning">
              No destination selected — breaches will be recorded but nobody notified.
            </p>
          )}
          {emailWithoutRecipients && (
            <p className="text-xs text-warning">
              Email is on but there are no recipients; add one or switch email off.
            </p>
          )}
          {!cfg.email && recipientsText.trim() && (
            <p className="text-xs text-warning">
              Recipients are set but <strong>email is switched off</strong> — test alerts and breach
              alerts will not be emailed.
            </p>
          )}
        </div>

        <div className="space-y-2 border-t border-border pt-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              disabled={save.isPending || isLoading || noChannel || emailWithoutRecipients}
              onClick={() => save.mutate()}
            >
              {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save alerts
            </Button>
            <Button
              variant="outline"
              disabled={test.isPending || noChannel || emailWithoutRecipients}
              onClick={() => test.mutate()}
            >
              {test.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Send test alert
            </Button>
            {save.isSuccess && <span className="text-xs text-success">✓ Saved</span>}
            {test.data && (
              <span className={`text-xs ${test.data.ok ? "text-success" : "text-danger"}`}>
                {test.data.message}
              </span>
            )}
            {save.isError && (
              <span className="text-xs text-danger">{(save.error as Error).message}</span>
            )}
            {test.isError && (
              <span className="text-xs text-danger">{(test.error as Error).message}</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Thresholds apply on the next sample — the worker reads them every tick.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function WorkerCapacityCard() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["worker-capacity"],
    queryFn: getWorkerCapacity,
    refetchInterval: 15_000,
  });
  const [target, setTarget] = React.useState<string>("");

  React.useEffect(() => {
    if (data?.running != null) setTarget(String(data.running));
  }, [data?.running]);

  const apply = useMutation({
    mutationFn: () => setWorkerConcurrency(Number(target)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["worker-capacity"] }),
  });

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="space-y-1">
          <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
            <Activity className="h-4 w-4 text-primary" />
            Worker capacity
          </h2>
          <p className="text-sm text-muted-foreground">
            Extraction slots. Jobs beyond this queue until a slot frees.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4 text-sm">
          <Badge tone={data?.available ? "success" : "warning"}>
            {data?.available
              ? `${data.nodes} worker${data.nodes === 1 ? "" : "s"}`
              : "no worker answering"}
          </Badge>
          <span className="font-mono text-xs">
            running {data?.running ?? "—"} · active {data?.active_jobs ?? 0} · configured{" "}
            {data?.configured ?? "—"}
          </span>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <Label>Set slots</Label>
            <Input
              type="number"
              min={1}
              max={64}
              className="w-28"
              value={target}
              onChange={(e) => setTarget(e.target.value.replace(/[^0-9]/g, ""))}
            />
          </div>
          <Button
            disabled={apply.isPending || !target || Number(target) < 1}
            onClick={() => apply.mutate()}
          >
            {apply.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Apply now
          </Button>
          {apply.data && (
            <span className="text-xs text-muted-foreground">{apply.data.message}</span>
          )}
          {apply.isError && (
            <span className="text-xs text-danger">{(apply.error as Error).message}</span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          A running change is lost on restart. Set{" "}
          <span className="font-mono">WORKER_CONCURRENCY</span> in{" "}
          <span className="font-mono">.env</span> to make it permanent. Each extra slot streams
          another extraction, so watch CPU, memory and Last9 quota.
        </p>
      </CardContent>
    </Card>
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
          <p className="text-sm text-muted-foreground">
            Configure Slack and email for job failure alerts.
          </p>
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
            <p className="text-xs text-muted-foreground">Get from Slack App → Incoming Webhooks</p>
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
                placeholder={
                  saved?.smtp_password_set ? "•••••••• (unchanged)" : "app-specific password"
                }
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
              <span className="text-xs text-danger">{(save.error as Error).message}</span>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * The Last9 API base URL. SaaS deployments keep the default; a BYOC install
 * points this at the Last9 instance in their own cloud. Saved in the database
 * and read at call time, so switching hosts needs no image rebuild.
 */
function Last9EndpointSettings() {
  const qc = useQueryClient();
  const { data: saved, isLoading } = useQuery({
    queryKey: ["last9-endpoint"],
    queryFn: getLast9Endpoint,
  });
  const [apiBase, setApiBase] = React.useState("");
  const [probe, setProbe] = React.useState<Last9EndpointTestResult | null>(null);

  React.useEffect(() => {
    if (saved) setApiBase(saved.api_base);
  }, [saved]);

  const save = useMutation({
    mutationFn: () => updateLast9Endpoint(apiBase),
    onSuccess: () => {
      setProbe(null);
      qc.invalidateQueries({ queryKey: ["last9-endpoint"] });
      // The read-only settings page shows the active URL too.
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });
  const test = useMutation({
    mutationFn: () => testLast9Endpoint(apiBase),
    onSuccess: setProbe,
  });

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">Last9 endpoint</h2>
          <p className="text-sm text-muted-foreground">
            Where extractions read logs from. Change it when Last9 runs in your own cloud (BYOC).
          </p>
        </div>

        <div className="space-y-1.5 border-t border-border pt-4">
          <Label>API base URL</Label>
          <Input
            value={apiBase}
            spellCheck={false}
            onChange={(e) => {
              setApiBase(e.target.value);
              setProbe(null);
            }}
            placeholder="https://app.last9.io/api/v4"
          />
          <p className="text-xs text-muted-foreground">
            Include the API version path, e.g.{" "}
            <code className="font-mono">https://last9.internal.example.com/api/v4</code>.{" "}
            {saved?.source === "env"
              ? "No saved value — the deployment default is in use."
              : "Saved value in use."}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
          <Button
            disabled={save.isPending || isLoading || !apiBase.trim()}
            onClick={() => save.mutate()}
          >
            {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Save endpoint
          </Button>
          <Button
            variant="outline"
            disabled={test.isPending || !apiBase.trim()}
            onClick={() => test.mutate()}
          >
            {test.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Test connection
          </Button>
          {save.isSuccess && <span className="text-xs text-success">✓ Saved</span>}
          {save.isError && (
            <span className="text-xs text-danger">{(save.error as Error).message}</span>
          )}
          {probe && (
            <span className={`text-xs ${probe.ok ? "text-success" : "text-danger"}`}>
              {probe.message}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Applies to the next request and the next job — no restart. Jobs already running keep the
          endpoint they started with.
        </p>
      </CardContent>
    </Card>
  );
}
