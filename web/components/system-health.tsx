"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Cpu, HardDrive, MemoryStick } from "lucide-react";
import * as React from "react";
import { Card, CardContent } from "@/components/ui/card";
import { IconBadge } from "@/components/ui/icon-badge";
import { getHealthMetrics } from "@/lib/api";

/**
 * Host pressure shown where people actually look. Disk is the one that matters
 * most: exports and Postgres share the filesystem, so filling it makes the
 * whole platform read-only — worth seeing before a slow extraction is blamed on
 * Last9.
 */
export function useHealthMetrics() {
  return useQuery({
    queryKey: ["health-metrics"],
    queryFn: getHealthMetrics,
    refetchInterval: 30_000,
    staleTime: 20_000,
  });
}

type Tone = "ok" | "near" | "breach";

function toneFor(value: number | undefined, threshold: number | undefined): Tone {
  if (value == null || !threshold) return "ok";
  if (value >= threshold) return "breach";
  // A metric within 10% of its threshold is worth a warning colour: it is
  // usually the run that starts before the breach.
  if (value >= threshold * 0.9) return "near";
  return "ok";
}

const BAR: Record<Tone, string> = {
  ok: "bg-success",
  near: "bg-warning",
  breach: "bg-danger",
};

const TEXT: Record<Tone, string> = {
  ok: "text-muted-foreground",
  near: "text-warning",
  breach: "text-danger font-semibold",
};

function MiniMeter({
  label,
  icon,
  value,
  threshold,
  detail,
  compact,
}: {
  label: string;
  icon: React.ReactNode;
  value: number | undefined;
  threshold: number | undefined;
  detail: string;
  compact: boolean;
}) {
  const tone = toneFor(value, threshold);
  const pct = value == null ? 0 : Math.min(100, value);
  const limit = threshold ?? 100;
  return (
    <div className="min-w-0 space-y-1" title={`${label}: ${value ?? "—"}% (limit ${limit}%)`}>
      <div className="flex items-baseline justify-between gap-2 text-[11px] leading-none">
        <span className="flex min-w-0 items-center gap-1 font-medium">
          {icon}
          <span className="truncate">{label}</span>
        </span>
        <span className={`shrink-0 font-mono tabular-nums ${TEXT[tone]}`}>
          {value == null ? "—" : `${value}%`}
          {!compact && <span className="ml-1 opacity-60">/ {limit}%</span>}
        </span>
      </div>
      <div
        className="relative h-1 w-full overflow-hidden bg-muted"
        role="meter"
        aria-label={label}
        aria-valuenow={value ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={`h-full transition-all duration-500 ${BAR[tone]}`}
          style={{ width: `${pct}%` }}
        />
        {/* Threshold marker, so "how close" is visible at a glance. */}
        {threshold != null && threshold < 100 && (
          <span
            className="absolute top-0 h-full w-px bg-foreground/40"
            style={{ left: `${threshold}%` }}
            aria-hidden
          />
        )}
      </div>
      {!compact && <p className="truncate text-[10px] text-muted-foreground">{detail}</p>}
    </div>
  );
}

/**
 * Dashboard card. Same shape as the stat cards beside it - one icon badge, one
 * value line, one label - so the row reads as a single strip. Colour encodes
 * the worst metric: green normally, amber within 10% of a threshold, red at
 * breach.
 *
 * Disk matters most: exports and Postgres share the filesystem, so filling it
 * makes the whole platform read-only.
 */
export function SystemHealthCard() {
  const { data, isError } = useHealthMetrics();
  const thresholds = data?.thresholds ?? { cpu: 85, memory: 85, disk: 85 };

  const meters = [
    { key: "cpu" as const, short: "CPU", name: "CPU", value: data?.cpu_pct, limit: thresholds.cpu },
    {
      key: "memory" as const,
      short: "MEM",
      name: "Memory",
      value: data?.memory_pct,
      limit: thresholds.memory,
    },
    {
      key: "disk" as const,
      short: "DISK",
      name: "Disk",
      value: data?.disk_pct,
      limit: thresholds.disk,
    },
  ];

  const tones = meters.map((m) => toneFor(m.value, m.limit));
  const worst: Tone = tones.includes("breach") ? "breach" : tones.includes("near") ? "near" : "ok";
  const badge: "green" | "yellow" | "red" =
    worst === "breach" ? "red" : worst === "near" ? "yellow" : "green";

  const label =
    isError || (data && !data.available)
      ? "System health - no sample yet"
      : worst === "breach"
        ? "System health - threshold breached"
        : worst === "near"
          ? "System health - near limit"
          : "System health";

  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-3.5">
        <IconBadge icon={Activity} color={badge} size="sm" />
        <div className="min-w-0">
          <div className="flex items-baseline gap-1.5 font-mono text-[13px] font-semibold leading-tight tracking-tight">
            {meters.map((m, index) => (
              <React.Fragment key={m.key}>
                {index > 0 && <span className="text-border">.</span>}
                <span
                  className={TEXT[tones[index]]}
                  title={`${m.name}: ${m.value ?? "-"}% (limit ${m.limit}%)`}
                >
                  {m.short} {m.value == null ? "-" : `${m.value}%`}
                </span>
              </React.Fragment>
            ))}
          </div>
          <p className="truncate text-[11px] text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

/** Fuller variant for the admin card: same meters, limits and details shown. */
export function HealthMeters({
  metrics,
}: {
  metrics: ReturnType<typeof useHealthMetrics>["data"];
}) {
  const thresholds = metrics?.thresholds ?? { cpu: 85, memory: 85, disk: 85 };
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <MiniMeter
        label="CPU"
        icon={<Cpu className="h-3 w-3" />}
        value={metrics?.cpu_pct}
        threshold={thresholds.cpu}
        detail={metrics?.load1 != null ? `load ${metrics.load1}` : "1s sample"}
        compact={false}
      />
      <MiniMeter
        label="Memory"
        icon={<MemoryStick className="h-3 w-3" />}
        value={metrics?.memory_pct}
        threshold={thresholds.memory}
        detail={
          metrics?.memory_used_mb != null
            ? `${metrics.memory_used_mb} / ${metrics.memory_total_mb} MB`
            : "—"
        }
        compact={false}
      />
      <MiniMeter
        label="Disk"
        icon={<HardDrive className="h-3 w-3" />}
        value={metrics?.disk_pct}
        threshold={thresholds.disk}
        detail={
          metrics?.disk_free_gb != null
            ? `${metrics.disk_free_gb} GB free of ${metrics.disk_total_gb} GB${
                metrics.disk_path ? ` on ${metrics.disk_path}` : ""
              }`
            : "—"
        }
        compact={false}
      />
    </div>
  );
}
