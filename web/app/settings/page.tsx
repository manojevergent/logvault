"use client";

import { useQuery } from "@tanstack/react-query";
import { getSettings } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

export default function SettingsPage() {
  const { data, isLoading } = useQuery({ queryKey: ["settings"], queryFn: getSettings });

  const rows: [string, string][] = data
    ? [
        ["Environment", data.environment],
        ["Default org slug", data.default_org_slug],
        ["Storage directory", data.storage_dir],
        ["Export retention", `${data.export_retention_days} days`],
        ["Download link TTL", `${Math.round(data.download_url_ttl_seconds / 86400)} days`],
        ["Regions configured", String(data.region_count)],
      ]
    : [];

  return (
    <div className="mx-auto max-w-3xl animate-fade-in px-6 py-8">
      <div className="space-y-1.5 pb-6">
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Environment configuration (read-only; set via env vars).
        </p>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {data && (
        <Card>
          <CardContent className="divide-y divide-border p-0">
            {rows.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between px-5 py-3">
                <span className="text-sm text-muted-foreground">{k}</span>
                <span className="font-mono text-sm">{v}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
